// SPDX-License-Identifier: MIT
// Build-verified K151 codec transport, explicitly dormant at app startup.
#pragma once
#include <array>
#include <cstddef>
#include <cstdint>
#include <span>
#include <driver/i2c_master.h>
#include <driver/i2s_std.h>
#include <driver/i2s_tdm.h>
#include <esp_codec_dev.h>
#include <esp_codec_dev_defaults.h>

namespace stackchan::standalone {

// This class MUST NOT be started by app_main. Amp reset, power rails, exact
// LCD/board identity and physical STOP require a separate hardware review.
// Calls are synchronous; no hard realtime STOP latency is claimed.
class K151CodecPort final {
 public:
  static const char* compiled_link_marker();
  K151CodecPort() = default;
  K151CodecPort(const K151CodecPort&) = delete;
  K151CodecPort& operator=(const K151CodecPort&) = delete;
  ~K151CodecPort();

  bool prepare(bool physical_owner_approval, bool exact_k151_identity,
               bool amp_reset_and_power_verified);
  bool microphone_on();
  bool microphone_off();
  bool capture_mono_24k(std::span<int16_t> mono);  // <= 10ms; channel 0 only
  bool speaker_on_low_volume();
  bool speaker_off();
  bool play_mono_24k(std::span<const int16_t> mono); // <= 10ms
  bool quiet();      // Both codecs; error latches fault
  bool shutdown();   // Release only, never erase/flash/NVS
  bool prepared() const { return prepared_ && !fault_; }
  bool faulted() const { return fault_; }

 private:
  bool fail();
  bool prepare_i2s();
  bool prepare_codecs();
  i2c_master_bus_handle_t i2c_bus_ = nullptr;
  i2s_chan_handle_t tx_ = nullptr;
  i2s_chan_handle_t rx_ = nullptr;
  const audio_codec_data_if_t* data_if_ = nullptr;
  const audio_codec_ctrl_if_t* in_ctrl_ = nullptr;
  const audio_codec_ctrl_if_t* out_ctrl_ = nullptr;
  const audio_codec_if_t* in_codec_ = nullptr;
  const audio_codec_if_t* out_codec_ = nullptr;
  const audio_codec_gpio_if_t* gpio_if_ = nullptr;
  esp_codec_dev_handle_t in_dev_ = nullptr;
  esp_codec_dev_handle_t out_dev_ = nullptr;
  bool attempted_ = false;
  bool prepared_ = false;
  bool fault_ = false;
  bool tx_enabled_ = false;
  bool rx_enabled_ = false;
  bool input_open_ = false;
  bool output_open_ = false;
};

}  // namespace stackchan::standalone
