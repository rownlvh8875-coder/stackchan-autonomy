# K151 SCFG -> NVS enrollment bridge (compile-only)

**Not approved for device installation. No USB, NVS write, paid API or hardware use.**

This stage connects the verified portable `EnrollmentServer` (SWK1 features
only) to `PersistentGuard::save_profile`, and through it to the existing
isolated `IsolatedNvs` adapter. The new `ConsentProfileStore` requires a
separate *physical local enrollment* latch AND a clear STOP latch immediately
before each commit. The USB SCFG `enroll_begin` command cannot arm NVS write
privileges. A scoped permission callback enables `IsolatedNvs` writing only
during the commit, then revokes it even after storage failure. A post-commit
readback is required to report success, otherwise the persistent guard is
latched into failure. NVS erase, factory namespace migration, and automatic
profile provisioning are never performed.

The object is not constructed or invoked by HOLD `app_main`: the firmware
only compiles its marker. No physical button handler or console controller
currently supplies the required local consent. An `EnrollmentServer` can
be constructed with `K151UsbEnrollmentStorage::profile_store()` in a later,
separately approved device integration, but such activation is NOT part of
this stage.

STOP may occur while a flash commit is in flight. The bridge returns failure
if STOP is observed after the commit, but the previously written bytes MAY
remain on flash. A STOP or transport interruption does not prove rollback.

Host scenarios: explicit consent and no-consent, revocation between chunks,
failed/uncertain readback, replay rejection, STOP during commit. These are
fake-KV tests and NOT evidence of actual NVS behavior or physical ownership.

See `firmware/standalone/core/consent_profile_store.hpp` and the test.
