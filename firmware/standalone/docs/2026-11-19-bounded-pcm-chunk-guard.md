# Bounded 24kHz PCM output / cancellation contract (2026-11-19)

Status: **NO HARDWARE ACCESS / HOST TESTED ONLY / HOLD FIRMWARE**.

## Code changes

- `core/pcm_chunk_guard.hpp` adds a deterministic, portable 24 kHz PCM16 frame writer with <=240 samples per synchronous call, <=480,000 total frames (20s), monotonic-time validation, a 25s admission deadline, and STOP/owner-consent checks before and after every write. It rejects overlong PCM, failed writes, clock rollback/invalid time, and overruns without retry or accepting a partial result.
- `esp_app/main/k151_pcm_speaker_sink.hpp` delegates each chunk to the guard. The codec itself remains *hard disabled* by `kK151PhysicalOutputEnabledInHoldImage=false`, and `app_main` never constructs the sink.
- `tests/pcm_chunk_guard_test.cpp` exercises 241/481 sample boundaries, STOP and consent races, failed write, deadline expiry, nonmonotonic clock, empty/oversize and overflow input. All audio data is synthetic.

## Important limits

An `esp_codec_dev_write` success does **not** mean physical DMA drained, analog output ended, or the amplifier is safely muted. A single blocked synchronous write cannot be preempted by this helper; physical STOP latency remains unmeasured. The existing `DmaDrainLedger` and audio HOLD hard gates remain in force.

The caller must supply a monotonic `started_ms` from the same time base as `esp_timer_get_time()/1000`; UTC timestamps are invalid. The 25s timeout is a policy guard, **not a measured 25s real-time STOP bound**. No device flashing, API billing, NVS mutation, power action, or actual audio output was performed.
