// SPDX-License-Identifier: MIT
#include "k151_speaker_probe.hpp"
#include "k151_audio_hold_hooks.hpp"
#include "k151_pcm_speaker_sink.hpp"

#include <algorithm>
#include <array>

#ifndef STACKCHAN_K151_SPEAKER_PROBE
#error "The speaker probe must only be built in its dedicated TX-only image"
#endif

namespace stackchan::standalone {
namespace {
using Result = K151SpeakerProbeResult;
constexpr size_t kToneSamples = 6000; // 250 ms at 24 kHz.
constexpr int16_t kPeakPcm = 4096;
constexpr size_t kFadeSamples = kPcmOutputChunkSamples;
constexpr auto tone = [] {
  constexpr std::array<int16_t, 24> wave{
      0, 1060, 2048, 2896, 3547, 3956, kPeakPcm, 3956, 3547, 2896, 2048, 1060,
      0, -1060, -2048, -2896, -3547, -3956, -kPeakPcm, -3956, -3547, -2896, -2048, -1060};
  std::array<int16_t, kToneSamples> pcm{};
  for (size_t i = 0; i < pcm.size(); ++i) {
    const int ramp = static_cast<int>(std::min({i, pcm.size() - i - 1, kFadeSamples}));
    pcm[i] = static_cast<int16_t>(wave[i % wave.size()] * ramp / static_cast<int>(kFadeSamples));
  }
  return pcm;
}();
std::atomic_flag attempted = ATOMIC_FLAG_INIT;
}

K151SpeakerProbeResult run_k151_speaker_probe(const std::atomic_bool& owner,
    const std::atomic_bool& stop, K151AudioBoardEvidence evidence) {
  const auto allowed = [&] { return owner.load() && !stop.load(); };
  if (stop.load()) return Result::stopped;
  if (!owner.load() || !evidence.verified() || attempted.test_and_set()) return Result::denied;

  K151CodecPort codec;
  // The one-shot benchmark uses the local START permission for synthetic
  // playback. This image links no cloud client or microphone codec.
  AudioGuard audio{k151_audio_hooks(codec, owner, stop, owner, evidence)};
  K151PcmSpeakerSink sink{codec, stop, owner, owner};
  const auto finish = [&](Result result) {
    if (audio.state() == AudioState::playback) audio.stop();
    const bool released = codec.shutdown();
    if (codec.cleanup_unverified() || (result == Result::observed && !released))
      return Result::cleanup_failed;
    return allowed() ? result : Result::stopped;
  };
  if (!audio.initialize(allowed(), evidence.verified())) return finish(Result::codec_prepare_failed);
  if (!allowed()) return finish(Result::stopped);
  if (!audio.playback_begin()) return finish(Result::amplifier_start_failed);
  const auto started_us = esp_timer_get_time();
  if (started_us < 0) return finish(Result::clock_fault);
  const auto playback = sink.play_pcm24k(tone, static_cast<uint64_t>(started_us / 1000));
  if (!playback.complete) return finish(Result::transfer_failed);
  if (!audio.playback_end()) return finish(Result::mute_confirmation_failed);
  return finish(Result::observed);
}

} // namespace stackchan::standalone
