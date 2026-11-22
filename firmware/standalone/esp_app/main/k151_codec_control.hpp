// SPDX-License-Identifier: MIT
#pragma once
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
 private:
  static constexpr uint8_t kPowerVerified = 1, kMuteVerified = 2, kAttenuationVerified = 4;

  int write_aw88298(int reg, int len, void* data, int size) {
    if (len != 1 || size != 2 || reg < 0 || reg > 0xff)
      return record(ESP_CODEC_DEV_INVALID_ARG);
    if (faulted() && !cleaning_up_) return ESP_CODEC_DEV_WRONG_STATE;

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
        if (staged[0] > 0xc0) return record(ESP_CODEC_DEV_INVALID_ARG);
        if (staged[0] < 0x60) staged[0] = 0x60;
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
