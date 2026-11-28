// SPDX-License-Identifier: MIT
// Bounded PCM input shared by the native controller and the silent bench.
#pragma once
#include "mic_frame_bridge.hpp"
#include "native_wake_port.hpp"
#include "stream_resampler.hpp"
#include <array>
#include <cstdint>

namespace stackchan::standalone {

// Optional progress for a bounded diagnostic run. This holds no samples.
struct NativeWakePollTrace {
  enum class Step { poll_entry, mic_read, input_processing, model_return };

  Step last_step = Step::poll_entry;
  uint32_t model_calls = 0;
  NativeWakeResult last_model_result = NativeWakeResult::none;
};

class NativeWakeInput final {
 public:
  NativeWakeInput() = default;
  NativeWakeInput(const NativeWakeInput&) = delete;
  NativeWakeInput& operator=(const NativeWakeInput&) = delete;
  ~NativeWakeInput() { clear(); }

  bool configure(NativeWakeFormat format) {
    clear();
    format_ = {};
    if (format.sample_rate_hz != 16000 || format.channels != 1 ||
        format.bits_per_sample != 16 || format.chunk_samples < 160 ||
        format.chunk_samples > chunk_.size()) return false;
    format_ = format;
    return true;
  }

  bool matches(const NativeWakePort& model) const {
    return format_.chunk_samples != 0 && model.ready() && model.format() == format_;
  }

  void clear() {
    resampler_.reset();
    wipe_pcm(chunk_);
    used_ = 0;
  }

  // The caller owns the source and latches STOP/consent locally. This method
  // checks that gate and fixed model format before and after external calls.
  template<class Allowed>
  NativeWakeResult poll(MonoMicReader& mic, NativeWakePort& model, const Allowed& allowed,
                        NativeWakePollTrace* trace = nullptr) {
    using Step = NativeWakePollTrace::Step;
    if (trace) trace->last_step = Step::poll_entry;
    const auto current = [&] { return allowed() && matches(model); };
    if (!current()) return reject();
    std::array<int16_t, 240> input{};
    std::array<int16_t, 160> output{};
    ScopedPcmWipe clear_input{input};
    ScopedPcmWipe clear_output{output};
    if (trace) trace->last_step = Step::mic_read;
    if (!mic.read_10ms(input) || !current()) return reject();
    if (trace) trace->last_step = Step::input_processing;
    if (!resampler_.process(input, output)) return reject();
    wipe_pcm(input);
    for (const auto sample : output) {
      chunk_[used_++] = sample;
      if (used_ != format_.chunk_samples) continue;
      if (!current()) return reject();
      const auto result = model.detect(std::span(chunk_).first(used_));
      wipe_pcm(chunk_);
      used_ = 0;
      if (trace) {
        trace->last_step = Step::model_return;
        ++trace->model_calls;
        trace->last_model_result = result;
      }
      if (!current()) return reject();
      if (result == NativeWakeResult::detected) {
        clear();
        return result;
      }
      if (result != NativeWakeResult::none) return reject();
    }
    return NativeWakeResult::none;
  }

 private:
  NativeWakeResult reject() {
    clear();
    return NativeWakeResult::error;
  }
  StreamingPcm24To16 resampler_;
  NativeWakeFormat format_{};
  std::array<int16_t, 2048> chunk_{};
  size_t used_ = 0;
};
} // namespace stackchan::standalone
