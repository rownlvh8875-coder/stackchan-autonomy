# K151 offline release blocker snapshot (2026-11-19)

Use `uv run --frozen python firmware/standalone/tools/readiness_snapshot.py` to inspect **repository source only**. The command does not access USB, serial ports, actual flash, audio, camera, Wi-Fi, OpenAI credentials, private factory backups or local system secrets.

The output is a read-only JSON checklist, not a release manifest or device installation permission. It validates six source-level invariants: hard-disabled physical output; hard-disabled DMA output driver; codec admission requires both gates; perpetual HOLD entrypoint; audio memory diagnostics cannot authorize flashing; and the `NOT_APPROVED_FOR_DEVICE_INSTALLATION.txt` marker. If source cannot be read or an invariant is broken, it returns nonzero with `SOURCE_UNAVAILABLE` or `BLOCKED_SOURCE_REGRESSION`.

Even with all source checks passing, status remains **NOT_APPROVED_FOR_DEVICE_INSTALLATION**, and missing physical proofs are listed: independent factory restores, active OTA slot, exact board/I2C identity, AXP2101 rails, AW9523 reset, AW88298 hard mute, measured physical STOP, DMA/codec drain telemetry, actual microphone sample clock/voice recognition, measured RAM usage and explicit approved installation. Those facts are not established by a successful unit test or compile-only CI build.

This tool does not accept human-edited true/false flags that could mark the device as ready. No factory images or personal paths appear in the report. Device-side setup and any hardware probing remain blocked pending separate verified prerequisites.
