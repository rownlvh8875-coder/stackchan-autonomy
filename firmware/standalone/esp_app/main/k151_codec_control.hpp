// SPDX-License-Identifier: MIT
#pragma once
#include "k151_speaker_startup_stage.hpp"
#include <array>
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <type_traits>
#include <audio_codec_ctrl_if.h>

namespace stackchan::standalone {
// Non-owning error observer, confined to the codec port's owner task. The SDK
// codec can discard register errors; latch them independently. The AW88298
// staging profile also holds the output disabled through SDK initialization.
class K151CodecControl final : private audio_codec_ctrl_if_t {
 public:
  enum class Profile { observe, aw88298_muted_startup };

  explicit K151CodecControl(Profile profile = Profile::observe)
      : audio_codec_ctrl_if_t{}, profile_(profile) {
    is_open = opened; read_reg = read; write_reg = write; get_info = info;
    // Only the owner opens/closes/frees the original SDK interface.
  }
  K151CodecControl(const K151CodecControl&) = delete;
  K151CodecControl& operator=(const K151CodecControl&) = delete;
  const audio_codec_ctrl_if_t* interface() const { return this; }
  bool attach(const audio_codec_ctrl_if_t* base) {
    if (attempted_) return false;
    attempted_ = true;
    if (!base || !base->is_open || !base->read_reg || !base->write_reg ||
        !base->get_info || !base->is_open(base)) {
      record(ESP_CODEC_DEV_WRONG_STATE); return false;
    }
    base_ = base; return true;
  }
  void detach() { base_ = nullptr; } // After codec deletion; fault survives.
  bool faulted() const { return failed_.load(); }
  bool healthy() const { return opened(this) && !faulted(); }
  void begin_cleanup() { cleaning_up_ = true; }
  bool cleanup_faulted() const { return cleanup_failed_; }
  bool muted_startup_verified() const {
    return profile_ == Profile::aw88298_muted_startup &&
           verified_ == (kPowerVerified | kMuteVerified | kAttenuationVerified) && healthy();
  }
  bool aw88298_standby_verified(std::optional<bool>* uvls = nullptr,
                               K151SpeakerCleanupStage* failure = nullptr) {
    using Cleanup = K151SpeakerCleanupStage;
    if (profile_ != Profile::aw88298_muted_startup || !healthy()) {
      if (failure) *failure = Cleanup::standby_control_unavailable;
      return false;
    }
    uint16_t status{};
    const auto check = standby_register_check([&](int reg, std::array<uint8_t, 2>& value) {
      return read(this, reg, 1, value.data(), value.size()) == ESP_CODEC_DEV_OK;
    }, uvls ? &status : nullptr);
    if (failure) *failure = check;
    const bool verified = check == Cleanup::none;
    if (uvls && verified) *uvls = (status & aw88298_protection::undervoltage) != 0;
    return verified;
  }
  bool request_aw88298_standby() {
    if (profile_ != Profile::aw88298_muted_startup || !opened(this)) return false;
    const auto update = [&](int reg) {
      std::array<uint8_t, 2> value{};
      return read(this, reg, 1, value.data(), value.size()) == ESP_CODEC_DEV_OK &&
             write_aw88298(reg, 1, value.data(), value.size(), true) == ESP_CODEC_DEV_OK;
    };
    // Force HMUTE before power-down. Attempt power-down even if mute was
    // unsuccessful. Only these two masked writes may run after a fault.
    const bool mute = update(0x05);
    const bool power = update(0x04);
    return mute && power;
  }

  // The caller owns the enabled I2S TX and must close through standby or reset
  // on failure, including revocation detected during the unmute transaction.
  template <typename Allowed, typename Clock, typename Pause, typename VoltageRead = std::nullptr_t,
            typename StatusRead = std::nullptr_t>
  [[nodiscard]] K151SpeakerStartupDiagnostic start_aw88298_low_volume(Allowed allowed, Clock clock,
      Pause pause, VoltageRead read_voltage = nullptr, StatusRead read_followup = nullptr) {
    using Stage = K151SpeakerStartupStage;
    using Exit = K151ClockWaitExit;
    using Sample = K151ClockWaitSample;
    constexpr int64_t kStartupLimitUs = 100'000;
    constexpr int64_t kStageSettleUs = 2'000;
    constexpr uint16_t kNoReference = 0x0020; // NOCLKS
    constexpr uint16_t kInternalClock = 0x0010; // CLKS
    constexpr uint16_t kPllLocked = 0x0001; // PLLS
    constexpr uint16_t kClockLocked = kInternalClock | kPllLocked;
    constexpr uint16_t kClockMask = kNoReference | kClockLocked;
    constexpr uint16_t kSwitching = 0x0100;
    constexpr auto kUnderVoltage = aw88298_protection::undervoltage;
    static_assert(aw88298_protection::mask == 0xcc0a);
    constexpr uint8_t kPowerMask = 0x43; // I2SEN, AMPPD, PWDN
    constexpr uint8_t kStandbyI2s = 0x43; // I2S configured before system power-up
    constexpr uint8_t kConfiguring = 0x42; // I2S enabled, amplifier still off
    constexpr uint8_t kOperating = 0x40;
    constexpr uint8_t kHardMute = 0x10;

    if (!allowed() || !muted_startup_verified()) return {Stage::muted_admission};
    const int64_t started = clock();
    if (started < 0) return {Stage::clock_origin};
    int64_t sampled = started;
    auto wait_exit = Exit::none;
    auto last_status = Sample::unobserved;
    uint16_t protection_flags = 0;
    int32_t settling_uvls_us = -1;
    int32_t clock_ready_after_uvls_us = -1;
    const auto live = [&] {
      if (!allowed() || !healthy()) {
        wait_exit = Exit::admission_lost;
        return false;
      }
      const int64_t observed = clock();
      if (observed < sampled) {
        wait_exit = Exit::timer_regressed;
        return false;
      }
      if (observed - started >= kStartupLimitUs) {
        wait_exit = Exit::startup_deadline;
        return false;
      }
      sampled = observed;
      return true;
    };
    const auto read_live = [&](int reg, std::array<uint8_t, 2>& value) {
      if (!live()) return false;
      if (read(this, reg, 1, value.data(), value.size()) != ESP_CODEC_DEV_OK) {
        wait_exit = Exit::status_read_failed;
        return false;
      }
      return live();
    };
    const auto transition = [&](int reg, uint8_t mask, uint8_t before, uint8_t after) {
      std::array<uint8_t, 2> value{};
      if (!read_live(reg, value) || (value[1] & mask) != before) return false;
      value[1] = (value[1] & ~mask) | after;
      // SDK writes still use the muted profile. Only these owner-task stages
      // directly change the protected low-byte bits.
      verified_ &= ~(reg == 0x04 ? kPowerVerified : kMuteVerified);
      if (!live() ||
          record(base_->write_reg(base_, reg, 1, value.data(), value.size())) != ESP_CODEC_DEV_OK)
        return false;
      if (!read_live(reg, value)) return false;
      return (value[1] & mask) == after;
    };
    const auto read_status = [&](uint16_t& status) {
      std::array<uint8_t, 2> value{};
      if (!read_live(0x01, value)) return false; // SYSST is not clear-on-read.
      status = (static_cast<uint16_t>(value[0]) << 8) | value[1];
      if (status & kNoReference) last_status = Sample::reference_missing;
      else if (!(status & kPllLocked)) last_status = Sample::pll_unlocked;
      else if (!(status & kInternalClock)) last_status = Sample::internal_unstable;
      else last_status = Sample::stable;
      protection_flags = status & aw88298_protection::mask;
      return true;
    };
    const auto await_stage = [&](bool operating, uint16_t& status) {
      const int64_t stage_started = sampled; // Sampled after the stage write/readback.
      const uint16_t expected = kClockLocked | (operating ? kSwitching : 0);
      // The poll count also bounds failure if the injected clock never advances.
      for (int poll = 0; poll < 100; ++poll) {
        if (!read_status(status)) return false;
        const auto elapsed = sampled - stage_started;
        if (protection_flags) {
          // During the existing clock setup interval, an isolated UVLS keeps
          // the output powered down and muted. All other faults stop now.
          if (operating || (status & kSwitching) || protection_flags != kUnderVoltage ||
              elapsed >= kStageSettleUs) {
            wait_exit = Exit::protection_active;
            return false;
          }
          if (settling_uvls_us < 0) settling_uvls_us = static_cast<int32_t>(elapsed);
          protection_flags = 0; // Terminal protection; the earlier sample has its own field.
        } else {
          if (!operating && (status & kSwitching)) {
            wait_exit = Exit::early_switching;
            return false;
          }
          if (elapsed >= kStageSettleUs &&
              (status & (kClockMask | kSwitching)) == expected) return true;
        }
        if (!live()) return false;
        pause();
      }
      wait_exit = Exit::poll_limit;
      return false;
    };

    std::array<uint8_t, 2> value{};
    uint16_t standby_status{};
    if (standby_register_check(read_live, &standby_status) != K151SpeakerCleanupStage::none)
      return {Stage::standby_readback};
    // AW88298 Table 2 configures the I2S data path in standby, then clears PWDN.
    if (!transition(0x04, kPowerMask, 0x03, kStandbyI2s)) return {Stage::i2s_enable};
    if (!transition(0x04, kPowerMask, kStandbyI2s, kConfiguring)) return {Stage::clock_enable};
    const auto clock_verified = sampled;
    uint16_t status{};
    if (!await_stage(false, status)) {
      K151SpeakerStartupDiagnostic failure{Stage::wait_clock, wait_exit, last_status, protection_flags};
      failure.settling_uvls_us = settling_uvls_us;
      if (protection_flags & kUnderVoltage)
        failure.standby_uvls = (standby_status & kUnderVoltage) != 0;
      if constexpr (!std::is_same_v<VoltageRead, std::nullptr_t>) {
        constexpr int64_t kVoltageReadReserveUs = 30'000;
        if (wait_exit == Exit::protection_active && (protection_flags & kUnderVoltage)) {
          const auto fault_observed = sampled;
          failure.uvls_after_clock_us = static_cast<int32_t>(fault_observed - clock_verified);
          failure.vdd = {k151::PowerSample::skipped};
          // The VDD read cannot change the failure or proceed to amplification.
          // Keep the existing HW mute and powered-down output stage throughout.
          if (protection_flags == kUnderVoltage && !(status & kSwitching) && live() &&
              sampled - started <= kStartupLimitUs - kVoltageReadReserveUs) {
            const auto reading = read_voltage();
            if (live()) {
              failure.vdd = reading;
              if (reading.state != k151::PowerSample::not_seen)
                failure.vdd_after_uvls_us = static_cast<int32_t>(sampled - fault_observed);
              if constexpr (!std::is_same_v<StatusRead, std::nullptr_t>) {
                constexpr int64_t kStatusReadReserveUs = 10'000;
                const auto vdd_observed = sampled;
                // Record a second SYSST sample without updating the first fault.
                // The observer cannot enable the amplifier or clear SYSINT.
                if (reading.state == k151::PowerSample::sampled && live() &&
                    sampled - started <= kStartupLimitUs - kStatusReadReserveUs) {
                  const auto followup = read_followup();
                  if (live() && followup) {
                    failure.uvls_after_vdd = *followup;
                    failure.uvls_after_vdd_us = static_cast<int32_t>(sampled - vdd_observed);
                  }
                }
              }
            }
          }
        }
      }
      return failure;
    }
    const auto result = [&](Stage stage, uint16_t flags = 0) {
      K151SpeakerStartupDiagnostic report{stage, Exit::none, Sample::none, flags};
      report.settling_uvls_us = settling_uvls_us;
      report.clock_ready_after_uvls_us = clock_ready_after_uvls_us;
      return report;
    };
    constexpr auto kStatusMask = kClockMask | kSwitching;
    if (!read_live(0x05, value) || !(value[1] & kHardMute)) return result(Stage::mute_readback);
    // Confirm a fresh, clear status after checking HMUTE and before clearing AMPPD.
    if (!read_status(status) || protection_flags || (status & kStatusMask) != kClockLocked)
      return result(Stage::pre_amplifier_status, protection_flags);
    if (settling_uvls_us >= 0)
      clock_ready_after_uvls_us = static_cast<int32_t>(sampled - clock_verified);
    if (!transition(0x04, kPowerMask, kConfiguring, kOperating)) return result(Stage::amplifier_enable);
    if (!await_stage(true, status))
      return result(Stage::wait_switching, protection_flags);
    if (!read_live(0x0c, value) || value[0] < kMinAttenuation || value[0] > kMaxAttenuation)
      return result(Stage::attenuation);
    constexpr auto kReady = kClockLocked | kSwitching;
    if (!read_status(status) || protection_flags || (status & kStatusMask) != kReady)
      return result(Stage::pre_unmute_status, protection_flags);
    if (!transition(0x05, kHardMute, kHardMute, 0)) return result(Stage::unmute);
    if (!read_status(status) || protection_flags || (status & kStatusMask) != kReady)
      return result(Stage::post_unmute_status, protection_flags);
    return result(Stage::none);
  }
 private:
  static constexpr uint8_t kPowerVerified = 1, kMuteVerified = 2, kAttenuationVerified = 4;
  static constexpr uint8_t kMinAttenuation = 0x60, kMaxAttenuation = 0xc0;

  template <typename Read>
  static K151SpeakerCleanupStage standby_register_check(Read read_word, uint16_t* status) {
    using Cleanup = K151SpeakerCleanupStage;
    std::array<uint8_t, 2> value{};
    // ID, SYSCTRL, SYSCTRL2 and SYSST. SYSINT is clear-on-read and is not used.
    if (!read_word(0x00, value)) return Cleanup::standby_id_read;
    if (value[0] != 0x18 || value[1] != 0x52) return Cleanup::standby_id_mismatch;
    if (!read_word(0x04, value)) return Cleanup::standby_power_read;
    if ((value[1] & 0x43) != 0x03) return Cleanup::standby_power_mismatch;
    if (!read_word(0x05, value)) return Cleanup::standby_mute_read;
    if ((value[1] & 0x10) == 0) return Cleanup::standby_mute_mismatch;
    if (!read_word(0x01, value)) return Cleanup::standby_status_read;
    if ((value[0] & 0x01) != 0) return Cleanup::standby_switching;
    if (status) *status = (static_cast<uint16_t>(value[0]) << 8) | value[1];
    return Cleanup::none;
  }

  int write_aw88298(int reg, int len, void* data, int size, bool standby_request = false) {
    if (len != 1 || size != 2 || reg < 0 || reg > 0xff)
      return record(ESP_CODEC_DEV_INVALID_ARG);
    if (faulted() && !cleaning_up_ && !standby_request) return ESP_CODEC_DEV_WRONG_STATE;

    // esp_codec_dev 1.6.2 sends the 16-bit word high byte first.
    const auto* bytes = static_cast<const uint8_t*>(data);
    std::array<uint8_t, 2> staged{bytes[0], bytes[1]}, mask{};
    uint8_t verified_bit = 0;
    switch (reg) {
      case 0x00:  // Software reset invalidates earlier register readbacks.
        verified_ = 0;
        break;
      case 0x04:  // SYSCTRL: I2S disabled, amplifier and device powered down.
        mask[1] = 0x43;
        staged[1] = (staged[1] & ~mask[1]) | 0x03;
        verified_bit = kPowerVerified;
        break;
      case 0x05:  // SYSCTRL2: force HMUTE even when SDK requests unmute.
        mask[1] = 0x10;
        staged[1] |= mask[1];
        verified_bit = kMuteVerified;
        break;
      case 0x0c:  // HAGCCFG4: high byte encodes attenuation in 0.5 dB steps.
        if (staged[0] > kMaxAttenuation) return record(ESP_CODEC_DEV_INVALID_ARG);
        if (staged[0] < kMinAttenuation) staged[0] = kMinAttenuation;
        mask[0] = 0xff;
        verified_bit = kAttenuationVerified;
        break;
    }
    if (!verified_bit) return record(base_->write_reg(base_, reg, len, data, size));
    verified_ &= ~verified_bit;
    auto rc = record(base_->write_reg(base_, reg, len, staged.data(), size));
    if (rc != ESP_CODEC_DEV_OK) return rc;

    std::array<uint8_t, 2> observed{};
    rc = record(base_->read_reg(base_, reg, len, observed.data(), size));
    if (rc != ESP_CODEC_DEV_OK) return rc;
    if ((observed[0] & mask[0]) != (staged[0] & mask[0]) ||
        (observed[1] & mask[1]) != (staged[1] & mask[1]))
      return record(ESP_CODEC_DEV_DRV_ERR);
    verified_ |= verified_bit;
    return ESP_CODEC_DEV_OK;
  }

  static K151CodecControl& self(const audio_codec_ctrl_if_t* h) {
    return *const_cast<K151CodecControl*>(static_cast<const K151CodecControl*>(h));
  }
  int record(int rc) {
    if (rc != ESP_CODEC_DEV_OK) {
      failed_ = true;
      if (cleaning_up_) cleanup_failed_ = true;
    }
    return rc;
  }
  static bool opened(const audio_codec_ctrl_if_t* h) {
    if (!h) return false;
    auto& p = self(h);
    if (p.base_ && p.base_->is_open(p.base_)) return true;
    p.record(ESP_CODEC_DEV_WRONG_STATE); return false;
  }
  static int read(const audio_codec_ctrl_if_t* h, int reg, int len, void* data, int size) {
    if (!h) return ESP_CODEC_DEV_INVALID_ARG;
    auto& p = self(h);
    if (!data || len <= 0 || size <= 0) return p.record(ESP_CODEC_DEV_INVALID_ARG);
    if (!opened(h)) return ESP_CODEC_DEV_WRONG_STATE;
    return p.record(p.base_->read_reg(p.base_, reg, len, data, size));
  }
  static int write(const audio_codec_ctrl_if_t* h, int reg, int len, void* data, int size) {
    if (!h) return ESP_CODEC_DEV_INVALID_ARG;
    auto& p = self(h);
    if (!data || len <= 0 || size <= 0) return p.record(ESP_CODEC_DEV_INVALID_ARG);
    if (!opened(h)) return ESP_CODEC_DEV_WRONG_STATE;
    if (p.profile_ == Profile::aw88298_muted_startup)
      return p.write_aw88298(reg, len, data, size);
    return p.record(p.base_->write_reg(p.base_, reg, len, data, size));
  }
  static int info(const audio_codec_ctrl_if_t* h, audio_codec_ctrl_info_t* out) {
    if (!h) return ESP_CODEC_DEV_INVALID_ARG;
    auto& p = self(h);
    if (!out) return p.record(ESP_CODEC_DEV_INVALID_ARG);
    if (!opened(h)) return ESP_CODEC_DEV_WRONG_STATE;
    return p.record(p.base_->get_info(p.base_, out));
  }
  const Profile profile_;
  const audio_codec_ctrl_if_t* base_ = nullptr;
  uint8_t verified_ = 0;
  std::atomic_bool failed_{false};
  bool attempted_ = false;
  bool cleaning_up_ = false;
  bool cleanup_failed_ = false;
};
}
