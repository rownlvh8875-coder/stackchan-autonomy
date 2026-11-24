// SPDX-License-Identifier: MIT
#include "k151_audio_hold_hooks.hpp"
#include "k151_board_bus.hpp"
#include "k151_display_stop.hpp"
#include "k151_lcd_panel.hpp"
#include "k151_probe_tone.hpp"
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
};
}

class K151SpeakerStopProbe final {
 public:
  Report run(const std::atomic_bool& owner, K151AudioBoardEvidence evidence) {
    const auto result = exercise(owner, evidence);
    const bool codec_released = codec_.shutdown();
    if (codec_.cleanup_unverified() || !release_panel() || (result.sampled_us && !codec_released))
      return {"cleanup_failed"};
    return result;
  }

 private:
  Report exercise(const std::atomic_bool& owner, K151AudioBoardEvidence evidence) {
    if (!owner.load() || !evidence.verified() || lv_is_initialized() ||
        !k151::open_board_bus(bus_)) return {"preparation_failed"};
    lv_init();
    lvgl_owned_ = true;
    if (!panel_.start(bus_, true) || !owner.load()) return {"preparation_failed"};
    auto* label = lv_label_create(lv_display_get_screen_active(panel_.display()));
    if (!label) return {"preparation_failed"};
    lv_label_set_text(label, "Tap screen during tone");
    lv_obj_center(label);
    if (!panel_.present_now() || !owner.load()) return {"preparation_failed"};

    const auto armed = K151DisplayStop::arm(bus_, panel_);
    stop_owned_ = armed != K151DisplayStop::ArmResult::unavailable;
    if (armed != K151DisplayStop::ArmResult::armed) return {"preparation_failed"};
    const auto settled_from = esp_timer_get_time();
    for (;;) {
      const auto now = esp_timer_get_time();
      if (!owner.load() || stop_.load() || settled_from < 0 || now < settled_from)
        return {"no_playing_stop"};
      if (now - settled_from >= 150'000) break;
      vTaskDelay(1);
    }

    AudioGuard audio{k151_audio_hooks(codec_, owner, stop_, owner, evidence, bus_)};
    if (!audio.initialize(owner.load() && !stop_.load(), evidence.verified()))
      return {"preparation_failed"};
    std::puts("{\"mic_trial\":\"SPEAKER_STOP_ARMED\",\"operating_admission\":false}");
    (void)std::fflush(stdout);
    if (!owner.load() || stop_.load()) return {"no_playing_stop"};
    if (!audio.playback_begin()) return {"amplifier_start_failed"};
    return play(audio, owner);
  }

  Report play(AudioGuard& audio, const std::atomic_bool& owner) {
    int64_t previous = esp_timer_get_time();
    const auto began = previous;
    int64_t first_write = -1;
    bool transfer_fault = began < 0;
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
      if (first_write < 0) {
        if (!sample_time()) return false;
        first_write = previous;
      }
      return true;
    };
    bool queued = !transfer_fault;
    for (int i = 0; i < kRepetitions && queued; ++i)
      queued = stream_pcm_chunks_guarded(
          tone, static_cast<uint64_t>(began / 1000), stop_, owner, write, sample_time).has_value();

    if (queued && codec_.wait_for_tx_tail(owner, owner, stop_)) {
      return {audio.playback_end() ? "no_playing_stop" : "cleanup_failed"};
    }
    const auto returned = esp_timer_get_time();
    const auto sampled = K151DisplayStop::observed_at_us();
    const bool window = !queued && !transfer_fault && owner.load() && stop_.load() &&
                        returned >= previous;
    audio.stop();
    // AudioGuard returns stopped only after amplifier standby and physical
    // channel idle both pass. A write fault invalidates that witness.
    if (audio.state() != AudioState::stopped) return {"cleanup_failed"};
    if (window && owner.load()) {
      const auto elapsed = sampled_stop_to_standby_us(
          first_write, sampled, returned, esp_timer_get_time());
      if (elapsed) return {"screen_stop_and_standby_observed", elapsed};
    }
    return {transfer_fault || (!stop_.load() && owner.load()) ? "transfer_failed"
                                                            : "no_playing_stop"};
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

void report_k151_speaker_stop_probe(const std::atomic_bool& owner, K151AudioBoardEvidence evidence) {
  // Stay alive on ambiguous release. The supervised one-shot ends in HOLD.
  static K151SpeakerStopProbe probe;
  const auto report = probe.run(owner, evidence);
  std::printf("{\"speaker_probe\":\"K151_SPEAKER_STOP_V1\",\"result\":\"%s\","
              "\"sample_to_standby_us\":", report.result);
  if (report.sampled_us) std::printf("%lu", static_cast<unsigned long>(*report.sampled_us));
  else std::fputs("null", stdout);
  std::puts(",\"operating_admission\":false}");
}
} // namespace stackchan::standalone
