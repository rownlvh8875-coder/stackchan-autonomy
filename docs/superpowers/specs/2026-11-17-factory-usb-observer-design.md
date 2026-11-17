# Factory-based USB observer: design for the next autonomy milestone

Date: 2026-11-17 KST. Status: APPROVED for implementation by the user's “그래 진행해”.
Fresh ESP32/Python builder check completed: nothing important left for planning.
The user chose preparation of an official-firmware extension, explicitly not permission
to install firmware. Preserve the current working GPT/official-app setup on the device.

## Intent and scope

Give the PC real K151 camera/sensor observations, then let GPT describe them. This is
the next prerequisite to physical autonomy. The existing engine already has offline
decision/safety/control tests; another simulated motor demo would not close this gap.

This project produces an opt-in read-only firmware patch, PC USB client, and optional
GPT image observation tool. No motion/expression/LED commands, no device flashing,
no backup erase/provisioning or real cloud/device calls during development.
Physical action ownership, real STOP and sustained physical operation are later milestones.

## Findings and approaches

Official main was checked using GitHub on 2026-11-17 and matches cached SHA
`28b9f0c8bd6acd81cb3c70f1a93c3e373b39d400` (firmware project version1.6.2).

1. **Existing external MCP extension.** Works for GPT speech. It serves PC tools to
   the official AI; it is not a PC client to the robot's tool catalog/camera.
2. **Emulate the official Avatar transport.** LAN is a phone-hosted WebSocket and
   the robot connects after an AppLanAddress announcement. Server addresses/RSA
   configuration are deployment inputs, not the user's external MCP URL. The public
   `secret_logic.cpp` supplies weak placeholder authentication functions; a rebuild
   must not be assumed equivalent to the shipped service configuration.
3. **Official-source observer extension, user-selected family.** Builder proposes
   dedicated USB observation first: no dependency on unpublished broker configuration,
   new LAN port or TLS credential distribution. Wi-Fi HTTPS is deferred. The source
   patch keeps the official code as its base; service compatibility still needs proof.

Source references at the pinned SHA: `firmware/main/hal/hal_mcp.cpp`,
`hal/utils/local_network/{local_avatar_client.cpp,local_network_protocol.h}`,
`hal/utils/secret_logic/secret_logic.cpp`, `hal/hal_servo.cpp`, `hal/hal.cpp`,
`app/lib/network/local_area_network_service.dart`, `app/lib/util/value_constant.dart`.
No production broker keys, private-key extraction or account bypass is part of this design.

## Deliverables and ownership

- `firmware/observer/`: original, documented ESP-IDF component/patch against the pinned
  official tree, provenance/license notices, build recipe and host-side codec tests.
  Keep upstream source/dependency caches outside tracked code. No silent upstream update.
- PC observer module/CLI: explicit COM-port selection, bounded framing and snapshots,
  metadata-only local diagnostic output; source/editable and wheel support.
- GPT bridge: optional `--observer-port` alongside `--gpt`, with
  `STACKCHAN_IMAGE_TRANSMISSION=true` required for sending a snapshot to OpenAI.
  Register a separate `stackchan_gpt_observe(question)` tool only in this mode.
- Operator instructions and evidence distinguish codec/SDK/firmware-build checks from
  real hardware, image transmission, service coexistence and motor/STOP acceptance.

## Firmware behavior

- Observer is disabled by default. When enabled, use the ESP32-S3 native USB
  Serial/JTAG peripheral as a dedicated data channel. Do not use/reconfigure the servo
  UART, BLE or LAN transport. UART0 remains the console; USB secondary-console use
  must be disabled or configuration rejected to avoid a shared stream/driver conflict.
- Exact K151 connector routing/Windows port identity must be verified before a hardware
  trial. Do not infer the data port from a power cable or arbitrarily select the first COM port.
- Start a bounded observer worker after HAL initialization. Existing main UI/AI tasks
  remain in place. Serialize observer requests; reject busy camera access without
  waiting on an unbounded queue or retaining a stream of frames.
- `snapshot` acquires the existing camera frame lock, captures/encodes one JPEG in RAM,
  releases the lock and frees owned buffers. No ongoing camera stream, file write,
  microphone operation or cloud upload. Return BUSY/UNAVAILABLE on conflict/failure.
  Reviewed implementation uses a narrow conditional camera-access patch: discard/requeue
  the pinned single-buffer DVP's outstanding frame, lease the next with conservative time,
  validate raw format/length/mapping and never replace the official retained `frame_`.
- `status` returns capabilities and cached touch/IMU events with age/provenance.
  Use existing public event signals; unavailable/never-observed is null, not false/zero.
  Exact event names/cache hooks and numeric representation are builder decisions based
  on the pinned drivers. Do not invent sensor readings or disable official consumers.
- Initial `head_pose` is null and `pose_verified=false`. The official getCurrentAngle
  implementation can fall back to estimated state after failed ReadPos; it is not a
  sufficient freshness/error contract for this project's physical control authority.
- This worker introduces no actuator calls. Existing factory boot/idle/AI behavior
  may still move the device; read-only does not promise the entire device is motionless.

## USB contract v1

Dedicated channel, no caller-selected operation strings, URLs, paths or file commands.
Use a 32-byte binary envelope in network order:

| Field | Bytes |
|---|---:|
| magic `SCOB` | 4 |
| version1 | 1 |
| message kind | 1 |
| flags, must be0 | 2 |
| fresh request nonce | 16 |
| payload length | 4 |
| CRC32 | 4 |

CRC covers the first28 header bytes plus payload. CRC detects corruption, not peer
authentication. USB physical attachment/explicit operator pairing is the trust boundary.
PC nonces are fresh128-bit random values, never reused on retry. No automatic retry.
Allow commands HELLO=1, STATUS=2, SNAPSHOT=3 only. Responses use0x81 hello JSON,
0x82 status JSON,0x83 snapshot metadata JSON,0x84 JPEG and0xff fixed error JSON.
Only one request can be in flight. HELLO has no payload; later commands carry the
16-byte boot ID from HELLO. Wrong boot ID/nonce/kind/size/CRC is an error, not fallback data.

HELLO JSON identifies contract1, an explicitly unofficial observer build, boot ID,
stable device identity and read-only capabilities. PC pairing pins identity locally;
identity/port/boot IDs never go to OpenAI or normal logs. Pairing and subsequent
identity-change rejection must be explicit; no silent trust-on-reconnect.

SNAPSHOT returns metadata then JPEG for the same nonce, boot ID and image identity.
Metadata includes captured monotonic time, dimensions, byte count and SHA-256.
Limits: metadata4KiB, JPEG128KiB, image pixel count307200 and maximum dimension640.
PC verifies exact lengths/hash, format/decode/dimensions and freshness before use.
Bound resynchronization across boot noise to1MiB and finite time. Emit only fixed
codes on serial errors, never echo received console bytes.

Request deadline default10s, configurable1–30s. Firmware capture lock attempt is
nonblocking; transport timeout does not become a new capture request. A failed or
partial request is abandoned; a new operator attempt starts a fresh handshake.
Serial DTR/RTS must be set inactive before opening; reset/glitch behavior still needs
hardware verification and is not guaranteed by a Python unit test.

## PC/GPT behavior and data handling

- The observer CLI can pair/read status/capture one frame with cloud entirely off.
  Pairing profile contains only local device identity/port metadata, never API secrets.
  Default profile is git-ignored; installed-wheel use works outside the checkout.
- GPT image observation requires explicit mode plus image transmission opt-in; ordinary
  GPT text questions remain unchanged. Validate image and source binding before reserving
  API quota. Send the one image, question and sensor/provenance metadata only.
- Reuse existing fixed OpenAI endpoint, persistent quota, retry0, timeout and private logs.
  Do not mix image observations into text-chat history or persist image/dialogue data.
  The observation tool returns a bounded Korean explanation and capture-age/source labels.
- No proposed motion command is exposed to the official AI in this milestone. It must
  not be able to turn an unverified observation into this program's motor authority.
  Our bridge does not restrict unrelated factory/official-AI controls.
- No raw image, pixel signature, description, serial text, credentials or identifying
  device metadata in normal console/logs. Fixed lifecycle/call/success markers only.
  Synthetic fixtures are permitted in automated tests and clearly labeled as such.
  The paid path rebuilds JPEG from decoded pixels to strip metadata/trailing data;
  MCP cancellation received during capture suppresses the pending image upload.

## Build and verification

1. Meaningful RED→GREEN codec tests with literal packets and independent CRC checks:
   fragmentation, noise, truncation, overflow, CRC/type/version errors, stale boot ID,
   wrong device and mixed response nonces. Test disallowed opcodes cannot reach a backend.
2. C++ host tests execute the same firmware codec/dispatcher logic with a fake camera/
   sensor backend. Include busy, failure and buffer cleanup; do not call this a firmware build.
3. Pin ESP-IDF6.1 and dependencies; produce a real ESP32-S3 build of the patched source
   with reproducible manifest/checksums. Temporary build-only configuration is not
   production authentication. If the real toolchain/build is unavailable, explicitly
   leave the build blocked; never substitute host stubs for a flash-ready artifact.
4. Python serial tests use a real local byte-stream fixture, plus real MCP/Responses SDK
   with MockTransport for optional image replies. Cover consent, source freshness,
   bounded image validation, quota/privacy and diagnostic-mode compatibility.
5. Full offline suite/lint/package checks, fresh review and Windows/Linux validation.
   Real COM/driver timing, physical camera/sensors, simultaneous official voice and
   image use, recovery and actual API vision stay pending until operator evidence.

## Installation hold and later milestones

No installer/flash/erase step runs as part of this work. A prototype binary, if built,
is labeled NOT APPROVED FOR DEVICE INSTALLATION. Before proposing a device trial:

- Verified full flash/NVS/calibration backup with hashes and a concrete restore path.
- Matching board/LCD configuration and native USB connector/driver confirmed.
- Resolve the public-source placeholder service authentication via a supported build/
  provisioning path, or get an explicit decision about changing backend/app behavior.
  Do not promise the official app/GPT connection survives a source rebuild.
- Review startup/NVS behavior: upstream HAL can erase NVS after initialization errors,
  and stock servo initialization can move hardware. A read-only patch does not remove these.
- Separate, explicit user approval of the exact image/configuration and installation.

After real observation works: introduce a device-side ownership/fencing and STOP
contract, validate physical feedback/limits and small approved actions; only then
connect autonomous decision execution and perform sustained hardware operation tests.
