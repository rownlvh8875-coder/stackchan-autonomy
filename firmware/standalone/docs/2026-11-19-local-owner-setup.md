# K151 first-use RAM-only local setup (2026-11-19)

**STATUS: COMPILE/TEST ONLY — NO DEVICE INSTALL, USB CREDENTIAL TRANSFER,
NVS WRITE, Wi-Fi ACTIVITY OR PAID OPENAI REQUESTS.**

This is the missing first-use configuration **state machine**, not a complete
credential-entry user interface or a secure-enrollment protocol. The ESP32
HOLD entrypoint references `K151LocalOwnerSetup::compiled_link_marker()`
but never creates or invokes any setup, network or audio object.

`OwnerSetupController` requires independent, trusted local-hardware-owner and
local-input-surface latches (both NOT PROVIDED in this firmware), plus a clear
physical STOP. No SCFG command or HTTP response can arm it.

The single-use sequence is:

1. `arm()`: verify both trusted on-device inputs and no previous credentials.
2. `submit_wifi()`: accept bounded SSID and valid WPA2/WPA3 passphrase.
3. `submit_api_key()`: accept a bounded printable ASCII key.
4. `confirm()`: require a second explicit on-device confirmation before
   copying the staged credentials into `RuntimeSecrets` (RAM only).
5. After STOP, owner-mode loss, trusted-input loss, 2-minute setup timeout,
   monotonic rollback, invalid input or invalid operation order, refuse all
   continuation, scrub staged buffers and wipe any controller-owned credentials.

A successful setup is one-shot per boot. It cannot reactivate after STOP or
be remotely replayed. The code does not print, return in an ACK, log or
serialize the credentials. Temporary copies can still exist in the caller,
FreeRTOS stacks or drivers, and this is NOT a hardware secure enclave.
An actual authenticated physical owner-control input path and trusted
configuration UI/PC bridge remain unimplemented. Generic untrusted USB SCFG
frames must NOT supply these values or override local latches.

**Why RAM only:** The factory backup indicates Flash Encryption is disabled.
NVS plaintext encryption cannot be assumed. API keys and Wi-Fi passwords are
not written to NVS, and will be lost on reset. Automatic headless restart
and unattended reconnect cannot yet work without fresh, owner-authorized
credential entry. Future encrypted key storage requires a separate threat
model, compatibility plan and explicit user approval.

Host tests use fake credentials. They cover flow order, separate final local
confirmation, invalid SSID/passphrase/token, STOP, timeout, monotonic clock
rollback, revocation after success, replay denial and preserving preexisting
credentials when not armed. These prove a portable policy, not authentication
of a physical button, Wi-Fi association, USB confidentiality or deployment
readiness.
