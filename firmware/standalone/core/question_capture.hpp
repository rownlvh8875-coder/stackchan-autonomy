// SPDX-License-Identifier: MIT
// Deterministic, bounded offline PCM question segmenter (not neural VAD).
// A calibrated acoustic VAD and real microphone driver are still required.
#pragma once

#include "audio_wipe.hpp"

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <new>
#include <span>

namespace stackchan::standalone {

enum class CaptureResult { listening, speech_started, ready, rejected };

class QuestionCapture final {
 public:
  static constexpr size_t kFrame = 480; // 20ms at 24kHz mono PCM16
  static constexpr size_t kMaxSamples = 192000; // 8s, same as voice API
  static constexpr size_t kMaxFrames = kMaxSamples / kFrame;
  static constexpr size_t kStartFrames = 3; // 60ms continuous energy
  static constexpr size_t kEndFrames = 25; // 500ms silence
  static constexpr uint32_t kDefaultMinRms = 300;
  using Buffer = std::unique_ptr<int16_t[], void (*)(int16_t*)>;
  // Return exactly kMaxSamples with their matching deleter, or an empty buffer.
  using Allocator = Buffer (*)() noexcept;

  static Buffer allocate_host_pcm() noexcept {
    return {new (std::nothrow) int16_t[kMaxSamples],
            [](int16_t* pcm) { delete[] pcm; }};
  }

  // Fixed energy threshold is only a synthetic-test policy; site calibration
  // and background-noise immunity are not provided by this class.
  explicit QuestionCapture(uint32_t min_rms = kDefaultMinRms,
                           Allocator allocate = allocate_host_pcm)
      : min_rms_(min_rms), allocate_(allocate) {}
  ~QuestionCapture() { wipe_pcm(used_samples()); }

  bool prepare() {
    if (state_ == CaptureResult::rejected || min_rms_ == 0) return false;
    if (!samples_ && allocate_) samples_ = allocate_();
    return static_cast<bool>(samples_);
  }

  CaptureResult push(std::span<const int16_t> pcm, bool stop,
                     bool speaker_active) {
    // A late STOP/playback signal must invalidate even a completed capture.
    // Never allow a previously ready buffer to be reused after cancellation.
    if (stop || speaker_active) return reject();
    if (state_ == CaptureResult::ready || state_ == CaptureResult::rejected)
      return state_;
    if (pcm.size() != kFrame || min_rms_ == 0) return reject();
    if (++frames_seen_ > kMaxFrames) return reject();
    uint64_t sum_sq = 0;
    for (const int16_t value : pcm) {
      const int64_t sample = value;
      sum_sq += static_cast<uint64_t>(sample * sample);
    }
    const bool voiced = sum_sq / kFrame >=
        static_cast<uint64_t>(min_rms_) * min_rms_;
    if (!started_ && !voiced) {
      wipe_pcm(used_samples());
      used_ = consecutive_voice_ = 0;
      return CaptureResult::listening;
    }
    if (used_ > kMaxSamples - pcm.size() || !prepare()) return reject();
    std::copy(pcm.begin(), pcm.end(), samples_.get() + used_);
    used_ += pcm.size();
    if (!started_) {
      if (++consecutive_voice_ < kStartFrames) return CaptureResult::listening;
      started_ = true;
      state_ = CaptureResult::speech_started;
      return state_;
    }
    if (voiced) {
      consecutive_silence_ = 0;
    } else if (++consecutive_silence_ >= kEndFrames) {
      constexpr size_t tail = kEndFrames * kFrame;
      wipe_pcm(used_samples().last(tail));
      used_ -= tail;
      if (used_ == 0) return reject();
      state_ = CaptureResult::ready;
    }
    return state_;
  }

  std::span<const int16_t> audio() const {
    return state_ == CaptureResult::ready ?
        std::span<const int16_t>(samples_.get(), used_) : std::span<const int16_t>{};
  }
  CaptureResult status() const { return state_; }
  void reset() {
    wipe_pcm(used_samples());
    samples_.reset();
    used_ = frames_seen_ = consecutive_voice_ = consecutive_silence_ = 0;
    started_ = false;
    state_ = CaptureResult::listening;
  }
 private:
  std::span<int16_t> used_samples() { return {samples_.get(), used_}; }
  CaptureResult reject() {
    reset();
    state_ = CaptureResult::rejected;
    return state_;
  }
  uint32_t min_rms_;
  Allocator allocate_;
  Buffer samples_{nullptr, nullptr};
  size_t used_ = 0;
  size_t frames_seen_ = 0;
  size_t consecutive_voice_ = 0;
  size_t consecutive_silence_ = 0;
  bool started_ = false;
  CaptureResult state_ = CaptureResult::listening;
};

}  // namespace stackchan::standalone
