# K151 SCPS PC Serial/JTAG operator tool (not yet approved for hardware)

A new `tools/scps_usb_wire.py` implements the exact strict `SCPW` v1 wire
envelope from `core/scps_usb_wire.hpp`. `tools/scps_usb_cli.py` is a
**manually activated** PC serial client; it does not discover, auto-connect
or install firmware on devices.

The PC must see the 86-byte device hello, send its 86-byte ephemeral hello,
receive a payload-free `display_ready`, then the operator must READ and
TYPE the full eight-digit SAS seen on the actual already-verified K151 LCD.
Only after exact match does the PC prompt for Wi-Fi SSID and hidden passphrase
and API key, encrypt the KSE1 packet and send it once. The PC waits for
`pending_touch` and then requires the human to hold/release the K151
head touch for three seconds before accepting a `completed` ACK.

- No API tokens in command-line arguments, environment variables, config,
  plain SCFG frames, error logs, or committed fixtures
- No retry after possibly delivered encrypted payload
- Wrong SAS, wrong state, bad framing, partial serial write or timeout fail
  closed; a best-effort STOP is sent without a success claim
- Key exchange authenticated ONLY by human full SAS comparison. An
  unverified screen or compromised PC breaks this guarantee
- Python immutable secret strings and pyserial/platform buffers cannot
  be promised to be fully erased
- There is **no** approved K151 SCPS USB listener yet, so running the CLI
  against the factory robot cannot provision it
- This tool is never run automatically by CI; tests use `FakePort` and
  `OfflineDeviceEmulator`, not COM ports or actual K151 firmware

Example syntax (only after separate physical/firmware approval; DO NOT RUN NOW):

`python firmware/standalone/tools/scps_usb_cli.py --port COM3 --interactive`

No deployment instructions or credentials are provided.
