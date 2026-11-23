// SPDX-License-Identifier: MIT
#pragma once
#include "k151_speaker_startup_stage.hpp"
#include <array>
#include <atomic>
#include <cstdint>
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
  bool aw88298_standby_verified() {
    if (profile_ != Profile::aw88298_muted_startup || !healthy()) return false;
    return standby_registers_verified([&](int reg, std::array<uint8_t, 2>& value) {
      return read(this, reg, 1, value.data(), value.size()) == ESP_CODEC_DEV_OK;
    });
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
  template <typename Allowed, typename Clock, typename Pause>
  [[nodiscard]] K151SpeakerStartupStage start_aw88298_low_volume(Allowed allowed, Clock clock,
                                                                Pause pause) {
    using Stage = K151SpeakerStartupStage;
    constexpr int64_t kStartupLimitUs = 100'000;
    constexpr int64_t kStageSettleUs = 2'000;
    constexpr uint16_t kClockMask = 0x0031; // NOCLKS, CLKS, PLLS
    constexpr uint16_t kClockLocked = 0x0011;
    constexpr uint16_t kSwitching = 0x0100;
    constexpr uint16_t kHardFaults = 0xcc0a; // OVP2, UVL, BSTOC, OVP, OCD, OTH
    constexpr uint8_t kPowerMask = 0x43; // I2SEN, AMPPD, PWDN
    constexpr uint8_t kConfiguring = 0x42; // I2S enabled, amplifier still off
    constexpr uint8_t kOperating = 0x40;
    constexpr uint8_t kHardMute = 0x10;

    if (!allowed() || !muted_startup_verified()) return Stage::muted_admission;
    const int64_t started = clock();
    if (started < 0) return Stage::clock_origin;
    int64_t sampled = started;
    const auto live = [&] {
      if (!allowed() || !healthy()) return false;
      const int64_t observed = clock();
      if (observed < sampled || observed - started >= kStartupLimitUs) return false;
      sampled = observed;
      return true;
    };
    const auto read_live = [&](int reg, std::array<uint8_t, 2>& value) {
      return live() && read(this, reg, 1, value.data(), value.size()) == ESP_CODEC_DEV_OK && live();
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
      return (status & kHardFaults) == 0;
    };
    const auto await_stage = [&](bool operating) {
      const int64_t stage_started = sampled; // Sampled after the stage write/readback.
      const uint16_t expected = kClockLocked | (operating ? kSwitching : 0);
      // The poll count also bounds failure if the injected clock never advances.
      for (int poll = 0; poll < 100; ++poll) {
        uint16_t status{};
        if (!read_status(status) || (!operating && (status & kSwitching))) return false;
        if (sampled - stage_started >= kStageSettleUs &&
            (status & (kClockMask | kSwitching)) == expected) return true;
        if (!live()) return false;
        pause();
      }
      return false;
    };

    std::array<uint8_t, 2> value{};
    if (!standby_registers_verified(read_live)) return Stage::standby_readback;
    if (!transition(0x04, kPowerMask, 0x03, kConfiguring)) return Stage::clock_enable;
    if (!await_stage(false)) return Stage::wait_clock;
    if (!read_live(0x05, value) || !(value[1] & kHardMute)) return Stage::mute_readback;
    if (!transition(0x04, kPowerMask, kConfiguring, kOperating)) return Stage::amplifier_enable;
    if (!await_stage(true)) return Stage::wait_switching;
    if (!read_live(0x0c, value) || value[0] < kMinAttenuation || value[0] > kMaxAttenuation)
      return Stage::attenuation;
    uint16_t status{};
    constexpr auto kStatusMask = kClockMask | kSwitching;
    constexpr auto kReady = kClockLocked | kSwitching;
    if (!read_status(status) || (status & kStatusMask) != kReady) return Stage::pre_unmute_status;
    if (!transition(0x05, kHardMute, kHardMute, 0)) return Stage::unmute;
    if (!read_status(status) || (status & kStatusMask) != kReady) return Stage::post_unmute_status;
    return Stage::none;
  }
 private:
  static constexpr uint8_t kPowerVerified = 1, kMuteVerified = 2, kAttenuationVerified = 4;
  static constexpr uint8_t kMinAttenuation = 0x60, kMaxAttenuation = 0xc0;

  template <typename Read>
  static bool standby_registers_verified(Read read_word) {
    std::array<uint8_t, 2> value{};
    // ID, SYSCTRL, SYSCTRL2 and SYSST. SYSINT is clear-on-read and is not used.
    return read_word(0x00, value) && value[0] == 0x18 && value[1] == 0x52 &&
           read_word(0x04, value) && (value[1] & 0x43) == 0x03 &&
           read_word(0x05, value) && (value[1] & 0x10) != 0 &&
           read_word(0x01, value) && (value[0] & 0x01) == 0;
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
