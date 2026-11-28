// SPDX-License-Identifier: MIT
// No device access: fail-closed K151 power/reset and DMA policy fixtures.
#include "k151_output_evidence.hpp"
#include "k151_dma_tx_tail.hpp"
#include <cassert>
#include <iostream>

using namespace stackchan::standalone;

int main() {
  const auto at = [](DmaTxTail& tail, int64_t now) {
    return tail.poll([now] { return now; });
  };
  {
    DmaTxTail tail;
    using Result = DmaTxTail::Result;
    int descriptors[DmaTxTail::kDescriptorCount]{};
    constexpr size_t mono_bytes = 240 * sizeof(int16_t);
    tail.on_sent(&descriptors[0], mono_bytes);
    assert(at(tail, 1000) == Result::idle);
    assert(tail.arm(mono_bytes, 1000));
    int64_t now = 1000;
    for (const auto& descriptor : descriptors) {
      tail.on_sent(&descriptor, mono_bytes);
      now += 10000;
      assert(at(tail, now) == Result::waiting);
    }
    tail.on_sent(&descriptors[0], mono_bytes);
    assert(at(tail, now + 10000) == Result::observed);

    // A subsequent playback gets a fresh fence, including a new slot layout.
    assert(tail.arm(2 * mono_bytes, 101000));
    assert(at(tail, 101000) == Result::waiting);
    tail.on_sent(&descriptors[1], 2 * mono_bytes);
    tail.abandon();
    for (const auto& descriptor : descriptors)
      tail.on_sent(&descriptor, 2 * mono_bytes);
    assert(at(tail, 121000) == Result::failed && !tail.arm(mono_bytes, 121000));
    tail.reset_after_release();
    assert(tail.arm(mono_bytes, 131000) && at(tail, 131000) == Result::waiting);
  }
  for (int malformed = 0; malformed < 4; ++malformed) {
    DmaTxTail tail;
    int descriptors[DmaTxTail::kDescriptorCount]{};
    constexpr size_t stereo_bytes = 240 * 2 * sizeof(int16_t);
    assert(tail.arm(stereo_bytes, 1000));
    if (malformed == 0) {
      tail.on_sent(nullptr, stereo_bytes);
    } else if (malformed == 1) {
      tail.on_sent(&descriptors[0], stereo_bytes / 2);
    } else if (malformed == 2) {
      tail.on_sent(&descriptors[0], stereo_bytes);
      tail.on_sent(&descriptors[0], stereo_bytes);
    } else {
      for (const auto& descriptor : descriptors) tail.on_sent(&descriptor, stereo_bytes);
      tail.on_sent(&descriptors[1], stereo_bytes);
    }
    assert(at(tail, 2000) == DmaTxTail::Result::failed);
  }
  {
    DmaTxTail tail;
    constexpr size_t mono_bytes = 240 * sizeof(int16_t);
    assert(!tail.arm(mono_bytes, -1));
    assert(tail.arm(mono_bytes, 1000));
    assert(at(tail, 100999) == DmaTxTail::Result::waiting);
    int descriptors[DmaTxTail::kDescriptorCount]{};
    for (const auto& descriptor : descriptors) tail.on_sent(&descriptor, mono_bytes);
    tail.on_sent(&descriptors[0], mono_bytes);
    assert(at(tail, 101000) == DmaTxTail::Result::failed); // Late EOF cannot win.
  }
  {
    DmaTxTail tail;
    constexpr size_t mono_bytes = 240 * sizeof(int16_t);
    int descriptors[DmaTxTail::kDescriptorCount]{};
    assert(tail.arm(mono_bytes, 1000));
    for (const auto& descriptor : descriptors) tail.on_sent(&descriptor, mono_bytes);
    assert(at(tail, 61000) == DmaTxTail::Result::waiting);
    tail.on_sent(&descriptors[0], mono_bytes);
    assert(at(tail, 60000) == DmaTxTail::Result::failed);
  }
  K151OutputEvidence e;
  assert(assess_k151_output(e) == OutputBlock::board_unknown);
  assert(!may_enable_k151_output(e));
  e.exact_board_revision_verified = true;
  assert(assess_k151_output(e) == OutputBlock::i2c_not_exclusive);
  e.exclusive_i2c_ownership_verified = true;
  assert(assess_k151_output(e) == OutputBlock::rails_not_measured);
  e.axp2101_rails_measured = true;
  assert(assess_k151_output(e) == OutputBlock::aw9523_reset_unverified);
  e.aw9523_reset_sequence_verified = true;
  assert(assess_k151_output(e) == OutputBlock::amplifier_mute_unverified);
  e.aw88298_hardware_mute_measured = true;
  assert(assess_k151_output(e) == OutputBlock::physical_stop_unmeasured);
  e.independent_stop_latency_measured = true;
  assert(assess_k151_output(e) == OutputBlock::tx_drain_telemetry_unavailable);
  e.dma_tx_empty_and_codec_idle_observable = true;
  assert(assess_k151_output(e) == OutputBlock::hold_image_never_enables_audio);
  assert(!may_enable_k151_output(e));
  static_assert(!kK151PhysicalOutputEnabledInHoldImage);
  static_assert(!kK151SafeDmaDrainDriverAvailable);

  {
    DmaDrainLedger proof;
    assert(proof.begin(480, 100000));          // 20ms at 24kHz
    assert(proof.note_enqueued(240));
    assert(proof.note_enqueued(240));
    assert(!proof.confirmed());                // Queued ACK is not DMA drain.
    assert(proof.confirm(true, true, true, false, 120000));
    assert(proof.confirmed());
    assert(!proof.note_enqueued(1));           // One shot: cannot be reused.
    assert(proof.faulted() && !proof.confirmed());
  }
  {
    DmaDrainLedger proof;
    assert(proof.begin(240, 100000));
    assert(proof.note_enqueued(240));
    assert(!proof.confirm(true, true, true, false, 105000));
    assert(proof.faulted() && !proof.confirmed()); // Too early for 10ms.
  }
  {
    DmaDrainLedger proof;
    assert(proof.begin(240, 0));
    assert(proof.note_enqueued(240));
    assert(!proof.confirm(true, false, true, false, 20000));
    assert(proof.faulted());                   // Codec still queued.
  }
  {
    DmaDrainLedger proof;
    assert(proof.begin(240, 0));
    assert(proof.note_enqueued(240));
    assert(!proof.confirm(false, true, true, false, 20000));
    assert(proof.faulted());                   // TX DMA still active.
  }
  {
    DmaDrainLedger proof;
    assert(proof.begin(240, 0));
    assert(proof.note_enqueued(240));
    assert(!proof.confirm(true, true, false, false, 20000));
    assert(proof.faulted());                   // Unverified clock.
  }
  {
    DmaDrainLedger proof;
    assert(proof.begin(240, 0));
    assert(proof.note_enqueued(240));
    assert(!proof.confirm(true, true, true, true, 20000));
    assert(proof.faulted());                   // Physical STOP.
  }
  {
    DmaDrainLedger proof;
    assert(proof.begin(240, 100000));
    assert(!proof.confirm(true, true, true, false, 120000));
    assert(proof.faulted());                   // No samples submitted.
  }
  {
    DmaDrainLedger proof;
    assert(proof.begin(240, 0));
    assert(!proof.note_enqueued(241));
    assert(!proof.begin(240, 0));             // No silent reset after overflow.
  }
  {
    DmaDrainLedger proof;
    assert(!proof.begin(0, 0));
    assert(proof.faulted());
  }
  {
    DmaDrainLedger proof;
    assert(!proof.begin(DmaDrainLedger::kMaxPcmFrames + 1, 0));
  }
  std::cout << "K151 power+reset HOLD / DMA drain evidence: PASS (host only)\n";
}
