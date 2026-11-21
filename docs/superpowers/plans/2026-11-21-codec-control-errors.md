# K151 codec control error propagation

Spec: existing native-wake bridge design and K151_AUDIO_IO.ko.md. This bounded
follow-up preserves HOLD, output/drain false, cloud OFF, physical preparation
gates and all wake/session/model protections. User authorized offline code and
same-branch PR work without repeated design approval. No device or paid API work.

Design: keep SDK codec/register protocols, I2C objects and single owner lifecycle.
Add a non-owning control interface which forwards the original base pointer and
latches failed register/info operations even if SDK gain/close discards results.
Permit cleanup after faults; a successful later cleanup cannot clear the fault.
Never interpret logical close or register success as physical mute evidence.

## Task 1: C ABI defensive boundaries

Modify k151_codec_io_test.cpp/test_k151_codec_io_build.py first. Invoke every
bounded-data callback with a null handle; expect false/INVALID_ARG, bounded read
buffer wipe, unchanged write source, no hardware calls. Run these RED before
adding minimal guards in k151_bounded_i2s.cpp. Inject I2S get_info failure during
shutdown; expect best-effort disable, false return and sticky fault on repeat.
The latter covers existing correct behavior and needs no artificial code change.

## Task 2: hidden codec control failures

Extend real-port C ABI doubles with distinct original input/output controls and
SDK-style ignored errors at initialization/open/gain/close. First prove port
incorrectly accepts these errors. Add k151_codec_control.hpp, integrate into
prepare/readiness/close/shutdown without changing SDK protocols or ownership.
Cover read and write failures, original pointer forwarding, cleanup after fault,
no further PCM and fault persistence. No retries or timeout extensions.

## Task 3: verification and handoff

Run focused tests, full root and optional standalone suites using assert-enabled
host compiler; owned-source diff/style checks and pinned header hashes. One fresh
final code reviewer required by executing-plans; Critical/Important get one fix
pass with RED/GREEN, Minors recorded. Update docs and sanitized validation record,
commit/push feat/wakeword-josu and update PR3. Observe first actual CI results,
including target S3 builds. Report Mock, target compile and physical validation
separately; retain historical failures. No installation approval is requested.

Interfaces: Task1 and Task2 share actual port test fixture; add fault modes rather
than replacing existing scenarios. Control wrappers live until both codec/dev
objects are deleted, then detach before their original SDK controls are freed.
