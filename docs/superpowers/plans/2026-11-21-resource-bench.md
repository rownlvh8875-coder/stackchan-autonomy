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
