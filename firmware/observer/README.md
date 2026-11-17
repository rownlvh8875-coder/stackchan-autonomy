# Experimental official-source USB observer

**COMPILE/TEST ONLY — NOT APPROVED FOR DEVICE INSTALLATION.** No installer is provided.
Source rebuilds may lose official service/app compatibility; backup/restore, board/LCD/
USB routing, camera driver recovery and exact-image approval remain unresolved.
See [operator HOLD and later procedure](../../docs/USB_OBSERVER.ko.md).

`core/` is the portable production SCOB codec/dispatcher and fresh-frame lease helper.
`esp/` uses HAL cached events, isolated quiet camera capture and native USB Serial/JTAG. Only HELLO,
STATUS and SNAPSHOT exist. No actuator API is called. Unknown pose remains null.
The feature defaults off and rejects USB console sharing and camera DEBUG hexdumps.
The existing official firmware can still move hardware during startup/AI operation.

## Source and toolchain pins

All six Git dependencies and the official source/ESP-IDF are pinned in
[`dependencies.json`](dependencies.json); managed packages use upstream
`firmware/dependencies.lock`. The original xiaozhi patch is applied before our narrow
conditional camera-access patch. Observer capture never replaces the stock retained frame.
No private auth files or uploaded user secrets are build inputs. See [NOTICE](NOTICE.md).

Use a **new scratch directory**, outside any deployed checkout:

```bash
uv run --frozen python scripts/fetch_observer_sources.py .local/observer-build/upstream
```

The script prepares source only and refuses existing destinations. For an already
fetched exact clean official tree with dependencies, `scripts/prepare_observer.py`
applies the same integration patch; it refuses a second installation of the source patch.

Install/export ESP-IDF v6.1, exact commit `fff9895c82d744c7237be8847347bdd1b07c6643`,
with ESP32-S3 tools. The recorded Linux build used GCC15.2.0_20251204, CMake3.31.6,
Ninja1.13.0 and an isolated IDF Python environment. Preserve the upstream defaults.
Create `firmware/sdkconfig.defaults.local` in the scratch tree with:

```text
CONFIG_ESP_CONSOLE_UART_DEFAULT=y
CONFIG_ESP_CONSOLE_SECONDARY_NONE=y
CONFIG_STACKCHAN_PC_OBSERVER=y
```

Then compile without connecting any device:

```bash
idf.py -C .local/observer-build/upstream/firmware build
```

ESP-IDF prints suggested installation commands after a successful build. **Do not run
them.** They are tool-generated suggestions, not project approval or an operator step.
Artifacts remain local; no firmware binary release is published.

Record exact source/config/lock and output hashes after a successful compile:

```bash
uv run --frozen python scripts/record_observer_build.py .local/observer-build/upstream --idf /path/to/pinned/esp-idf --output .local/observer-build/manifest.json
```

The recorder requires the pinned source/dependency heads, exact adapter/core bytes,
enabled observer/isolated USB, compiled source entries and a real Xtensa ELF. It writes
an adjacent `NOT_APPROVED_FOR_INSTALLATION.txt`. Rebuilding under another absolute path
or build date may produce different binary hashes; source/toolchain pins are reproducible
inputs, not a claim of byte-identical builds across machines.

## Verification boundaries

```bash
uv run --frozen pytest -q tests/test_observer.py tests/test_observer_firmware.py tests/test_gpt_observe.py
```

Host C++ tests compile/run the same core with a synthetic camera backend. Python tests
use literal CRC packets, real local sockets, Pillow, actual MCP/WebSockets and the
Responses SDK with MockTransport. A host pass is never called an ESP32 build or a
physical camera test. Installed-wheel checks run outside the source directory.
Linux CI requires g++; other platforms explicitly skip host core tests without it.

The worker has bounded request buffers/USB writes and a nonblocking frame-lock attempt.
Supported configuration is the pinned K151 DVP with exactly one buffer and packed
supported raw format (no rotation/endian-transform configuration). Capture discards and
requeues the outstanding buffer, then leases the next, with a conservative timestamp
before requeue. Null/short/oversized/error buffers and requeue failures are errors;
format/row/length validation precedes conversion. It never writes `frame_`, joins the
stock encoder or changes shared driver timeout/stream configuration. The dequeue has
no proven hard real-time bound; PC timeout does not cancel it.
Real driver fault recovery and voice coexistence are installation HOLD
items, not promises established by this build. Touch/IMU event callbacks only cache
values; existing subscribers remain installed.
