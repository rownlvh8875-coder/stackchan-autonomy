# Reconnected K151: current ROM metadata and dormant asset admission

2026-11-20, same feat/wakeword-josu / PR #3, source basea6488de.
User reconnected USB; this follow-up supersedes the initial absent-device PnP
observation. Installation and real paid API approval are still absent.

## Direct Windows device observations

- Present COM3, VID303A/PID1001, USB JTAG/serial debug unit, statusOK. Bluetooth
  COM7 was excluded. No running Python/esptool/MCP/serial-terminal process was
  found; this is process inspection, not a universal kernel-handle ownership proof.
- The first no-reset ROM query failed, without a reported port-busy error.
  One explicit usb-reset then succeeded: ESP32-S3 QFN56 rev0.2, Secure Boot
  Disabled, Flash Encryption Disabled. ROM/no-stub flash-id reported16MB.
- Read only4096bytes at0x8000 and8192bytes at0xD000. NVS was not read and the
  16MB flash was not reread. Both regions exactly match the hash-verified original
  factory-a snapshot. The parser verified the baseline SHA/partition MD5 first.
- Current OTA records seq1/seq2 are VALID with correct CRC; both rollback-policy
  interpretations nominateota_1. This is a current metadata snapshot, not a
  running-slot, bootloader-fallback or safe-spare proof. seq_label was not printed.
- The final no-reset query with after=hard-reset returned0 and reported hard reset
  toward flash boot. COM3 reappeared OK. Actual factory face/menu return requires
  physical observation; no screen/voice/API success is inferred from PnP.

Two intentional chip resets occurred (ROM entry and return to flash boot).
No flash write/erase, NVS/partition/eFuse modification, RAM stub upload, motor
command, new microphone capture, audio file, model inference or real API call was
performed. Raw metadata stays in a new ignored local directory; only sanitized
facts are published in [the JSON record](2026-11-20-k151-current-usb-and-assets.json).

## Model preparation now uses actual local partition evidence

Added `K151WakeNetPort::prepare_local(owner, stop)` and a small IDF-backed verifier.
It requires main-flash DATA labelmodel at the draft0xF00000/1048576byte region,
unencrypted and readonly. Missing/wrong/external/writable/encrypted partitions
reject before hashing or SDK startup. The original table has no model partition,
so the connected robot is not provisioned for this path.

The verifier calls IDF `esp_partition_get_sha256` over the **entire DATA partition**.
The pin is the verified292607byte ESP-SR2.4.7 model pack plus0xff to1MiB:

| Scope | SHA256 |
|---|---|
| Actual packed model292607bytes | `0255855e56bf72d1e072d2e0cbee4fb3ce1ac2c48f7fee6c8cd591f83e59ed95` |
| Padded readonly model partition1048576bytes | `1d04bf6a1f6775d43ab4398bbbac1bc4606f5c4130fe1a853851ec5df7f21d1b` |

The offline packer now verifies/reports the padded digest as well. It does not
write a device or create a partition table. Recomputed the real local public pack
digest to verify the pin. Prefix-only SHA or arbitrary tail contents cannot pass
the target whole-partition check. SHA/partition C ABI doubles test control flow;
they do not execute IDF hashing or prove target neural inference.

Owner/STOP are checked around partition lookup/hash and SDK setup, including
before allocating the model. Revocation after allocation closes the context and
model list. Failed local verification latches the object against both local and
legacy bool entry points; close() cannot clear it. Existing SDK single ownership,
terminal cleanup, exact model/mode/format and wake PCM wipe remain intact.

The linked marker retains the new preparation path under target linker GC but
does not invoke it. app_main remains HOLD. Real model allocation admission,
model-resident allocator/TLS/TTS measurements, trusted owner UI wiring and physical
audio/STOP/drain still gate any future operational bootstrap. The readonly flag
is an SDK write restriction, not protection against arbitrary raw flash writers;
bootstrap must remain exclusive with no OTA or other raw flash writer.

## Validation

17 initial host cases failed for absent implementation, then SDK44PASS. Two new
packer tests failed for absent partition digest, then packer5PASS. One fresh
read-only review found an Important legacy-path lifecycle bypass. Added a failing
bad-SHA→legacy test and two stricter owner/STOP-during-SDK tests:3FAIL. Fixed via a
private shared allocator helper, with live atomic checks around SDK callbacks.
Post-fix focused SDK/native-wake/packer101PASS. No second review was run.

Root495PASS2SKIP was run on this Windows notebook. Initial standalone421PASS5SKIP
preceded the review correction; final post-review standalone **423PASS5SKIP** in
87.03s and focused101PASS, Ruff335files and project diff PASS. Actual new target
CI is recorded on PR #3 after completion. Actual device inference
and an independent GPT turn remain untested. Do not use HOLD size as operating RAM.

The previous exact code heada6488de remains **7/9 CI success**, not green:
[push44752454968](https://github.com/rownlvh8875-coder/stackchan-autonomy/actions/runs/44752454968)
2/4; [PR44752464762](https://github.com/rownlvh8875-coder/stackchan-autonomy/actions/runs/44752464762)
4/4; [S3 build44752464683](https://github.com/rownlvh8875-coder/stackchan-autonomy/actions/runs/44752464683)
PASS. [Numeric CI record](2026-11-20-windows-ci-a6488de.json).
Failed Windows3.12 renewal was interrupted in SQLite COMMIT (max5.613439s;
loop lag53.1832ms, executor wait3.0695ms), narrowing this failure to a storage API
stage without separating disk I/O from worker OS descheduling. Windows3.11 passed
soak but timed out in the second installed-wheel Mock GPT/MCP wait; same-head PR
and one local Python3.11.9 installed-wheel check passed. That second cause remains
unresolved. No failed job was rerun and no safety limits were increased.

Primary API contract: pinned IDF
[esp_partition_get_sha256](https://github.com/espressif/esp-idf/blob/fff9895c82d744c7237be8847347bdd1b07c6643/components/esp_partition/include/esp_partition.h)
documents whole-data-partition hashing. Draft geometry is subject to the
[installation/restore review](../K151_NATIVE_INSTALL_PREP.ko.md); no table or image
here authorizes installation.
