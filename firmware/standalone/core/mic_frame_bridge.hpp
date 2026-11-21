// SPDX-License-Identifier: MIT
// No-hardware bridge: two bounded 10ms reads -> 20ms question frame.
#pragma once

#include "question_capture.hpp"
#include "audio_wipe.hpp"

#include <array>
#include <atomic>
#include <cstdint>
#include <span>

namespace stackchan::standalone {

class MonoMicReader {
 public:
  virtual ~MonoMicReader() = default;
  virtual bool read_10ms(std::span<int16_t> pcm240) = 0;
};

class MicFrameBridge final {
 public:
  explicit MicFrameBridge(MonoMicReader& mic, const std::atomic_bool& stop,
                          const std::atomic_bool& speaker_busy)
      : mic_(mic), stop_(stop), speaker_(speaker_busy) {}

  CaptureResult capture(QuestionCapture& segmenter) {
    if (stop_.load() || speaker_.load() || faulted_) return reject(segmenter);
    std::array<int16_t, QuestionCapture::kFrame> frame{};
    ScopedPcmWipe clear{frame};
    for (size_t offset = 0; offset < frame.size(); offset += 240) {
      if (stop_.load() || speaker_.load() ||
          !mic_.read_10ms(std::span<int16_t>(frame.data() + offset, 240))) {
        return reject(segmenter);
      }
    }
    // Late STOP must invalidate both the local buffer and completed audio.
    if (stop_.load() || speaker_.load()) {
      return reject(segmenter);
    }
    const auto result = segmenter.push(frame, false, false);
    return result;
  }

  bool faulted() const { return faulted_; }

 private:
  CaptureResult reject(QuestionCapture& segmenter) {
    faulted_ = true; // One-way latch, no implicit restart after failed I/O.
    return segmenter.push({}, true, false);
  }
  MonoMicReader& mic_;
  const std::atomic_bool& stop_;
  const std::atomic_bool& speaker_;
  bool faulted_ = false;
};

} // namespace stackchan::standalone
