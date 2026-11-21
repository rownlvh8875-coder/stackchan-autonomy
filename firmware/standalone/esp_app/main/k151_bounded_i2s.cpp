// SPDX-License-Identifier: MIT
#include "k151_bounded_i2s.hpp"
#include "audio_wipe.hpp"
#include <esp_timer.h>

namespace stackchan::standalone {
namespace {
constexpr uint32_t kWaitMs = 20;
constexpr int64_t kPostDeadlineUs = 40000;
int index(esp_codec_dev_type_t type) {
  return type == ESP_CODEC_DEV_TYPE_IN ? 0 : type == ESP_CODEC_DEV_TYPE_OUT ? 1 : -1;
}
}
class K151BoundedI2s::Access {
 public:
  explicit Access(K151BoundedI2s& port) : port_(port), held_(!port.busy_.test_and_set()) {
    if (!held_) port_.failed_ = true;
  }
  ~Access() { if (held_) port_.busy_.clear(); }
  explicit operator bool() const { return held_; }
 private:
  K151BoundedI2s& port_;
  bool held_;
};
K151BoundedI2s::K151BoundedI2s() : audio_codec_data_if_t{} {
  // The SDK factory already opened base. Its owner alone closes/frees it;
  // never pass this non-owning interface to audio_codec_delete_data_if.
  is_open = opened; enable = enable_data; set_fmt = format_data;
  read = read_data; write = write_data;
}
K151BoundedI2s& K151BoundedI2s::self(const audio_codec_data_if_t* h) {
  return *const_cast<K151BoundedI2s*>(static_cast<const K151BoundedI2s*>(h));
}
int K151BoundedI2s::fail() { failed_ = true; return ESP_CODEC_DEV_DRV_ERR; }
bool K151BoundedI2s::attach(const audio_codec_data_if_t* base,
                            i2s_chan_handle_t rx, i2s_chan_handle_t tx) {
  if (attempted_) return false;
  attempted_ = true;
  if (!base || !rx || !tx || !base->is_open || !base->enable || !base->set_fmt ||
      !base->is_open(base)) { fail(); return false; }
  base_ = base; rx_ = rx; tx_ = tx;
  return true;
}
void K151BoundedI2s::detach() {
  base_ = nullptr; rx_ = tx_ = nullptr; formats_ = {}; enabled_ = {};
}
bool K151BoundedI2s::opened(const audio_codec_data_if_t* h) {
  const auto& p = self(h);
  return p.base_ && p.base_->is_open(p.base_);
}
bool K151BoundedI2s::ready(esp_codec_dev_type_t type) const {
  const int i = index(type);
  return i >= 0 && !failed_ && base_ && base_->is_open(base_) && formats_[i] &&
         enabled_[i] && !enabled_[1-i];
}
bool K151BoundedI2s::disabled(esp_codec_dev_type_t type) const {
  const int i = index(type);
  return i >= 0 && !enabled_[i]; // Logical data state, not physical mute proof.
}
int K151BoundedI2s::format_data(const audio_codec_data_if_t* h, esp_codec_dev_type_t type,
                               esp_codec_dev_sample_info_t* fs) {
  auto& p = self(h); Access access{p};
  if (!access) return ESP_CODEC_DEV_DRV_ERR;
  const int i = index(type);
  if (i < 0 || !fs || p.failed_ || !opened(h) || p.enabled_[i] || p.enabled_[1-i]) return p.fail();
  p.formats_[i] = false;
  if (fs->bits_per_sample != 16 || fs->sample_rate != 24000 || fs->mclk_multiple != 0 ||
      fs->channel != (i == 0 ? 2 : 1) || fs->channel_mask != (i == 0 ? 3 : 0)) return p.fail();
  // Preserve SDK clock/slot/reconfiguration with the ORIGINAL base pointer.
  const int rc = p.base_->set_fmt(p.base_, type, fs);
  if (rc != ESP_CODEC_DEV_OK || p.failed_) return p.fail();
  p.formats_[i] = true;
  return ESP_CODEC_DEV_OK;
}
int K151BoundedI2s::enable_data(const audio_codec_data_if_t* h, esp_codec_dev_type_t type, bool enable) {
  auto& p = self(h); Access access{p};
  if (!access) return ESP_CODEC_DEV_DRV_ERR;
  const int i = index(type);
  if (i < 0 || !opened(h)) return p.fail();
  if (enable && (p.failed_ || !p.formats_[i] || p.enabled_[1-i])) return p.fail();
  // Disabling remains possible after a transfer fault; do not erase the fault.
  const int rc = p.base_->enable(p.base_, type, enable);
  if (rc != ESP_CODEC_DEV_OK) return p.fail();
  p.enabled_[i] = enable;
  return ESP_CODEC_DEV_OK;
}
int K151BoundedI2s::read_data(const audio_codec_data_if_t* h, uint8_t* data, int bytes) {
  return self(h).transfer(false, data, bytes);
}
int K151BoundedI2s::write_data(const audio_codec_data_if_t* h, uint8_t* data, int bytes) {
  return self(h).transfer(true, data, bytes);
}
int K151BoundedI2s::transfer(bool output, uint8_t* data, int bytes) {
  const int maximum = output ? 480 : 960, alignment = output ? 2 : 4;
  const bool buffer_valid = data && bytes > 0 && bytes <= maximum;
  const auto reject = [&] {
    if (!output && buffer_valid) wipe_audio_bytes({data, static_cast<size_t>(bytes)});
    return fail();
  };
  Access access{*this};
  if (!access || !buffer_valid || bytes % alignment ||
      !ready(output ? ESP_CODEC_DEV_TYPE_OUT : ESP_CODEC_DEV_TYPE_IN)) return reject();
  const int64_t before = esp_timer_get_time();
  if (before < 0) return reject();
  size_t actual = 0;
  const esp_err_t rc = output ? i2s_channel_write(tx_, data, bytes, &actual, kWaitMs)
                              : i2s_channel_read(rx_, data, bytes, &actual, kWaitMs);
  const int64_t after = esp_timer_get_time();
  if (rc != ESP_OK || actual != static_cast<size_t>(bytes) || after < before ||
      after - before > kPostDeadlineUs ||
      !ready(output ? ESP_CODEC_DEV_TYPE_OUT : ESP_CODEC_DEV_TYPE_IN)) return reject();
  return ESP_CODEC_DEV_OK;
}
}
