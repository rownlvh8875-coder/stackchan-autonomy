// SPDX-License-Identifier: MIT
#include "k151_speaker_probe.hpp"
#include "k151_audio_hold_hooks.hpp"
#include "k151_pcm_speaker_sink.hpp"
#include "k151_probe_tone.hpp"

#ifndef STACKCHAN_K151_SPEAKER_PROBE
#error "The speaker probe must only be built in its dedicated TX-only image"
#endif

namespace stackchan::standalone {
namespace {
using Result = K151SpeakerProbeResult;
using Stage = K151SpeakerStartupStage;
using Progress = K151SpeakerPlaybackProgress;
using Cleanup = K151SpeakerCleanupStage;
constexpr auto tone = k151_probe_tone<6000>(); // 250 ms at 24 kHz.
std::atomic_flag attempted = ATOMIC_FLAG_INIT;
}

K151SpeakerProbeReport run_k151_speaker_probe(const std::atomic_bool& owner,
    const std::atomic_bool& stop, K151AudioBoardEvidence evidence) {
  const auto allowed = [&] { return owner.load() && !stop.load(); };
  if (stop.load()) return {Result::stopped};
  if (!owner.load() || !evidence.verified() || attempted.test_and_set()) return {Result::denied};

  K151CodecPort codec;
  // The one-shot benchmark uses the local START permission for synthetic
  // playback. This image links no cloud client or microphone codec.
  AudioGuard audio{k151_audio_hooks(codec, owner, stop, owner, evidence)};
  K151PcmSpeakerSink sink{codec, stop, owner, owner};
  auto progress = Progress::none;
  const auto finish = [&](Result result, K151SpeakerStartupDiagnostic startup = {})
      -> K151SpeakerProbeReport {
    const auto reset = startup.standby_uvls.has_value() ? codec.speaker_reset_observations()
                                                       : K151SpeakerResetObservations{};
    if (audio.state() == AudioState::playback) audio.stop();
    const bool released = codec.shutdown();
    auto cleanup = codec.speaker_cleanup_stage();
    if (codec.cleanup_unverified() || (result == Result::observed && !released)) {
      if (cleanup == Cleanup::none) cleanup = Cleanup::previous_fault;
      return {Result::cleanup_failed, startup, reset, progress, cleanup};
    }
    if (allowed()) return {result, startup, reset, progress, cleanup};
    if (cleanup == Cleanup::standby_interrupted)
      return {Result::stopped, {}, {}, progress, cleanup};
    return {Result::stopped};
  };
  if (!audio.initialize(allowed(), evidence.verified())) return finish(Result::codec_prepare_failed);
  if (!allowed()) return finish(Result::stopped);
  if (!audio.playback_begin())
    return finish(Result::amplifier_start_failed, codec.speaker_startup());
  const auto started_us = esp_timer_get_time();
  if (started_us < 0) return finish(Result::clock_fault, codec.speaker_startup());
  const auto playback = sink.play_pcm24k(tone, static_cast<uint64_t>(started_us / 1000));
  if (!playback.complete) return finish(Result::transfer_failed, codec.speaker_startup());
  progress = Progress::dma_complete;
  if (!audio.playback_end()) return finish(Result::mute_confirmation_failed, codec.speaker_startup());
  progress = Progress::mute_verified;
  return finish(Result::observed, codec.speaker_startup());
}

const char* speaker_startup_stage_name(Stage stage) {
  switch (stage) {
    case Stage::none: return "none";
    case Stage::audio_guard: return "audio_guard";
    case Stage::admission: return "admission";
    case Stage::codec_open: return "codec_open";
    case Stage::codec_ready: return "codec_ready";
    case Stage::i2s_tx_state: return "i2s_tx_state";
    case Stage::volume: return "volume";
    case Stage::muted_admission: return "muted_admission";
    case Stage::clock_origin: return "clock_origin";
    case Stage::standby_readback: return "standby_readback";
    case Stage::i2s_enable: return "i2s_enable";
    case Stage::clock_enable: return "clock_enable";
    case Stage::wait_clock: return "wait_clock";
    case Stage::mute_readback: return "mute_readback";
    case Stage::pre_amplifier_status: return "pre_amplifier_status";
    case Stage::amplifier_enable: return "amplifier_enable";
    case Stage::wait_switching: return "wait_switching";
    case Stage::attenuation: return "attenuation";
    case Stage::pre_unmute_status: return "pre_unmute_status";
    case Stage::unmute: return "unmute";
    case Stage::post_unmute_status: return "post_unmute_status";
  }
  return nullptr;
}

const char* speaker_clock_wait_exit_name(K151ClockWaitExit reason) {
  using Exit = K151ClockWaitExit;
  switch (reason) {
    case Exit::none: return "none";
    case Exit::admission_lost: return "admission_lost";
    case Exit::timer_regressed: return "timer_regressed";
    case Exit::startup_deadline: return "startup_deadline";
    case Exit::poll_limit: return "poll_limit";
    case Exit::status_read_failed: return "status_read_failed";
    case Exit::protection_active: return "protection_active";
    case Exit::early_switching: return "early_switching";
  }
  return nullptr;
}

const char* speaker_clock_wait_sample_name(K151ClockWaitSample sample) {
  using Sample = K151ClockWaitSample;
  switch (sample) {
    case Sample::none: return "none";
    case Sample::unobserved: return "unobserved";
    case Sample::reference_missing: return "reference_missing";
    case Sample::pll_unlocked: return "pll_unlocked";
    case Sample::internal_unstable: return "internal_unstable";
    case Sample::stable: return "stable";
  }
  return nullptr;
}

} // namespace stackchan::standalone
