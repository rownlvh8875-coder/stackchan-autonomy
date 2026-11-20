// SPDX-License-Identifier: MIT
// No device access: fail-closed K151 power/reset and DMA policy fixtures.
#include "k151_output_evidence.hpp"
#include <cassert>
#include <iostream>

using namespace stackchan::standalone;

int main() {
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
