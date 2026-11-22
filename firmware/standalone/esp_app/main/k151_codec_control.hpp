// SPDX-License-Identifier: MIT
#pragma once
#include <atomic>
#include <audio_codec_ctrl_if.h>

namespace stackchan::standalone {
// Non-owning error observer, confined to the codec port's owner task. The SDK
// codec can discard register errors; latch them independently without changing
// its register protocol or preventing best-effort cleanup after a fault.
class K151CodecControl final : private audio_codec_ctrl_if_t {
 public:
  K151CodecControl() : audio_codec_ctrl_if_t{} {
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
 private:
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
    return p.record(p.base_->write_reg(p.base_, reg, len, data, size));
  }
  static int info(const audio_codec_ctrl_if_t* h, audio_codec_ctrl_info_t* out) {
    if (!h) return ESP_CODEC_DEV_INVALID_ARG;
    auto& p = self(h);
    if (!out) return p.record(ESP_CODEC_DEV_INVALID_ARG);
    if (!opened(h)) return ESP_CODEC_DEV_WRONG_STATE;
    return p.record(p.base_->get_info(p.base_, out));
  }
  const audio_codec_ctrl_if_t* base_ = nullptr;
  std::atomic_bool failed_{false};
  bool attempted_ = false;
  bool cleaning_up_ = false;
  bool cleanup_failed_ = false;
};
}
