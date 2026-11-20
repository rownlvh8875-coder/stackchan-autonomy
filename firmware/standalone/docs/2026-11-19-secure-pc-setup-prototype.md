# SCPS v1 — encrypted PC setup experiment (2026-11-19)

**Status: OFFLINE reference, ESP32-S3 cross-compile-only receiver, not safe to install.**
No real USB serial transport, Wi-Fi/API key from the user, production credential
prompt, operating firmware, LCD activation, paid API or NVS mutation.

The existing `SCFG` receiver deliberately **does not accept API keys/passwords**:
CRC does not provide confidentiality or authentication. The new, distinct
`SCPS` envelope is a first-use credential-transfer experiment using standard
P-256 ephemeral ECDH, HKDF-SHA256 and AES-256-GCM via Espressif's PSA Crypto
on the device and Python `cryptography` on the PC reference.

## Bytes, strict version 1

- `device_hello`: `KSD1 | 0x01 | 65-byte SEC1 uncompressed P-256 pubkey |
  16-byte random nonce` (86 bytes)
- `pc_hello`: `KSP1 | 0x01 | 65-byte SEC1 uncompressed P-256 pubkey |
  16-byte random nonce` (86 bytes)
- `shared`: the 32-byte P-256 ECDH exchange; cryptographic point validity
  is checked by the underlying crypto provider
- `salt`: `device_nonce || pc_nonce` (32 bytes)
- `key`: HKDF-SHA256 32 bytes with info
  `K151-SCPS-v1/aes256gcm/ || device_pub || pc_pub`
- `SAS`: HKDF-SHA256 8 bytes with info
  `K151-SCPS-v1/sas/ || device_pub || pc_pub`; displayed as the *eight-digit*
  decimal encoding of this unsigned big-endian integer modulo 100000000.
- `credentials plaintext`: `KSC1 | 0x01 | ssid_len:uint8 | pass_len:uint8 |
  key_len:uint8 | ssid_bytes | passphrase_ASCII | api_key_ASCII` (max 324 bytes)
- `encrypted credentials`: `KSE1 | 0x01 | random_gcm_iv:12 | ciphertext_len:uint16LE |
  AES-256-GCM(ciphertext || 16-byte tag)`; authenticated associated data is
  `device_hello || pc_hello || first_19_bytes_of_encrypted_message`.
  Maximum total 359 bytes.

All messages are strictly length-bounded and single-use. Tag errors, wrong
version, bad P-256 point, wrong session, malformed fields, STOP, expiry and
repeat packets permanently fail that in-memory pairing session. No
keys/transcripts are intentionally stored to NVS or sent to logs. A failed
storage commit cannot be undone by USB STOP. Production code must use owner
confirmation, atomic setting handoff and secure terminal entry to enforce this.

## Manual SAS is mandatory

Ephemeral ECDH on untrusted USB is **not authenticated**. An active MITM can
create two separate exchanges and decrypt credentials unless a human checks
that the full 8-digit SAS on the **actual K151 LCD** matches the full 8-digit
code on the trusted PC. The physical local display path and comparison
confirmation must be independently reviewed. The expected accidental collision
probability per attempt is approximately 1 in 100 million, assuming fresh
unbiased sessions and careful comparison. This is not biometric identity,
not secure against a compromised PC/LCD, and not a substitute for verified
physical ownership.

The ESP32 module requires local consent and SAS confirmation as input gates,
but the physical user interaction and actual USB port are **NOT wired yet**.
It never constructs a crypto object at boot; only a marker is linked.
`K151SetupLvgl::present_pairing_sas()` can display the nonsecret digits only
on an **already verified, initialized** panel with a held LVGL owner lock;
it never initializes LCD, PMIC, SPI or device I2C. The setup UI is not a
trusted device pairing display until the actual board variant is validated.

## PC reference

`tools/scps_reference.py` implements PC-side in-memory key exchange/envelope
construction and a separate *offline-only device emulator* for test fixtures.
It has **no serial/COM input or output**, no user-secret prompt, and no stored
private keys or real credentials. Python immutable strings, third-party
library copies and allocator pages cannot be guaranteed to zero immediately.
It must not be presented as a ready-to-use credential provisioner.

Offline test fixture:

```
uv run --frozen --with cryptography==46.0.4 python -m pytest -q \
    firmware/standalone/tests/test_scps_reference.py
```

Test cases: matching SAS, wrong/unapproved SAS, ciphertext tamper/tag failure,
wrong device, replay, wrong packet length/version/point, STOP, and invalid
SSID/passphrase/key. *Both* sides run in Python for these tests. This does
not independently execute the PSA implementation or prove interop on ESP32-S3.
The separate ESP-IDF CI only compiles/links the PSA code.

## Unresolved before physical deployment

1. Trusted K151 display and Si12T power/I2C initialization; low-risk LCD
   variant identification, actual SAS presentation and user interaction.
2. Encrypted SCPS framing over the real USB Serial/JTAG transport without
   colliding with the separate SCFG enrollment or UART console.
3. Connect verified decrypted credentials to `OwnerSetupController` and the
   **second** three-second head-touch confirmation; use one owner task.
4. Field-tested PSA ↔ Python transcript interop, USB disconnect races,
   hard STOP interruption latency, PSRAM/heap usage and recovery testing.
5. Final firmware recovery and partition validation before any device flash.

No encryption of long-term secrets at rest is claimed. The user's backed-up
K151 Flash Encryption is disabled; RAM-only provisioning must be repeated after
power loss. Do **not** flash, merge, auto-enable radios, or send live paid API
requests based on a passing host test or cross-compilation alone.
