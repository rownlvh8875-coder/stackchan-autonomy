# K151 silent resource bench

Base: f63fb84102da99658aa8d0e6affdfa7fcec24560, same feat/wakeword-josu.
Scope authorized: code, offline tests, CI and review artifacts; no device writes.

1. RED/GREEN: verify the exact pinned embedded pack before SDK parsing, retain
   one global loader owner and irreversible failed-local-attempt gate. DROM
   lifetime, owner revocation, STOP and SDK cleanup must be tested.
2. RED/GREEN: bounded one-use local USB challenge/START/STOP parser. Separate
   silent diagnostic app; no NVS, audio, Wi-Fi, cloud, motors or display setup.
   Measure real model allocation, simultaneous question/TTS vectors, allocator
   placement and finite synthetic-silence detection. TLS remains unmeasured;
   never certify full operating admission from this bench.
3. RED/GREEN: independent review-bundle validator for app image, embedded pack,
   slot bounds and sector effects. Build with pinned IDF/SR, publish generic
   diagnostic image+proof+license only. Preserve HOLD app and original layout.
4. Run local regressions, one independent review, fix important findings with
   RED/GREEN, push same branch, inspect every actual CI job without reruns.
   Download built artifact and prepare private image/backup/restore manifest.

Ruling: embed the model in read-only app data using the pinned SDK srmodel_load
API, avoiding partition-table/NVS/model-region writes. This costs app space and
does not prove compatibility with the existing factory bootloader.
Ruling: local USB explicit START is lab operator consent, not authenticated
identity. A boot nonce prevents stale buffered START; no remote interface.
Ruling: installation remains unapproved and both factory OTA slots are occupied.
The backup's selected slot is not proof of the currently running slot or a spare.

Ledger: embedded entry RED (missing method), GREEN57 SDK cases; added mutable
PSRAM case RED (accepted), fixed explicit external-RAM rejection, GREEN12
embedded cases. Gate RED (missing header), GREEN. Image validation RED (missing
module), GREEN8 constructed-image cases. Optional full standalone444PASS5SKIP.
Root492PASS5SKIP: compiler PATH omitted in root shell; run skipped observer3
with correct PATH before recording coverage. Ruff340 files/diff PASS.
Observer3PASS with corrected compiler PATH; focused67PASS. One independent
final review found two Important artifact provenance issues. Fixed PR merge
checkout identity by recording actual git HEAD (configuration correction).
Wrong ELF/bin pairing regression RED (absent binding); added descriptor SHA
comparison; verification follows. No second review. Target build/CI pending.
No device actions this turn; A/B original hashes rechecked and private full
slot1 restore slice created. No backup bytes are published.

Target b09e63b: HOLD compile/link passed; separate bench compile FAILED because
IDF6.1 pins Mbed TLS4.1 and has no legacy mbedtls/sha256.h. Reproduced locally
by making the obsolete-header double reject. Replaced with pinned PSA Crypto
init/hash API, exact32-byte output, live owner recheck and no key/storage calls.
Added init-error/init-revocation/digest-length cases; focused71PASS, Ruff PASS.
Keep b09 target failure in history; a changed-source build is not a rerun.
Public review artifact also carries IDF/MbedTLS/SR license notices.

Post-target-API correction full standalone448PASS5SKIP (94.12s). Build graph
rejects NVS/Wi-Fi/HTTP/I2S components; prior target graph confirmed absence.

Exact b09 CI finished7/9: push3/4 (Windows3.11 check_timeout), PR4/4,
target0/1. New failed lease_check was interrupted inside SQLite COMMIT3.1134722s,
loop lag69.4647ms, executor wait4.3797ms; disk I/O vs worker descheduling remains
unresolved. Each check durably advances the anti-rollback coordination clock;
do not remove/relax that write or timeout just to obtain green. Numeric evidence
in docs/validation/2026-11-21-windows-ci-b09e63b.json. No failed run rerun.

Post-download d5 target compile/link PASS, image625968bytes/embedded pack/ELF
binding/esptool checksum all verified. However published source_head was empty:
container Git dubious-ownership error was swallowed in command substitution.
Do not approve that review bundle. Added8RED provenance guards/binding cases;
CI now captures Git HEAD with per-command named safe.directory, asserts it
equals GITHUB_SHA, puts12 chars in PROJECT_VER, and requires40hex/nonempty
commit+matching descriptor version. Real old d5 artifact rejected both for
empty source and attempted relabel with known merge6efd8b0. No device writes.

Created a protected current-user/SYSTEM-only full original copy on D: disk1,
distinct from C: disk0 (two512GB NVMe/NTFS); verified16777216bytes and original
SHA. This is a second local physical disk, not a cloud upload. Prepared exact
same-slot undo slice from full verified original, retaining whole-flash backup.

Provenance correction full standalone456PASS5SKIP (93.32s), image tests17PASS.
D5 CI completed9/9 (push44767547014, PR44767560777, S3 target44767560757),
but its review manifest is rejected for empty source despite successful compile.
Recorded this distinction; no failed CI rerun and no device writes. Final source
binding correction goes to the same branch/PR with a fresh changed-source build.

Approved physical execution (2026-11-21 KST): user said “진행해 승인”. Exact
ebed42c image SHA465cf701... installed once at0x510000,625968bytes (153sector
erase), independent verify PASS. One fresh USB nonce START,64synthetic chunks,
chunk512/max7615us/over100ms0, q384000/t960000 vectors bothPSRAM. No real audio,
Wi-Fi/cloud/output. Resident free internal354283/PSRAM8047576; concurrent free
internal354283/PSRAM6694860; TLS/operating admission false. Returned to ROM and
restored original fullslot5177344bytes at0x510000, independent verify PASS;
table/OTA identical prewrite/postbench/postrestore. Requested normal flash boot,
COM3OK; fresh user face/menu observation pending. No repeat bench, no full16MB
restore, no NVS/eFuse/table writes/stub. Wrapper falsely rejected native
successful original-slot verification text; corrected from saved log, no rerun.
Physical evidence: docs/validation/2026-11-21-k151-silent-resource-bench.{md,json}.
