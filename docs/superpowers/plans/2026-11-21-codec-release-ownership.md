# Retain K151 handles after failed driver release

Follow-up to K151_AUDIO_IO.ko.md and the native-wake bridge design. User authorized
offline implementation on feat/wakeword-josu/PR3. No device, reset, flash, recording
or paid API operation. HOLD/cloud OFF/output/drain false and physical/owner/model
admission remain unchanged. No new runtime subsystem or configuration relaxation.

## Task 1: driver cleanup failures

In actual-port C ABI tests, inject failed RX/TX disable followed by deletion
INVALID_STATE, for each direction/both and with status-query failure. Expect
shutdown false, PCM blocked/wiped, sticky fault and retained failed I2S handle.
An explicit later shutdown may attempt each retained channel once; confirmed
released handles must never be touched again. No automatic retry loop or later
success claim. Run new modes RED before clearing I2S pointers only on ESP_OK.

Ruling from pinned IDF source inspection: I2C deletion can return a pin-deinit
error AFTER freeing the wrapper, or fail BEFORE freeing it. Thus a failed bus
pointer cannot safely be retained/retried on return code alone. Keep the existing
no-reaccess behavior and sticky fault, add freed-error/live-error regression
coverage; do not claim the potentially retained bus was reclaimed. No reset or
private IDF object access to bypass uncertainty. I2S delete returns failures
before free and ESP_OK after free, so retaining a failed owned channel is valid.

## Task 2: AW88298 control boundary coverage

Correct the host output codec double to transfer two-byte register values as the
pinned AW88298 does; assert original address/value/length forwarding. Preserve
input one-byte behavior and all prior modes, add a two-byte fault/cleanup case.
Use a temporary truncating observer mutation to demonstrate regression sensitivity
without leaving mutation code in production. No real output-enable gate changes.

## Task 3: validate and deliver

Focused tests, full root and optional standalone suites, Ruff/format/owned diff,
original vendor bytes. One fresh final review per executing-plans. Fix Important
issues with RED/GREEN in one pass; ledger Minor findings. Commit/push same branch,
update PR3, observe first actual full CI and S3 builds; never rerun to obtain green.
Preserve historical Windows failures and distinguish Mock/target/physical results.

Interfaces: both tasks share k151_codec_io_test.cpp. The test ABI must reflect IDF
refusal to delete a running channel. SDK control destructor still hides device
removal errors; this plan avoids reaccessing the ambiguous bus pointer and keeps
the fault, without claiming bus/hidden child recovery or physical mute.

## Task 4: report evidence for the new CI lease-test failure

Actual8a34bc1 Push Windows3.12 failed the unchanged remaining-lifetime test before
virtual soak (494PASS1FAIL2SKIP148.74s); one local traced run did not reproduce it.
Add an explicit opt-in pytest fixture reusing TimingProbe, collect in the runner
context and print only bounded timing snapshot JSON on test-call failure. Keep
the original test TTL1.5/sleep0.6 and all assertions, no production edits. First
RED/GREEN subprocess tests prove original pass/fail exit preserved, failure-only
report, real AsyncStorage trace capture and no operation-data fields. Add the
fixture to the failed lease test; other tests remain uninstrumented. Same review
seat checks this added scope, no new parallel reviewer. Observe original CI to
completion before pushing diagnostics so it is not cancelled/replaced. New CI
is for changed instrumentation, never replaces8a34bc1 failure or proves its cause.
