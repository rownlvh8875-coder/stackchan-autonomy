// SPDX-License-Identifier: MIT
#include "k151_audio_hold_hooks.hpp"
#include "k151_board_bus.hpp"
#include "k151_display_stop.hpp"
#include "k151_lcd_panel.hpp"
#include "k151_probe_tone.hpp"
#include "k151_speaker_stop_probe.hpp"
#include "k151_speaker_stop_timing.hpp"
#ifdef STACKCHAN_K151_AEC_REFERENCE_PROBE
#include "k151_aec_dma.hpp"
#include "k151_aec_timeline.hpp"
#endif
#include <cstdio>
#include <esp_timer.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>

namespace stackchan::standalone {
namespace {
constexpr auto tone = k151_probe_tone<6000>();
constexpr int kRepetitions = 10; // At most 2.5 seconds at 24 kHz.
#ifdef STACKCHAN_K151_AEC_REFERENCE_PROBE
using Aec = K151AecStopProbe;
constexpr unsigned kAecToneBlocks = tone.size() * kRepetitions / Aec::kFramesPerBlock;
constexpr uint32_t kBaselineFrames = 3 * Aec::kFramesPerBlock;
struct AecStopResult {
  K151AecTimeline::Bracket bracket;
  Aec::Cutoff cutoff;
  int64_t sampled_us;
};

class AecObservation final {
 public:
  bool pump(int64_t stop_sampled_us = -1, uint32_t until_frame = Aec::kMaxFrames) {
    ScopedPcmWipe wipe{block_};
    for (unsigned i = 0; i < 16 && frames() < until_frame; ++i) {
      uint32_t first{};
      int64_t eof{};
      if (!take_k151_aec_block(block_, first, eof)) break;
      if (!timeline_.accept(first, eof)) return false;
      if (stop_sampled_us >= 0 && !bracket_) {
        bracket_ = timeline_.stop_bracket(stop_sampled_us);
        if (!bracket_ && eof > stop_sampled_us) return false;
        if (bracket_ && !analyzer_.mark_stop(bracket_->first_frame)) return false;
      }
      if (!analyzer_.observe(first, block_)) return false;
    }
    return !k151_aec_dma_faulted();
  }

  uint32_t frames() const { return timeline_.next_frame(); }
  bool begin_tone() {
    return analyzer_.begin_tone(kBaselineFrames + kAecToneBlocks * Aec::kFramesPerBlock);
  }
  std::optional<AecStopResult> result(int64_t sampled_us) const {
    if (!bracket_ || frames() < bracket_->end_frame + 5 * Aec::kFramesPerBlock)
      return std::nullopt;
    auto cutoff = analyzer_.cutoff();
    if (!cutoff) return std::nullopt;
    return AecStopResult{*bracket_, *cutoff, sampled_us};
  }

 private:
  K151AecTimeline timeline_;
  Aec analyzer_;
  std::optional<K151AecTimeline::Bracket> bracket_;
  std::array<int16_t, Aec::kFramesPerBlock * Aec::kSlots> block_{};
};
#endif
struct StopDiagnostic {
  bool screen_stop_sampled = false;
  bool pcm_write_rejected = false;
  K151SpeakerCleanupStage cleanup_stage = K151SpeakerCleanupStage::none;
  bool reset_latch_verified = false;
  bool tx_idle_observed = false;
  std::optional<uint32_t> reset_idle_us{};
};
struct Report {
  const char* result;
  std::optional<uint32_t> sampled_us{};
  unsigned pcm_blocks = 0;
  bool dma_complete = false;
  bool standby_confirmed = false;
  StopDiagnostic stop{};
#ifdef STACKCHAN_K151_AEC_REFERENCE_PROBE
  std::optional<AecStopResult> aec{};
  const char* failure_stage = nullptr;
#endif
};

Report preparation_failure([[maybe_unused]] const char* stage) {
  Report report{"preparation_failed"};
#ifdef STACKCHAN_K151_AEC_REFERENCE_PROBE
  report.failure_stage = stage;
#endif
  return report;
}
}

class K151SpeakerStopProbe final {
 public:
  Report run(const std::atomic_bool& owner, K151AudioBoardEvidence evidence, K151SpeakerStopCue& cue) {
    auto result = exercise(owner, evidence, cue);
    // Read before disarm, which latches STOP itself. Default shutdown also
    // holds reset, but only the earlier fallback in speaker_off is evidence here.
    result.stop.screen_stop_sampled = stop_.load() && K151DisplayStop::observed_at_us() >= 0;
    result.stop.reset_latch_verified = codec_.speaker_stop_reset_latch_verified();
    result.stop.tx_idle_observed |= codec_.speaker_stop_tx_idle();
    const bool codec_released = codec_.shutdown();
    result.stop.cleanup_stage = codec_.speaker_cleanup_stage();
    if (codec_.cleanup_unverified() || !release_panel() ||
        (result.standby_confirmed && !codec_released)) {
      result.result = "cleanup_failed";
      result.sampled_us.reset();
#ifdef STACKCHAN_K151_AEC_REFERENCE_PROBE
      result.standby_confirmed = false;
      result.aec.reset();
#endif
    }
    return result;
  }

 private:
  Report exercise(const std::atomic_bool& owner, K151AudioBoardEvidence evidence,
                  K151SpeakerStopCue& cue) {
    if (!owner.load() || !evidence.verified() || lv_is_initialized())
      return preparation_failure("board_admission");
    if (!k151::open_board_bus(bus_)) return preparation_failure("board_bus");
    lv_init();
    lvgl_owned_ = true;
    if (!panel_.start(bus_, true) || !owner.load()) return preparation_failure("panel_start");
    auto* label = lv_label_create(lv_display_get_screen_active(panel_.display()));
    if (!label) return preparation_failure("panel_label");
    lv_label_set_text(label, "Wait for PC, then tap screen");
    lv_obj_center(label);
    if (!panel_.present_now() || !owner.load()) return preparation_failure("panel_present");

    const auto armed = K151DisplayStop::arm(bus_, panel_);
    stop_owned_ = armed != K151DisplayStop::ArmResult::unavailable;
    if (armed != K151DisplayStop::ArmResult::armed) return preparation_failure("stop_input");
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
    if (!audio.initialize(owner.load() && !stop_.load(), evidence.verified())) {
#ifdef STACKCHAN_K151_AEC_REFERENCE_PROBE
      return preparation_failure(codec_.aec_setup_stage());
#else
      return preparation_failure("audio_admission");
#endif
    }
    std::puts("{\"mic_trial\":\"SPEAKER_STOP_ARMED\",\"operating_admission\":false}");
    (void)std::fflush(stdout);
    if (!owner.load()) return {"host_stopped"};
    if (stop_.load()) return {"screen_stop_before_playing"};
#ifdef STACKCHAN_K151_AEC_REFERENCE_PROBE
    return play_aec(audio, owner, cue);
#else
    if (!audio.playback_begin()) return {"amplifier_start_failed"};
    return play(audio, owner, cue);
#endif
  }

#ifdef STACKCHAN_K151_AEC_REFERENCE_PROBE
  Report play_aec(AudioGuard& audio, const std::atomic_bool& owner, K151SpeakerStopCue& cue) {
    AecObservation observation;
    if (!codec_.start_aec_reference())
      return {.result = "reference_setup_failed", .failure_stage = codec_.aec_setup_stage()};
    const auto start = esp_timer_get_time();
    int64_t previous = start;
    const auto elapsed_ok = [&](int64_t from, int64_t limit) {
      const auto now = esp_timer_get_time();
      if (from < 0 || now < previous || now < from || now - from >= limit) return false;
      previous = now;
      return true;
    };
    while (observation.frames() < kBaselineFrames) {
      if (!owner.load() || stop_.load()) return {"stopped_before_playback"};
      if (!elapsed_ok(start, 150'000) || !observation.pump(-1, kBaselineFrames))
        return {"baseline_unverified"};
      if (observation.frames() < kBaselineFrames) vTaskDelay(1);
    }
    if (!observation.begin_tone() || !owner.load() || stop_.load() || !audio.playback_begin())
      return {"amplifier_start_failed"};
    const auto began = esp_timer_get_time();
    unsigned blocks = 0;
    bool fault = false;
    while (blocks < kAecToneBlocks && owner.load() && !stop_.load()) {
      const auto offset = blocks == 0 ? 0 :
          blocks + 1 == kAecToneBlocks ? tone.size() - Aec::kFramesPerBlock : Aec::kFramesPerBlock;
      if (!elapsed_ok(began, 2'750'000) ||
          !codec_.play_mono_24k(std::span(tone).subspan(offset, Aec::kFramesPerBlock))) {
        fault = true;
        break;
      }
      ++blocks;
      if (blocks == 1) cue.pending.store(true);
      if (!owner.load() || stop_.load()) break;
      if (!observation.pump()) {
        fault = true;
        break;
      }
    }
    cue.pending.store(false);
    if (!fault && owner.load() && !stop_.load() && blocks == kAecToneBlocks &&
        codec_.wait_for_tx_tail(owner, owner, stop_)) {
      const bool quiet = audio.playback_end();
      return {quiet ? "ended_without_screen_stop" : "cleanup_failed", {}, blocks, true, quiet};
    }

    // Disable output before any post-STOP observation or wait.
    audio.stop();
    const bool quiet = audio.state() == AudioState::stopped && codec_.speaker_stop_tx_idle();
    if (!quiet) return {"cleanup_failed", {}, blocks};
    Report report{"reference_unverified", {}, blocks, false, true};
    const auto sampled = K151DisplayStop::observed_at_us();
    if (!owner.load() || !stop_.load() || sampled < began || !cue.sent.load() ||
        blocks == 0 || blocks == kAecToneBlocks || fault)
      return report;
    const auto quiet_at = esp_timer_get_time();
    while (owner.load() && elapsed_ok(quiet_at, 120'000)) {
      if (!observation.pump(sampled)) break;
      if (auto captured = observation.result(sampled); captured && owner.load()) {
        report.result = "reference_cutoff_bracketed";
        report.aec = captured;
        break;
      }
      vTaskDelay(1);
    }
    return report;
  }
#else
  Report play(AudioGuard& audio, const std::atomic_bool& owner, K151SpeakerStopCue& cue) {
    int64_t previous = esp_timer_get_time();
    const auto began = previous;
    int64_t first_write = -1;
    bool transfer_fault = began < 0;
    bool write_rejected = false;
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
        write_rejected = true;
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
    if (audio.state() != AudioState::stopped) {
      Report failure{"cleanup_failed", {}, blocks};
      failure.stop.pcm_write_rejected = write_rejected;
      if (window && owner.load() && codec_.speaker_stop_reset_latch_verified() &&
          codec_.speaker_stop_tx_idle()) {
        failure.stop.tx_idle_observed = true;
        failure.stop.reset_idle_us = sampled_stop_elapsed_us(
            first_write, sampled, returned, esp_timer_get_time());
      }
      return failure;
    }
    if (window && owner.load()) {
      const auto elapsed = sampled_stop_elapsed_us(
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
    Report report{result, {}, blocks, false, true};
    report.stop.pcm_write_rejected = write_rejected;
    return report;
  }
#endif

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
#ifdef STACKCHAN_K151_AEC_REFERENCE_PROBE
  char failure[48] = "null";
  if (report.failure_stage)
    std::snprintf(failure, sizeof(failure), "\"%s\"", report.failure_stage);
  char timing[224] = "null";
  if (const auto& aec = report.aec) {
    std::snprintf(timing, sizeof(timing),
                "{\"gpio_sample_us\":%lld,\"rx_eof_us\":[%lld,%lld],"
                "\"stop_frames\":[%u,%u],\"cutoff_frames\":[%u,%u]}",
                static_cast<long long>(aec->sampled_us),
                static_cast<long long>(aec->bracket.before_us),
                static_cast<long long>(aec->bracket.after_us),
                unsigned(aec->bracket.first_frame), unsigned(aec->bracket.end_frame),
                unsigned(aec->cutoff.first_possible_frame), unsigned(aec->cutoff.quiet_by_frame));
  }
  std::printf("{\"aec_stop_trial\":\"K151_AEC_REFERENCE_STOP_V1\",\"result\":\"%s\","
              "\"sample_rate_hz\":24000,\"pcm_blocks\":%u,\"standby_confirmed\":%s,"
              "\"operating_admission\":false,\"failure_stage\":%s,\"reference_timing\":%s}\n",
              report.result, report.pcm_blocks, report.standby_confirmed ? "true" : "false",
              failure, timing);
#else
  char delta[12] = "null";
  char reset_delta[12] = "null";
  if (report.sampled_us)
    std::snprintf(delta, sizeof(delta), "%lu", static_cast<unsigned long>(*report.sampled_us));
  if (report.stop.reset_idle_us)
    std::snprintf(reset_delta, sizeof(reset_delta), "%lu",
                  static_cast<unsigned long>(*report.stop.reset_idle_us));
  const auto flag = [](bool value) { return value ? "true" : "false"; };
  std::printf("{\"speaker_probe\":\"K151_SPEAKER_STOP_V3\",\"result\":\"%s\","
              "\"pcm_blocks\":%u,\"dma_complete\":%s,\"standby_confirmed\":%s,"
              "\"sample_to_standby_us\":%s,\"stop_diagnostic\":{\"screen_stop_sampled\":%s,"
              "\"pcm_write_rejected\":%s,\"cleanup_stage\":%u,\"reset_latch_verified\":%s,"
              "\"tx_idle_observed\":%s,\"sample_to_reset_idle_us\":%s},"
              "\"operating_admission\":false}\n",
              report.result, report.pcm_blocks, flag(report.dma_complete), flag(report.standby_confirmed),
              delta, flag(report.stop.screen_stop_sampled), flag(report.stop.pcm_write_rejected),
              unsigned(report.stop.cleanup_stage), flag(report.stop.reset_latch_verified),
              flag(report.stop.tx_idle_observed), reset_delta);
#endif
}
} // namespace stackchan::standalone
