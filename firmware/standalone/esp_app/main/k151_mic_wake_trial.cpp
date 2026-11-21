// SPDX-License-Identifier: MIT
#include "k151_mic_wake_trial.hpp"
#include "k151_mic_reader.hpp"
#include <esp_timer.h>

namespace stackchan::standalone {
namespace {
using Result = K151MicWakeTrialResult;
constexpr int64_t kCaptureWindowUs = 5'000'000;
constexpr int64_t kMaxPollGapUs = 100'000;
constexpr unsigned kMaxFrames = 500;  // 10 ms of 24 kHz PCM per frame.

template<class Allowed>
Result listen(NativeWakeInput& input, K151MicReader& mic, NativeWakePort& model,
              int64_t start_us, const Allowed& allowed) {
  auto last_poll_us = start_us;
  auto last_clock_us = start_us;
  const auto clock = [&] {
    const auto now = esp_timer_get_time();
    if (now < last_clock_us) return int64_t{-1};
    last_clock_us = now;
    return now;
  };

  for (unsigned frame = 0; frame < kMaxFrames; ++frame) {
    if (!allowed()) return Result::stopped;
    const auto before = clock();
    if (before < 0 || before - last_poll_us > kMaxPollGapUs) return Result::fault;
    if (before - start_us >= kCaptureWindowUs) break;
    last_poll_us = before;
    const auto within_time = [&] {
      const auto now = clock();
      return now >= 0 && now - before <= kMaxPollGapUs &&
             now - start_us <= kCaptureWindowUs;
    };
    const auto result = input.poll(mic, model, [&] { return within_time() && allowed(); });
    if (!within_time()) return Result::fault;
    if (!allowed()) return Result::stopped;
    if (result == NativeWakeResult::error) return Result::fault;
    if (result == NativeWakeResult::detected) return Result::detected;
  }
  return Result::not_detected;
}
}  // namespace

K151MicWakeTrialResult K151MicWakeTrial::run(const std::atomic_bool& owner,
                                           const std::atomic_bool& stop,
                                           const K151MicOnlyEvidence& evidence,
                                           std::unique_ptr<NativeWakePort> model) {
  if (attempted_) return Result::denied;
  attempted_ = true;
  if (stop.load()) return Result::stopped;
  if (!owner.load() || !evidence.verified()) return Result::denied;
  if (!model || !model->ready() || !input_.configure(model->format())) return Result::fault;

  const auto allowed = [&] { return owner.load() && !stop.load(); };
  if (!allowed()) return Result::stopped;
  if (!model->reset() || !input_.matches(*model)) return Result::fault;
  if (!allowed()) return Result::stopped;

  K151CodecPort codec;
  const bool prepared = codec.prepare_microphone_only(owner, stop, evidence);
  auto result = allowed() ? Result::fault : Result::stopped;
  if (prepared && allowed() && input_.matches(*model)) {
    const auto start_us = esp_timer_get_time();
    if (start_us >= 0 && codec.microphone_on()) {
      K151MicReader mic{codec};
      result = listen(input_, mic, *model, start_us, allowed);
    }
  }
  input_.clear();
  const bool codec_released = codec.shutdown();
  model.reset();
  if (!codec_released || result == Result::fault) return Result::fault;
  return allowed() ? result : Result::stopped;
}

}  // namespace stackchan::standalone
