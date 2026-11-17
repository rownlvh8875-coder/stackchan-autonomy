# USB observer development validation — 2026-11-17

Scope: user-approved implementation of the official-source observer design. Installation
was explicitly excluded. No physical serial port, camera, sensor, motor, vendor account,
operator secret or paid API was accessed during this work.

## Evidence

- Existing baseline415 PASS (66.02s). New protocol/client tests initially failed for
  the missing observer module; firmware host tests failed for the missing C++ core;
  SDK/MCP tests failed for missing observe/async-provider functionality. Implemented
  them and fixed the boot-noise limit boundary found by the adversarial test.
- Final full offline suite459 PASS (71.01s). Observer + GPT/MCP/CLI target suite155 PASS
  (6.22s). Tests use synthetic JPEGs, local socket byte streams, actual C++ dispatcher,
  real MCP/WebSocket sessions, actual Responses SDK/SQLite and MockTransport.
- Ruff check/format PASS. Source distribution and wheel built; isolated installed
  package probes outside the checkout passed, including synthetic serial→validated
  image→SDK input and the existing default/GPT MCP paths. Package contents checked
  for exclusion of local work/build data and environment files.
- **Real ESP32-S3 build PASS**, not a host substitute. ESP-IDF v6.1 exact SHA and six
  Git dependency SHAs are in [build manifest](2026-11-17-usb-observer-build.json).
  Managed dependency lock/config/source/output hashes are recorded there. Observer
  core and HAL adapter appear in compile commands; ELF machine is Xtensa94.
  Observer is enabled, UART0 console/USB secondary disabled, camera DEBUG hexdumps
  compiled out. Public-source auth placeholders are not production provisioning.
- Initial ESP-IDF environment creation required its target directory to exist. First
  device build exposed removed `mbedtls/sha256.h` under IDF6.1; changed to the supported
  PSA SHA256 API and rebuilt. Final build includes the logging privacy guard.
- Source packaging was restricted to explicit project directories so ignored SDK/build
  caches are excluded from both artifacts and source-distribution scanning.

Fresh whole-change review found camera freshness/shared-frame isolation/raw-length,
JPEG metadata privacy, cancellation, Windows binary stdio and sdist-input defects.
One tested fix pass addressed them and all smaller findings:

| Finding | Tested final disposition |
|---|---|
| Old queued DVP frame dated as new | Discard/requeue the verified single outstanding buffer, lease the next; conservative request-start timestamp |
| Replacing the stock pending photo | Narrow conditional camera-access patch; read driver queue independently, never write stock `frame_` or join encoder |
| Short raw image passed to unsafe converter | Validate pointer, error flags, mapped/valid sizes, format, dimensions and packed row; lease/requeue checked on every exit |
| EXIF/trailing bytes sent to API | Rebuild a bounded metadata-free JPEG from decoded pixels; adversarial synthetic fixture PASS |
| Cancel during capture still uploads | Bounded read-ahead handles active/queued cancellation, one SDK admission; gated MCP capture cancellation spends no quota/API request |
| Windows text-mode wire corruption | Binary CRT stdin/stdout in host harness; literal newline-containing nonce preserved |
| Sdist omitted config/example | Explicitly include tracked config and `.env.example`; inspect tar/wheel contents and test extracted foundation inputs |
| Reopen retained partial frame/HELLO | Clear decoder/noise/HELLO on close and explicit reopen |
| Self-referential recheck/public constructor | Factory-only validated object; retain independent expected nonce/boot, recheck those before upload |
| Literal bool/int coercion | Require exact JSON assertion types; numeric/boolean adversarial tests PASS |
| Optimized Python bypassed recorder | Mandatory explicit checks; `python -O` rejection test and real build manifest recording PASS |
| Silent Linux C++ skip | Missing compiler fails Linux test; Windows absence is explicit skip |

The camera helper's real production algorithm runs against a synthetic queue backend
for fresh-buffer selection, malformed sizes/formats, absence and requeue failures.
The final patched adapter was rebuilt with the real ESP32-S3 toolchain. Firmware
source/build checks are separate from hardware timing. Driver timeout is not changed
globally: preserving the shared driver's behavior and unresolved fault recovery are
explicit installation HOLD items. No second review was requested after the tested pass.

Existing accelerated engine scenario:2880 cycles, virtual86400s,11 restart/restoration
checks, no violations/task growth/cloud requests. This is a virtual scenario, not another
real24h run and not a hardware observer endurance test.

## Hosted verification

Source391299eb518a7d3366520785787cf9d59ca5a03c:
[CI44169302639](https://github.com/rownlvh8875-coder/stackchan-autonomy/actions/runs/44169302639),
final attempt2 SUCCESS. Downloaded all four JUnit/soak artifacts and checked counts,
target cases and virtual86400s results; [machine-readable evidence](2026-11-17-usb-observer-ci.json).

| Platform | Full suite | Observer/GPT/MCP/CLI targets | Virtual soak / isolated wheel |
|---|---|---|---|
| Linux Python3.11 | 459 PASS | 155 PASS | PASS |
| Linux Python3.12 | 459 PASS | 155 PASS | PASS |
| Windows Python3.11 | 457 PASS,2 SKIP | 155 PASS | PASS |
| Windows Python3.12 | 457 PASS,2 SKIP | 155 PASS | PASS |

Windows skips are the existing unavailable system Opus/fork cases. Host C++ camera/
binary-wire tests ran successfully on Windows too. The extracted sdist's foundation
tests passed12/12, including packaged config inputs. Hosted CI does not build ESP32;
the separately recorded local IDF build is the device-toolchain evidence.

The first Windows3.12 attempt failed the existing live heartbeat test configured with
a1.5s TTL (456 PASS,2 SKIP,1 FAIL). The same unchanged commit passed the complete job
on retry. Exact scheduling/storage cause was not instrumented; this is an intermittent
timing assertion, not a demonstrated runtime fix. No lease timing or safety behavior
was changed to get a pass. Both the first failure and retry are retained in the CI run.

Build outputs
stay in the ignored local build directory with a NOT_APPROVED_FOR_INSTALLATION notice;
no binary release is published.

## What has not passed

No real camera/sensor/USB driver timing, DTR/RTS reset test, actual image API response,
official voice coexistence, service authentication compatibility, backup/restore or
hardware STOP/motion test occurred. Touch/IMU data are cached HAL enum events, not raw
measurements. Pose stays unknown. The upstream video driver can block on dequeue;
PC timeouts do not terminate that device operation. No auto retry or fabricated image.

The previously reported Windows24h result and GPT voice live PASS remain historical
evidence of their original scopes; they are not evidence of this observer's hardware
operation. See [installation HOLD and operator sequence](../USB_OBSERVER.ko.md).
