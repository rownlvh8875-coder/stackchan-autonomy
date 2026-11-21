# K151 bounded codec I/O implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans inline. One fresh final review, no task implementer agents.

**Goal:** Harden dormant PCM I/O before any real mic activation.
**Architecture:** Non-owning data-interface adapter around the existing pinned
SDK I2S interface. Delegate configuration/enable to the same base pointer; keep
esp_codec_dev read/write so codec checks and software volume remain. Replace
only PCM transfer callbacks with one IDF call,20ms wait, exact byte count and
40ms post-call wall check. No retry or silence-on-reconfiguration success.
**Tech:** C++20, IDF6.1 fff9895, codec1.6.2, actual pinned SDK headers in host tests.
**Spec:** existing standalone design and native-wake bridge spec, plus this
bounded addendum. User explicitly opts out of code/design approval questions.

## Global constraints

Same feat/wakeword-josu/PR3, base cd067691ddcee224f0471a57e2abfc57b4f35dd5.
No new device access, flash, audio acquisition or paid API. Existing one-shot
physical approval is consumed; factory UI already confirmed after restoration.
HOLD/output false/cloud OFF,100ms input gap/chunk160..2048 unchanged. No owner,
power, asset or readiness fabrication. Config/open/close are synchronous and
outside the PCM wait budget; a driver timeout/postcheck is not hard STOP proof.
Port lifecycle is confined to one owner task, not concurrent destruction.

## Tasks

- [x] Reproduce current vendor wait1000/short-count acceptance with actual
  K151CodecPort compiled against SDK C ABI doubles. Pin original codec headers
  and LICENSE with hashes. Add adapter callback tests: exact/short/error/late/
  clock rollback, invalid format/enable and half-duplex; driver wait20 only.
- [x] Add non-owning adapter; preserve SDK base config/lifetime. SDK open ignores
  data set_fmt/enable returns, so port must independently verify adapter state.
  Any transfer/config error latches until teardown. No implicit reattach/retry.
- [x] Wire same existing port, RAII volatile PCM wipe on every local exit and
  caller rejection; MicFrameBridge/K151MicReader continue existing flow. Keep
  real speaker hard-disabled and drain false. Cover optimized end-of-life wipe.
- [ ] Run full host suites, one fresh final review, fix Important via RED/GREEN,
  actual pinned S3 CI, same-branch publish/results. No regenerated image install.

## Review focus

SDK base pointer forwarding and delete order; lost SDK callback errors; exact
counts/monotonic clock/one driver call; half-duplex + reconfiguration exclusion;
partial-buffer/early-return wipe; no claim of physical mute or hard STOP.

Ruling: preserve the vendor setup path rather than bypass esp_codec_dev_read/
write or replace its clock/slot configuration. Only callbacks change. Costs:
vendor open/close and driver internals remain synchronous/unpreemptible and
must be measured in a later authorized hardware build.
Ruling:20ms requested driver wait and40ms rejection postcheck are new dormant
PCM constraints, not an expansion of the existing100ms wake protocol bound.
IDF may wait on internal locks/queues; the postcheck refuses late audio after
return and does not make a preemption guarantee.

Ruling: query actual IDF6.1 channel is_enabled at shutdown. Vendor callbacks
change raw channel state, so cached port booleans cause a duplicate-disable
fault after successful mic close. Stateful C ABI reproduction failed, then
passed after the query; an unavailable query remains a fault with best-effort
disable. This is logical cleanup evidence, not physical mute telemetry.

RED/GREEN: old actual port reached1000ms driver wait; callback/reader rejection
retained PCM; active reformat and optimized invalid-frame wipe failed. Fixed
with one-call exact-count adapter + sticky state, RAII volatile wipe and format
exclusion. Negative control proves ordinary-fill destructor is elided at-O2.
SDK headers are unmodified system includes to isolate vendor C anonymous-union
extensions while retaining-Werror/-pedantic for our code.

Final review: one Important fixture checkout conversion fixed RED→GREEN with
a real core.autocrlf=true temporary checkout test and-text attributes. Minor
null callback handle parity/get_info failure branch fixture deferred.
Ruling: related cd06769 CI8/9 queue timing test assumed timeout40ms guaranteed
measured queue>=30ms. Pre-trace scheduling overhead disproved this locally
(20ms executor RED;35ms both tests RED). Preserve real40ms cancellation, pool,
lock/drain/count checks; compare reported wait against separately observed
real blocked sub-interval. Same35ms injection now2GREEN, timing module8GREEN.
No production timeout/lease/durability adjustment or failed CI rerun.
