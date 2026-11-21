# K151 board readback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prepare actual board/power readback evidence before microphone activation.
**Architecture:** Extend existing K151ReadOnlyProbe, preserve non-authorizing
ReadOnlyEvidence, reuse the existing one-shot USB BenchGate in a separate
minimal app. No I2S/codec/amp/power-register writes, model, Wi-Fi or NVS startup.
**Tech Stack:** pinned IDF6.1, C++20, host C ABI doubles, Python image verifier.
**Spec:** existing 2026-11-18-standalone-gpt-design.md and this bounded addendum.

## Global Constraints

Same feat/wakeword-josu/PR3, base4386dd6. No additional device writes approved.
No hardware access in this implementation, no real voice/API/profile activity.
HOLD remains; owner/assets/readiness never fabricated. Readback of programmed
rails/reset latches is not an electrical voltage/mute/STOP proof. Previous face
observation is still pending and must precede any future approved device trial.

## Tasks

- [x] RED/GREEN actual probe C ABI: reproduce SDK8bit→IDF7bit bug (0x80→0x40,
  0x6c→0x36), cleanup/STOP/revocation/read failure; no partial valid publication.
- [x] Extend fixed read list: AXP2101 ID0x03 and LDO config0x90/94/95/97/99;
  AW9523 ID0x10/output0x02..03/direction0x04..05; preserve touch0xa3..a8.
  Publish each register group validity separately; every call bounded30ms.
- [x] Implement separate board_probe app reusing probe and BenchGate; nonce START
  once, STOP latch, only fixed numeric register JSON, no raw audio or writer.
  Record actual running partition offset and live chip model/revision so a
  future physical run can resolve slot ambiguity. Fail closed on unexpected slot.
- [x] Reuse/refactor ESP image envelope/ELF/source binding verifier; reject wrong
  app kind/slot/revision/checksum/hash/ELF/version. Build exact S3 target and
  review artifact+license through existing pinned CI. No installation now.
- [x] Local suite, one independent end review, fix important findings RED/GREEN,
  same-branch push and inspect actual CI. Prepare private install/restore review
  bundle before any new write question. Preserve prior CI failures.

## Review Focus

7bit bus addresses; no device-configuration writes; stop/owner checks around
synchronous reads; cleanup error preservation; stale/partial evidence invalid;
no readiness promotion; provenance cannot be empty; no secret/backup artifacts.

Ledger: primary pinned codec1.6.2 headers define0x80/0x6c and its I2C control
adapter shifts by1. Existing probe passes these directly to IDF7bit calls.
Source audit also found codec1.6.2 data I/O uses1000ms timeout and ignores short
byte counts; current10ms comments describe payload length, not STOP latency.
Do not activate microphone through that path before bounded-I/O hardening.
Ruling: collect board state before RX-only activation; shared power/mute remains
unmeasured, so a split driver alone cannot satisfy its physical prerequisites.
Ruling: read only the five PMIC configuration registers used by the pinned
manufacturer board source, rather than the whole 0x90..0x9a interval; minimizes
bus activity and avoids unneeded register semantics. These are programmed
configuration values, not electrical rail measurements.
Ruling: centralize physical seven-bit addresses in board_evidence.hpp and check
them against pinned codec defaults at compile time in K151CodecPort. The small
board app then has no codec/I2S/model dependency merely to obtain addresses.

Local progress: address regression failed before shifting the old defaults;
extended reads failed at runtime before implementation. The actual C++ observer
now passes 73 cases (success, NACK, denied, stopped; failure/STOP/revocation at
all 23 SDK boundaries), compiled optimized with assertions enabled. Slot/chip
scope test failed before the predicate existed, then passed. Board image tests
failed before the dedicated verifier, then passed alongside bench regressions.

Final review: one fresh read-only reviewer; Important3 accepted and fixed by
RED→GREEN tests for selected build slot, actual denial telemetry and required
license packaging. Minor mixed NACK fixture deferred. Local root495PASS2SKIP;
finite Windows Mock120cycles PASS (no CI stall reproduced). No device access.

Final target: 36c4e98 code / c991ec9523d6a82c6908c9aa4bade5b8fdb62991 actual
checkout, run44844341123 PASS. Board image185744bytes, SHA128969c002b9b1242679baf1658b66951fe7c7c076b00e573dd221d34ff5aa17;
ELF/ZIP/CSV/source/license50 inventory all revalidated locally. Review bundle
includes exact write/erase, full same-slot recovery, rehashed backups and commands.
Code CI8/9: push4/4, PR3/4, S3 1/1. PR Windows3.11 root heartbeat test fails
StateUnavailable before virtual soak; no rerun or limit change. See sanitized
validation/2026-11-21-k151-board-readback-preflight.md. This is a prepared
diagnostic prerequisite, not completion of standalone operation or CI repair.
