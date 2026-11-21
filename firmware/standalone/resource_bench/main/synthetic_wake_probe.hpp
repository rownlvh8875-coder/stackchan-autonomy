// SPDX-License-Identifier: MIT
#pragma once
#include "native_wake_input.hpp"
#include <algorithm>
#include <memory>
#include <optional>
#include <string_view>

namespace stackchan::standalone {
namespace silent_probe {
class Silence final : public MonoMicReader {
 public:
  bool read_10ms(std::span<int16_t> pcm) override {
    if (pcm.size() != 240) return false;
    std::fill(pcm.begin(), pcm.end(), 0);
    return true;
  }
};

template<class Mark>
class FirstDetectTrace final : public NativeWakePort {
 public:
  FirstDetectTrace(NativeWakePort& model, const Mark& mark) : model_(model), mark_(mark) {}
  bool ready() const override { return model_.ready(); }
  NativeWakeFormat format() const override { return model_.format(); }
  bool reset() override { return model_.reset(); }
  NativeWakeResult detect(std::span<int16_t> pcm) override {
    if (!first_) return model_.detect(pcm);
    first_ = false;
    if (!mark_("first_detect_begin")) return NativeWakeResult::error;
    const auto result = model_.detect(pcm);
    return mark_("first_detect_return") ? result : NativeWakeResult::error;
  }
 private:
  NativeWakePort& model_;
  const Mark& mark_;
  bool first_ = true;
};
}  // namespace silent_probe

constexpr unsigned kSyntheticWakeFrames = 32;

template<class Allowed, class Clock, class Yield, class Trace>
std::optional<int64_t> probe_synthetic_wake_input(
    NativeWakePort& wake, const Allowed& allowed, const Clock& clock,
    const Yield& yield, const Trace& trace) {
  const auto mark = [&](std::string_view name) {
    return allowed() && trace(name) && allowed();
  };
  if (!mark("model_reset_begin")) return std::nullopt;
  const bool initial_reset_ok = wake.reset();
  if (!mark("model_reset_return") || !initial_reset_ok ||
      !mark("input_allocate_begin")) return std::nullopt;

  // Keep the shared 2048-sample buffer off the main task's 8 KiB stack.
  auto input = std::make_unique<NativeWakeInput>();
  if (!mark("input_allocated") || !input->configure(wake.format()) ||
      !mark("input_configured")) return std::nullopt;

  silent_probe::Silence source;
  silent_probe::FirstDetectTrace model{wake, mark};
  int64_t max_poll_us = 0;
  for (unsigned i = 0; i < kSyntheticWakeFrames; ++i) {
    if (i == 0 && !mark("first_poll_begin")) return std::nullopt;
    const auto before = clock();
    if (before < 0) return std::nullopt;
    const auto result = input->poll(source, model, allowed);
    const auto after = clock();
    if (i == 0 && !mark("first_poll_return")) return std::nullopt;
    if (after < before || result != NativeWakeResult::none) return std::nullopt;
    max_poll_us = std::max(max_poll_us, after - before);
    yield();
  }
  if (!mark("final_model_reset_begin")) return std::nullopt;
  const bool final_reset_ok = wake.reset();
  if (!mark("final_model_reset_return") || !final_reset_ok) return std::nullopt;
  return max_poll_us;
}
}  // namespace stackchan::standalone
