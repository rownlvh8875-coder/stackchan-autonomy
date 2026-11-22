// SPDX-License-Identifier: MIT
#include "k151_mic_wake_trial.hpp"
#include "k151_mic_wake_memory.hpp"
#include "k151_mic_reader.hpp"
#include <esp_timer.h>
#include <limits>
#include <utility>

namespace stackchan::standalone {
namespace {
using Result = K151MicWakeTrialResult;
constexpr int64_t kCaptureWindowUs = 5'000'000;
constexpr int64_t kMaxPollGapUs = 100'000;
constexpr unsigned kMaxFrames = 500;  // 10 ms of 24 kHz PCM per frame.

class CountedMicReader final : public MonoMicReader {
 public:
  explicit CountedMicReader(K151CodecPort& codec) : mic_(codec) {}

  bool read_10ms(std::span<int16_t> pcm) override {
    if (!mic_.read_10ms(pcm)) return false;
    bool all_zero = true;
    for (const int16_t sample : pcm) {
      all_zero &= sample == 0;
      counts_.full_scale_samples += sample == std::numeric_limits<int16_t>::min() ||
                                    sample == std::numeric_limits<int16_t>::max();
    }
    ++counts_.frames_read;
    counts_.all_zero_frames += all_zero;
    return true;
  }

  K151MicWakeInputCounts counts() const { return counts_; }

 private:
  K151MicReader mic_;
  K151MicWakeInputCounts counts_;
};

template<class Allowed>
Result listen(NativeWakeInput& input, MonoMicReader& mic, NativeWakePort& model,
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

std::optional<K151MicWakeInputCounts> K151MicWakeTrial::take_input_counts() {
  return std::exchange(input_counts_, std::nullopt);
}

K151MicWakeTrialResult K151MicWakeTrial::run(const std::atomic_bool& owner,
                                           const std::atomic_bool& stop,
                                           const K151MicOnlyEvidence& evidence,
                                           std::unique_ptr<NativeWakePort> model) {
  if (const auto denied = begin(owner, stop, evidence)) return *denied;
  return run_prepared(owner, stop, evidence, std::move(model));
}

K151MicWakeTrialResult K151MicWakeTrial::run_prepared(const std::atomic_bool& owner,
                                                     const std::atomic_bool& stop,
                                                     const K151MicOnlyEvidence& evidence,
                                                     std::unique_ptr<NativeWakePort> model) {
  const auto allowed = [&] { return owner.load() && !stop.load(); };
  if (!allowed()) return Result::stopped;
  if (!model || !model->ready() || !input_.configure(model->format())) return Result::fault;
  if (!allowed()) return Result::stopped;
  if (!model->reset() || !input_.matches(*model)) return Result::fault;
  if (!allowed()) return Result::stopped;
  const bool resident_headroom = k151_mic_wake_internal_heap_available();
  if (!resident_headroom || !allowed()) {
    model.reset();
    return allowed() ? Result::memory_denied : Result::stopped;
  }

  K151CodecPort codec;
  CountedMicReader mic{codec};
  const bool prepared = codec.prepare_microphone_only(owner, stop, evidence);
  auto result = allowed() ? Result::fault : Result::stopped;
  if (prepared && allowed() && input_.matches(*model)) {
    const auto start_us = esp_timer_get_time();
    if (start_us >= 0 && codec.microphone_on()) {
      result = listen(input_, mic, *model, start_us, allowed);
    }
  }
  input_.clear();
  const bool codec_released = codec.shutdown();
  model.reset();
  if (!codec_released || result == Result::fault) return Result::fault;
  if (!allowed() || result == Result::stopped) return Result::stopped;
  if (result == Result::detected || result == Result::not_detected)
    input_counts_ = mic.counts();
  return result;
}

}  // namespace stackchan::standalone
