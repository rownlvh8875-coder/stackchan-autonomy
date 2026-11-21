// SPDX-License-Identifier: MIT
#include "synthetic_wake_probe.hpp"
#include <cassert>
#include <stdexcept>
#include <string_view>
#include <vector>

using namespace stackchan::standalone;

struct Model final : NativeWakePort {
  size_t chunk = 512;
  bool reset_ok = true;
  bool crash_in_detect = false;
  int resets = 0, detects = 0;
  bool ready() const override { return true; }
  NativeWakeFormat format() const override { return {16000, chunk, 1, 16}; }
  bool reset() override { ++resets; return reset_ok; }
  NativeWakeResult detect(std::span<int16_t> samples) override {
    ++detects;
    assert(samples.size() == chunk);
    for (const int16_t sample : samples) assert(sample == 0);
    if (crash_in_detect) throw std::runtime_error("simulated interruption");
    return NativeWakeResult::none;
  }
};

int main(int argc, char** argv) {
  assert(argc == 2);
  const std::string_view test{argv[1]};
  Model model;
  bool allowed = test != "denied";
  int polls = 0;
  int64_t clock = 0;
  std::vector<std::string_view> marks;
  if (test == "first_poll_detect") model.chunk = 160;
  if (test == "reset_failure") model.reset_ok = false;
  if (test == "detect_interrupted") model.crash_in_detect = true;
  const auto trace = [&](std::string_view mark) {
    marks.push_back(mark);
    if (mark == "first_detect_begin" && test == "stop_before_detect") allowed = false;
    return test != "trace_error";
  };
  std::optional<int64_t> elapsed;
  try {
    elapsed = probe_synthetic_wake_input(
        model, [&] { return allowed; }, [&] { return ++clock; }, [&] { ++polls; }, trace);
  } catch (const std::runtime_error&) {
    assert(test == "detect_interrupted");
  }

  if (test == "denied") {
    assert(marks.empty() && model.resets == 0 && model.detects == 0 && !elapsed);
    return 0;
  }
  assert(!marks.empty() && marks.front() == "model_reset_begin");
  if (test == "trace_error") {
    assert(!elapsed && model.resets == 0 && model.detects == 0 && marks.size() == 1);
  } else if (test == "reset_failure") {
    assert(!elapsed && model.resets == 1 && model.detects == 0);
    assert(marks.size() == 2 && marks.back() == "model_reset_return");
  } else if (test == "stop_before_detect" || test == "detect_interrupted") {
    assert(!elapsed && model.resets == 1);
    assert(model.detects == (test == "stop_before_detect" ? 0 : 1));
    assert(marks.back() == "first_detect_begin");
  } else {
    assert(test == "complete" || test == "first_poll_detect");
    assert(elapsed == 1 && polls == 32 && model.resets == 2);
    assert(model.detects == (model.chunk == 512 ? 10 : 32));
    std::vector<std::string_view> expected{
        "model_reset_begin", "model_reset_return", "input_allocate_begin",
        "input_allocated", "input_configured", "first_poll_begin",
    };
    if (model.chunk == 512) expected.push_back("first_poll_return");
    expected.insert(expected.end(), {"first_detect_begin", "first_detect_return"});
    if (model.chunk == 160) expected.push_back("first_poll_return");
    expected.insert(expected.end(), {"final_model_reset_begin", "final_model_reset_return"});
    assert(marks == expected);
  }
}
