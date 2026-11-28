// SPDX-License-Identifier: MIT
#include "k151_aec_stop_probe.hpp"
#include "k151_aec_timeline.hpp"
#include "k151_probe_tone.hpp"

#include <algorithm>
#include <array>
#include <cassert>

using namespace stackchan::standalone;

namespace {
using Probe = K151AecStopProbe;
constexpr auto tone = k151_probe_tone<Probe::kFramesPerBlock * 3>();
enum class Signal { quiet, tone, mic_only, clipped, wrong_frequency };

bool feed(Probe& probe, uint32_t first, Signal signal, size_t tone_frames = Probe::kFramesPerBlock) {
  std::array<int16_t, Probe::kFramesPerBlock * Probe::kSlots> dma{};
  for (size_t frame = 0; frame < Probe::kFramesPerBlock; ++frame) {
    const int16_t value = tone[Probe::kFramesPerBlock + (frame + 5) % 24] / 8;
    dma[frame * Probe::kSlots] = value; // Always make the microphone a false witness.
    auto& reference = dma[frame * Probe::kSlots + Probe::kReferenceSlot];
    reference = frame % 2 ? 3 : -3;
    if (signal == Signal::tone && frame < tone_frames) reference = value;
    if (signal == Signal::wrong_frequency) reference = frame % 2 ? 512 : -512;
    if (signal == Signal::clipped) reference = 32767;
    dma[frame * Probe::kSlots + 2] = value;
  }
  const bool accepted = probe.observe(first, dma);
  assert(std::ranges::all_of(dma, [](auto sample) { return sample == 0; }));
  return accepted;
}

void establish_baseline(Probe& probe, uint32_t planned_end = 60'720) {
  for (uint32_t first = 0; first < 720; first += 240)
    assert(feed(probe, first, Signal::quiet));
  assert(probe.begin_tone(planned_end));
}

void establish_tone(Probe& probe) {
  establish_baseline(probe);
  assert(feed(probe, 720, Signal::tone));
}
}

int main() {
  K151AecTimeline clock;
  assert(clock.accept(0, 10'000));
  assert(!clock.stop_bracket(10'000)); // A previous and next EOF are both required.
  assert(clock.accept(240, 19'900));
  const auto bracket = clock.stop_bracket(14'300);
  assert(bracket && bracket->first_frame == 240 && bracket->end_frame == 480);
  assert(bracket->before_us == 10'000 && bracket->after_us == 19'900);
  assert(!clock.stop_bracket(19'900) && !clock.stop_bracket(9'999));
  assert(!clock.accept(480, 39'900) && !clock.valid()); // A missing EOF cannot become quiet.
  assert(!clock.stop_bracket(14'300));
  K151AecTimeline rollback;
  assert(rollback.accept(0, 30'000) && !rollback.accept(240, 29'999));
  K151AecTimeline skipped;
  assert(skipped.accept(0, 30'000) && !skipped.accept(480, 40'000));

  static_assert(Probe::kSampleRate == 24000 && Probe::kReferenceSlot == 1 && Probe::kSlots == 4);
  static_assert(Probe::kBclkHz == 1536000);
  Probe good;
  establish_tone(good);
  assert(good.mark_stop(960 + 29));
  assert(feed(good, 960, Signal::tone, 73));
  assert(!good.cutoff()); // A short dip cannot finish the observation.
  for (uint32_t first = 1200; first <= 2160; first += 240)
    assert(feed(good, first, Signal::quiet));
  const auto cut = good.cutoff();
  assert(cut && cut->stop_frame == 989);
  assert(cut->first_possible_frame <= 1033 && cut->quiet_by_frame >= 1033);
  assert(cut->quiet_by_frame - cut->first_possible_frame <= 72);

  for (auto signal : {Signal::mic_only, Signal::wrong_frequency}) {
    Probe no_reference;
    establish_baseline(no_reference);
    assert(feed(no_reference, 720, signal));
    assert(!no_reference.mark_stop(960));
    assert(!no_reference.cutoff());
  }

  Probe silence_before_stop;
  establish_tone(silence_before_stop);
  assert(silence_before_stop.mark_stop(960 + 48));
  assert(!feed(silence_before_stop, 960, Signal::quiet));
  assert(!silence_before_stop.cutoff());

  Probe no_stop;
  establish_tone(no_stop);
  assert(!feed(no_stop, 960, Signal::quiet));
  assert(!no_stop.cutoff());

  Probe missing_dma;
  establish_tone(missing_dma);
  assert(missing_dma.mark_stop(960));
  assert(!feed(missing_dma, 1200, Signal::quiet));
  assert(!missing_dma.cutoff());
  assert(!feed(missing_dma, 960, Signal::quiet));

  Probe unknown_stop_frame;
  establish_tone(unknown_stop_frame);
  assert(!unknown_stop_frame.mark_stop(1200));
  assert(!unknown_stop_frame.cutoff());

  Probe natural_end;
  establish_baseline(natural_end, 2'160);
  assert(feed(natural_end, 720, Signal::tone));
  assert(!natural_end.mark_stop(961)); // The 50 ms witness would overlap the planned end.
  assert(!natural_end.cutoff());

  Probe clipped;
  establish_baseline(clipped);
  assert(!feed(clipped, 720, Signal::clipped));
  assert(!clipped.cutoff());

  Probe rebound;
  establish_tone(rebound);
  assert(rebound.mark_stop(960));
  assert(feed(rebound, 960, Signal::quiet));
  assert(feed(rebound, 1200, Signal::tone));
  for (uint32_t first = 1440; first < 2160; first += 240)
    assert(feed(rebound, first, Signal::quiet));
  const auto late_cut = rebound.cutoff();
  assert(late_cut && late_cut->first_possible_frame >= 1416 && late_cut->quiet_by_frame == 1464);

  Probe malformed;
  std::array<int16_t, 7> short_read{};
  short_read.fill(123);
  assert(!malformed.observe(0, short_read));
  assert(std::ranges::all_of(short_read, [](auto sample) { return sample == 0; }));
  assert(!malformed.begin_tone(60'720));
}
