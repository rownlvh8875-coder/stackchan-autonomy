// SPDX-License-Identifier: MIT
// Build-verified K151 codec transport, explicitly dormant at app startup.
#pragma once
#include <array>
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <span>
#include <driver/i2c_master.h>
#include <driver/i2s_std.h>
#include <driver/i2s_tdm.h>
#include <esp_codec_dev.h>
#include <esp_codec_dev_defaults.h>
#include "k151_bounded_i2s.hpp"
#include "k151_codec_control.hpp"

namespace stackchan::standalone {

// Current physical observations from the caller's exclusive audio owner.
// Stored board readback and synthetic bench flags cannot supply these.
struct K151MicOnlyEvidence {
  bool exact_board_verified = false;
  bool microphone_supply_and_clock_pins_verified = false;
  bool amplifier_isolation_with_input_clocks_verified = false;
  bool exclusive_i2s0_owner_verified = false;
};

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
  // Both atomic flags must outlive this port and latch loss until teardown.
  bool prepare_microphone_only(const std::atomic_bool& owner, const std::atomic_bool& stop,
                               const K151MicOnlyEvidence& evidence);
  bool microphone_on();
  bool microphone_off();
  bool capture_mono_24k(std::span<int16_t> mono);  // <= 10ms PCM; 20ms driver wait + 40ms postcheck.
  bool speaker_on_low_volume();
  bool speaker_off();
  bool play_mono_24k(std::span<const int16_t> mono); // <= 10ms PCM; not wall-clock latency.
  bool drain_output_before_mute(); // False until real DMA+codec drain telemetry.
  bool quiet();      // Both codecs; error latches fault
  bool shutdown();   // One release attempt/handle; retains failed I2S, fault stays.
  bool prepared() const {
    return prepared_ && !faulted() && input_allowed() && in_control_.healthy() &&
           (microphone_only() || out_control_.healthy());
  }
  bool faulted() const {
    return fault_ || data_port_.faulted() || in_control_.faulted() || out_control_.faulted();
  }

 private:
  bool microphone_only() const { return mic_owner_ != nullptr; }
  bool input_allowed() const {
    return !microphone_only() || (mic_owner_->load() && !mic_stop_->load());
  }
  bool fail();
  bool prepare_hardware();
  bool prepare_i2s();
  bool prepare_i2s_tx();
  bool prepare_codecs();
  bool prepare_output_codec();
  bool prepare_input_codec();
  bool close_microphone(); // Used by shutdown without initiating nested cleanup.
  const std::atomic_bool* mic_owner_ = nullptr;
  const std::atomic_bool* mic_stop_ = nullptr;
  i2c_master_bus_handle_t i2c_bus_ = nullptr;
  i2s_chan_handle_t tx_ = nullptr;
  i2s_chan_handle_t rx_ = nullptr;
  const audio_codec_data_if_t* data_if_ = nullptr;
  K151BoundedI2s data_port_;
  const audio_codec_ctrl_if_t* in_ctrl_ = nullptr;
  const audio_codec_ctrl_if_t* out_ctrl_ = nullptr;
  K151CodecControl in_control_, out_control_;
  const audio_codec_if_t* in_codec_ = nullptr;
  const audio_codec_if_t* out_codec_ = nullptr;
  const audio_codec_gpio_if_t* gpio_if_ = nullptr;
  esp_codec_dev_handle_t in_dev_ = nullptr;
  esp_codec_dev_handle_t out_dev_ = nullptr;
  bool attempted_ = false;
  bool prepared_ = false;
  bool fault_ = false;
  bool input_open_ = false;
  bool output_open_ = false;
};

}  // namespace stackchan::standalone
