// SPDX-License-Identifier: MIT
// Deterministic, bounded offline PCM question segmenter (not neural VAD).
// A calibrated acoustic VAD and real microphone driver are still required.
#pragma once

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <span>
#include <vector>

namespace stackchan::standalone {

enum class CaptureResult { listening, speech_started, ready, rejected };

class QuestionCapture final {
 public:
  static constexpr size_t kFrame = 480; // 20ms at 24kHz mono PCM16
  static constexpr size_t kMaxSamples = 192000; // 8s, same as voice API
  static constexpr size_t kMaxFrames = kMaxSamples / kFrame;
  static constexpr size_t kStartFrames = 3; // 60ms continuous energy
  static constexpr size_t kEndFrames = 25; // 500ms silence
  // Fixed energy threshold is only a synthetic-test policy; site calibration
  // and background-noise immunity are not provided by this class.
  explicit QuestionCapture(uint32_t min_rms = 300) : min_rms_(min_rms) {}

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
    if (!started_) {
      if (!voiced) {
        consecutive_voice_ = 0;
        return CaptureResult::listening;
      }
      if (consecutive_voice_ == 0) pending_.clear();
      pending_.insert(pending_.end(), pcm.begin(), pcm.end());
      if (++consecutive_voice_ < kStartFrames) return CaptureResult::listening;
      started_ = true;
      captured_.swap(pending_);
      state_ = CaptureResult::speech_started;
      return state_;
    }
    if (captured_.size() > kMaxSamples - pcm.size()) return reject();
    captured_.insert(captured_.end(), pcm.begin(), pcm.end());
    if (voiced) {
      consecutive_silence_ = 0;
    } else if (++consecutive_silence_ >= kEndFrames) {
      captured_.resize(captured_.size() - kEndFrames * kFrame);
      if (captured_.empty()) return reject();
      state_ = CaptureResult::ready;
    }
    return state_;
  }

  std::span<const int16_t> audio() const {
    return state_ == CaptureResult::ready ?
        std::span<const int16_t>(captured_) : std::span<const int16_t>{};
  }
  CaptureResult status() const { return state_; }
  void reset() {
    std::fill(captured_.begin(), captured_.end(), 0);
    std::fill(pending_.begin(), pending_.end(), 0);
    captured_.clear();
    pending_.clear();
    frames_seen_ = consecutive_voice_ = consecutive_silence_ = 0;
    started_ = false;
    state_ = CaptureResult::listening;
  }
 private:
  CaptureResult reject() {
    reset();
    state_ = CaptureResult::rejected;
    return state_;
  }
  uint32_t min_rms_;
  std::vector<int16_t> captured_;
  std::vector<int16_t> pending_;
  size_t frames_seen_ = 0;
  size_t consecutive_voice_ = 0;
  size_t consecutive_silence_ = 0;
  bool started_ = false;
  CaptureResult state_ = CaptureResult::listening;
};

}  // namespace stackchan::standalone
