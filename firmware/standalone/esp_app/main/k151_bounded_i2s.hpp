// SPDX-License-Identifier: MIT
// Non-owning PCM adapter; the codec port owns the SDK base and I2S handles.
#pragma once
#include <array>
#include <atomic>
#include <audio_codec_data_if.h>
#include <driver/i2s_common.h>

namespace stackchan::standalone {
// Lifecycle is confined to the same owner task as K151CodecPort. No concurrent
// detach/destruction. A nonblocking callback guard rejects reconfiguration
// during transfer; it does not provide cross-task port lifecycle ownership.
class K151BoundedI2s final : private audio_codec_data_if_t {
 public:
  K151BoundedI2s();
  K151BoundedI2s(const K151BoundedI2s&) = delete;
  K151BoundedI2s& operator=(const K151BoundedI2s&) = delete;
  bool attach(const audio_codec_data_if_t* base, i2s_chan_handle_t rx, i2s_chan_handle_t tx);
  // Attach a reserved, disabled and unpaired RX. The owner must configure the
  // fixed PCM format before exposing the interface to the codec.
  bool attach_receive_only(i2s_chan_handle_t rx);
  void detach(); // Only after codec devices have been deleted.
  const audio_codec_data_if_t* interface() const { return this; }
  bool faulted() const { return failed_.load(); }
  bool ready(esp_codec_dev_type_t direction) const;
  bool disabled(esp_codec_dev_type_t direction) const;
 private:
  class Access;
  static K151BoundedI2s& self(const audio_codec_data_if_t* h);
  static bool opened(const audio_codec_data_if_t* h);
  static int enable_data(const audio_codec_data_if_t* h, esp_codec_dev_type_t type, bool enable);
  static int format_data(const audio_codec_data_if_t* h, esp_codec_dev_type_t type,
                         esp_codec_dev_sample_info_t* fs);
  static int read_data(const audio_codec_data_if_t* h, uint8_t* data, int bytes);
  static int write_data(const audio_codec_data_if_t* h, uint8_t* data, int bytes);
  int transfer(bool output, uint8_t* data, int bytes);
  int fail();
  bool has_channel(int direction) const;
  const audio_codec_data_if_t* base_ = nullptr;
  i2s_chan_handle_t rx_ = nullptr, tx_ = nullptr;
  std::array<bool, 2> formats_{}, enabled_{};
  std::atomic_bool failed_{false};
  std::atomic_flag busy_ = ATOMIC_FLAG_INIT;
  bool attempted_ = false;
};
}
