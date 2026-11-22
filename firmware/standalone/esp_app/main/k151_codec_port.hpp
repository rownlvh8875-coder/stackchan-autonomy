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
#include "k151_mic_only_evidence.hpp"

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

  // Both atomic flags must outlive this port and latch loss until teardown.
  bool prepare(const std::atomic_bool& owner, const std::atomic_bool& stop,
               const K151AudioBoardEvidence& evidence);
  bool prepare_microphone_only(const std::atomic_bool& owner, const std::atomic_bool& stop,
                               const K151MicOnlyEvidence& evidence);
  bool microphone_on();
  bool microphone_off();
  bool capture_idle() const;  // Check physical I2S idle before the next capture.
  bool start_fresh_capture(); // Open duplex RX and discard its first complete PCM block.
  bool capture_mono_24k(std::span<int16_t> mono);  // <= 10ms PCM; 20ms driver wait + 40ms postcheck.
  static bool playback_enabled_by_build();
  bool playback_available() const;
  bool speaker_on_low_volume(const std::atomic_bool& consent);
  bool speaker_off();
  bool play_mono_24k(std::span<const int16_t> mono); // <= 10ms PCM; not wall-clock latency.
  bool wait_for_tx_tail(const std::atomic_bool& owner, const std::atomic_bool& consent,
                        const std::atomic_bool& stop);
  bool drain_output_before_mute(); // Consume fresh DMA tail confirmation.
  bool quiet();      // Both codecs; error latches fault
  bool shutdown();   // One release attempt/handle; retains failed I2S, fault stays.
  bool prepared() const {
    return prepared_ && !faulted() && input_allowed() && in_control_.healthy() &&
           (microphone_only() || out_control_.healthy());
  }
  bool faulted() const {
    return fault_ || data_port_.faulted() || in_control_.faulted() || out_control_.faulted();
  }
  K151MicWakeStage prepare_stage() const { return prepare_stage_; }
  bool cleanup_unverified() const { return cleanup_unverified_; }

 private:
  enum class OutputData { empty, queued, dma_complete };
  bool microphone_only() const { return receive_only_; }
  bool input_allowed() const {
    // A cold port rejects on prepared() without latching a new I/O fault.
    return owner_ ? owner_->load() && !stop_->load() : !attempted_;
  }
  bool fail();
  bool prepare_hardware();
  bool prepare_board();
  bool attach_board_device(uint16_t address);
  bool read_board_register(uint8_t reg, uint8_t& value);
  bool set_amplifier_reset(bool held);
  bool release_board_device();
  bool prepare_i2s();
  bool prepare_i2s_tx();
  bool prepare_codecs();
  bool quiesce_duplex_channels();
  bool prepare_output_codec();
  bool prepare_input_codec();
  bool close_microphone(bool* driver_closed = nullptr); // Does not initiate nested cleanup.
  const std::atomic_bool* owner_ = nullptr;
  const std::atomic_bool* stop_ = nullptr;
  i2c_master_bus_handle_t i2c_bus_ = nullptr;
  i2c_master_dev_handle_t board_device_ = nullptr;
  i2s_chan_handle_t tx_ = nullptr;
  i2s_chan_handle_t rx_ = nullptr;
  const audio_codec_data_if_t* data_if_ = nullptr;
  K151BoundedI2s data_port_;
  const audio_codec_ctrl_if_t* in_ctrl_ = nullptr;
  const audio_codec_ctrl_if_t* out_ctrl_ = nullptr;
  K151CodecControl in_control_;
  K151CodecControl out_control_{K151CodecControl::Profile::aw88298_muted_startup};
  const audio_codec_if_t* in_codec_ = nullptr;
  const audio_codec_if_t* out_codec_ = nullptr;
  const audio_codec_gpio_if_t* gpio_if_ = nullptr;
  esp_codec_dev_handle_t in_dev_ = nullptr;
  esp_codec_dev_handle_t out_dev_ = nullptr;
  bool attempted_ = false;
  bool receive_only_ = false;
  bool reset_controlled_ = false;
  bool prepared_ = false;
  bool fault_ = false;
  bool input_open_ = false;
  bool output_open_ = false;
  bool tx_tail_registered_ = false;
  OutputData output_data_ = OutputData::empty;
  K151MicWakeStage prepare_stage_ = K151MicWakeStage::admission;
  bool cleanup_unverified_ = false;
};

}  // namespace stackchan::standalone
