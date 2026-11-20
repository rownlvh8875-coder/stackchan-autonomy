# SCPS-specific USB wire format — no secrets in SCFG

The SCPS USB channel has its own **SCPW** fixed envelope, not the old **SCFG**
enrollment channel. All integer lengths are uint16 little-endian:

`"SCPW" | version=1 | kind:uint8 | payload_length:uint16 | payload | CRC32:uint32`

The CRC32 protects against accidental byte damage, **not an active attacker**.
Authenticity is established only after the PC operator compares the entire
8-digit SAS displayed on the already-verified K151 LCD. The encrypted
credential packet is authenticated with P-256 ECDH/HKDF/AES-GCM inside
`K151SecurePcSetup`.

Kinds, payload sizes:
- 1 `device_hello` (86 bytes, KSD1) → PC
- 2 `pc_hello` (86 bytes, KSP1) → device
- 3 `sealed_credentials` (35–359 bytes, KSE1) → device
- 4 `display_ready` (empty) → PC; **never transmits SAS over USB**
- 5 `pending_touch` (empty) → PC; secrets remain encrypted on device
- 6 `completed` (empty) → PC only after local second-touch approval and
  RAM-only successful setup confirmation
- 7 `denied` (empty); no secrets or reason text
- 8 `stop` (empty) → device; revokes pairing permanently

The portable C++ parser has strict magic, order, length and CRC checks, a
359-byte maximum payload, and a 3-second partial-frame timeout. One bad byte
or partial-frame timeout faults the reader permanently. There is no resync
to accidentally admit a console log or an SCFG frame. No real USB driver,
display or physical touch is installed from this file.
