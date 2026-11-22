// SPDX-License-Identifier: MIT
#include "question_capture.hpp"
#include "k151_question_pcm.hpp"
#include <array>
#include <cassert>
#include <iostream>

using namespace stackchan::standalone;

namespace {
std::array<int16_t, QuestionCapture::kMaxSamples> psram;
enum class Placement { external, exhausted, internal, partial };
Placement placement=Placement::external;
int allocations=0, releases=0;
bool in_use=false;
}

extern "C" void* heap_caps_malloc(size_t size, uint32_t caps) {
  assert(size==psram.size()*sizeof(int16_t));
  assert(caps==(MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT) && !in_use);
  ++allocations;
  if(placement==Placement::exhausted)return nullptr;
  in_use=true;
  return psram.data();
}
extern "C" void heap_caps_free(void* ptr) {
  assert(ptr==psram.data() && in_use);
  ++releases;
  in_use=false;
}
extern "C" bool esp_ptr_external_ram(const void* ptr) {
  assert(ptr==psram.data() || ptr==&psram.back());
  return placement==Placement::external ||
         (placement==Placement::partial && ptr==psram.data());
}

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
    // STOP arriving after end-of-speech must still destroy ready audio.
    assert(cap.push(silence, true, false) == CaptureResult::rejected);
    assert(cap.audio().empty());
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
  for(const auto failure : {Placement::exhausted, Placement::internal, Placement::partial}) {
    placement=failure;
    const int before=releases;
    QuestionCapture cap(300,k151_allocate_question_pcm);
    assert(!cap.prepare() && !in_use && cap.audio().empty());
    assert(releases==before+(failure==Placement::exhausted?0:1));
  }
  placement=Placement::external;
  {
    const int before=allocations;
    psram.fill(-1);
    QuestionCapture cap(300,k151_allocate_question_pcm);
    assert(cap.prepare() && cap.prepare() && allocations==before+1);
    assert(cap.push(speech,false,false)==CaptureResult::listening);
    assert(cap.push(silence,false,false)==CaptureResult::listening);
    assert(psram[0]==0 && psram[speech.size()-1]==0);
    for(size_t i=0;i<QuestionCapture::kStartFrames;++i)cap.push(speech,false,false);
    const size_t voiced=QuestionCapture::kStartFrames*speech.size();
    for(size_t i=0;i<QuestionCapture::kEndFrames;++i)cap.push(silence,false,false);
    assert(cap.audio().data()==psram.data() && cap.audio().size()==voiced);
    assert(psram[voiced-1]==2000 && psram[voiced]==0);
    assert(allocations==before+1 && in_use);
    cap.reset();
    assert(!in_use && psram[0]==0 && psram[voiced-1]==0);
    assert(cap.prepare());
    assert(cap.push(speech,false,false)==CaptureResult::listening);
  }
  assert(!in_use && psram[0]==0 && psram[speech.size()-1]==0);
  {
    const int before=allocations;
    QuestionCapture cap(300,k151_allocate_question_pcm);
    for(size_t i=0;i<QuestionCapture::kMaxFrames;++i) {
      const auto result=cap.push(speech,false,false);
      assert(result!=CaptureResult::rejected);
    }
    assert(psram.back()==2000 && allocations==before+1);
    assert(cap.push(speech,false,false)==CaptureResult::rejected);
    assert(!in_use && psram.front()==0 && psram.back()==0);
  }
  std::cout << "bounded question capture PASS (host-only)\n";
}
