// SPDX-License-Identifier: MIT
#include "question_capture.hpp"
#include <array>
#include <cassert>
#include <iostream>

using namespace stackchan::standalone;

int main() {
  std::array<int16_t, QuestionCapture::kFrame> speech{}, silence{};
  speech.fill(2000);
  {
    QuestionCapture cap;
    for (int i = 0; i < 4; ++i)
      assert(cap.push(silence, false, false) == CaptureResult::listening);
    for (int i = 0; i < 2; ++i)
      assert(cap.push(speech, false, false) == CaptureResult::listening);
    assert(cap.push(speech, false, false) == CaptureResult::speech_started);
    assert(cap.audio().empty()); // No premature API dispatch.
    for (int i = 0; i < 4; ++i)
      assert(cap.push(speech, false, false) == CaptureResult::speech_started);
    for (size_t i = 0; i < QuestionCapture::kEndFrames - 1; ++i)
      assert(cap.push(silence, false, false) == CaptureResult::speech_started);
    assert(cap.push(silence, false, false) == CaptureResult::ready);
    assert(cap.audio().size() == 7 * QuestionCapture::kFrame);
    assert(cap.push(speech, false, false) == CaptureResult::ready);
    cap.reset();
    assert(cap.audio().empty() && cap.status() == CaptureResult::listening);
  }
  {
    QuestionCapture cap;
    assert(cap.push(speech, true, false) == CaptureResult::rejected);
    assert(cap.audio().empty());
    assert(cap.push(speech, false, false) == CaptureResult::rejected);
  }
  {
    QuestionCapture cap;
    assert(cap.push(speech, false, true) == CaptureResult::rejected);
  }
  {
    QuestionCapture cap;
    const std::array<int16_t, 1> malformed{1};
    assert(cap.push(malformed, false, false) == CaptureResult::rejected);
  }
  {
    QuestionCapture cap;
    for (size_t i = 0; i < QuestionCapture::kMaxFrames; ++i)
      assert(cap.push(silence, false, false) == CaptureResult::listening);
    assert(cap.push(silence, false, false) == CaptureResult::rejected);
  }
  {
    QuestionCapture cap(0);
    assert(cap.push(speech, false, false) == CaptureResult::rejected);
  }
  std::cout << "bounded question capture PASS (host-only)\n";
}
