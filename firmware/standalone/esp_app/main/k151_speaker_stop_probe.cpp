// SPDX-License-Identifier: MIT
#include "k151_audio_hold_hooks.hpp"
#include "k151_board_bus.hpp"
#include "k151_display_stop.hpp"
#include "k151_lcd_panel.hpp"
#include "k151_probe_tone.hpp"
#include "k151_speaker_stop_probe.hpp"
#include "k151_speaker_stop_timing.hpp"
#include <cstdio>
#include <esp_timer.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>

namespace stackchan::standalone {
namespace {
constexpr auto tone = k151_probe_tone<6000>();
constexpr int kRepetitions = 10; // At most 2.5 seconds at 24 kHz.
struct Report {
  const char* result;
  std::optional<uint32_t> sampled_us{};
  unsigned pcm_blocks = 0;
  bool dma_complete = false;
  bool standby_confirmed = false;
};
}

class K151SpeakerStopProbe final {
 public:
  Report run(const std::atomic_bool& owner, K151AudioBoardEvidence evidence, K151SpeakerStopCue& cue) {
    auto result = exercise(owner, evidence, cue);
    const bool codec_released = codec_.shutdown();
    if (codec_.cleanup_unverified() || !release_panel() ||
        (result.standby_confirmed && !codec_released)) {
      result.result = "cleanup_failed";
      result.sampled_us.reset();
    }
    return result;
  }

 private:
  Report exercise(const std::atomic_bool& owner, K151AudioBoardEvidence evidence,
                  K151SpeakerStopCue& cue) {
    if (!owner.load() || !evidence.verified() || lv_is_initialized() ||
        !k151::open_board_bus(bus_)) return {"preparation_failed"};
    lv_init();
    lvgl_owned_ = true;
    if (!panel_.start(bus_, true) || !owner.load()) return {"preparation_failed"};
    auto* label = lv_label_create(lv_display_get_screen_active(panel_.display()));
    if (!label) return {"preparation_failed"};
    lv_label_set_text(label, "Wait for PC, then tap screen");
    lv_obj_center(label);
    if (!panel_.present_now() || !owner.load()) return {"preparation_failed"};

    const auto armed = K151DisplayStop::arm(bus_, panel_);
    stop_owned_ = armed != K151DisplayStop::ArmResult::unavailable;
    if (armed != K151DisplayStop::ArmResult::armed) return {"preparation_failed"};
    const auto settled_from = esp_timer_get_time();
    for (;;) {
      const auto now = esp_timer_get_time();
      if (!owner.load()) return {"host_stopped"};
      if (stop_.load()) return {"screen_stop_before_playing"};
      if (settled_from < 0 || now < settled_from) return {"clock_fault"};
      if (now - settled_from >= 150'000) break;
      vTaskDelay(1);
    }

    AudioGuard audio{k151_audio_hooks(codec_, owner, stop_, owner, evidence, bus_)};
    if (!audio.initialize(owner.load() && !stop_.load(), evidence.verified()))
      return {"preparation_failed"};
    std::puts("{\"mic_trial\":\"SPEAKER_STOP_ARMED\",\"operating_admission\":false}");
    (void)std::fflush(stdout);
    if (!owner.load()) return {"host_stopped"};
    if (stop_.load()) return {"screen_stop_before_playing"};
    if (!audio.playback_begin()) return {"amplifier_start_failed"};
    return play(audio, owner, cue);
  }

  Report play(AudioGuard& audio, const std::atomic_bool& owner, K151SpeakerStopCue& cue) {
    int64_t previous = esp_timer_get_time();
    const auto began = previous;
    int64_t first_write = -1;
    bool transfer_fault = began < 0;
    unsigned blocks = 0;
    const auto sample_time = [&]() -> std::optional<uint64_t> {
      const auto now = esp_timer_get_time();
      if (now < 0 || now < previous) {
        transfer_fault = true;
        return std::nullopt;
      }
      previous = now;
      return static_cast<uint64_t>(now / 1000);
    };
    const auto write = [&](std::span<const int16_t> chunk) {
      if (!codec_.play_mono_24k(chunk)) {
        transfer_fault = true;
        return false;
      }
      ++blocks;
      if (first_write < 0) {
        if (!sample_time()) return false;
        first_write = previous;
        cue.pending.store(true);
      }
      return true;
    };
    bool queued = !transfer_fault;
    for (int i = 0; i < kRepetitions && queued; ++i)
      queued = stream_pcm_chunks_guarded(
          tone, static_cast<uint64_t>(began / 1000), stop_, owner, write, sample_time).has_value();

    cue.pending.store(false);
    if (queued && codec_.wait_for_tx_tail(owner, owner, stop_)) {
      const bool quiet = audio.playback_end();
      return {quiet ? "completed_no_stop" : "cleanup_failed", {}, blocks, true, quiet};
    }
    const auto returned = esp_timer_get_time();
    const auto sampled = K151DisplayStop::observed_at_us();
    const bool window = cue.sent.load() && !queued && !transfer_fault && owner.load() && stop_.load() &&
                        returned >= previous;
    audio.stop();
    // AudioGuard returns stopped only after amplifier standby and physical
    // channel idle both pass. A write fault invalidates that witness.
    if (audio.state() != AudioState::stopped) return {"cleanup_failed", {}, blocks};
    if (window && owner.load()) {
      const auto elapsed = sampled_stop_to_standby_us(
          first_write, sampled, returned, esp_timer_get_time());
      if (elapsed) return {"screen_stop_and_standby_observed", elapsed, blocks, false, true};
    }
    const char* result = "transfer_failed";
    if (!transfer_fault) {
      if (!owner.load()) result = "host_stopped";
      else if (stop_.load()) {
        if (blocks == 0) result = "screen_stop_before_playing";
        else result = queued ? "screen_stop_after_queue" : "screen_stop_timing_unverified";
      }
    }
    return {result, {}, blocks, false, true};
  }

  bool release_panel() {
    if (stop_owned_ && !K151DisplayStop::disarm()) return false;
    if (!panel_.shutdown()) return false;
    if (lvgl_owned_) lv_deinit();
    return !bus_ || i2c_del_master_bus(bus_) == ESP_OK;
  }

  const std::atomic_bool& stop_ = K151DisplayStop::flag();
  K151CodecPort codec_;
  K151LcdPanel panel_{stop_};
  i2c_master_bus_handle_t bus_ = nullptr;
  bool stop_owned_ = false;
  bool lvgl_owned_ = false;
};

void report_k151_speaker_stop_probe(const std::atomic_bool& owner, K151AudioBoardEvidence evidence,
                                   K151SpeakerStopCue& cue) {
  // Stay alive on ambiguous release. The supervised one-shot ends in HOLD.
  static K151SpeakerStopProbe probe;
  const auto report = probe.run(owner, evidence, cue);
  char delta[12] = "null";
  if (report.sampled_us)
    std::snprintf(delta, sizeof(delta), "%lu", static_cast<unsigned long>(*report.sampled_us));
  std::printf("{\"speaker_probe\":\"K151_SPEAKER_STOP_V2\",\"result\":\"%s\","
              "\"pcm_blocks\":%u,\"dma_complete\":%s,\"standby_confirmed\":%s,"
              "\"sample_to_standby_us\":%s,\"operating_admission\":false}\n",
              report.result, report.pcm_blocks, report.dma_complete ? "true" : "false",
              report.standby_confirmed ? "true" : "false", delta);
}
} // namespace stackchan::standalone
