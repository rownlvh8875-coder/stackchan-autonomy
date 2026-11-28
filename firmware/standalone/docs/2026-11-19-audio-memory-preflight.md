# Standalone voice heap/PSRAM headroom preflight (2026-11-19)

Status: **STATIC/SYNTHETIC POLICY ONLY; NO LIVE K151 HEAP MEASURED**.

The question (384,000 bytes of 24 kHz mono PCM16), speech response body
(960,000 bytes), and decoded playback PCM (960,000 bytes) can overlap during
speech decoding. Their payloads total **2,304,000 bytes**. Vector capacity,
codec DMA, TLS, JSON and other runtime allocations add to that total.

`core/audio_memory_admission.hpp` sets a policy threshold of **2,828,288 bytes**
free PSRAM (the three payloads plus 512 KiB), 128 KiB beyond the largest speech
buffer for contiguous PSRAM, at least 128 KiB free internal memory and at least
32 KiB contiguous internal memory. Admission still requires measured heap,
allocator placement and a combined peak with the model resident.

The separate [resource bench](../../../docs/K151_RESOURCE_BENCH.ko.md) measures
heap during synthetic response decoding. TLS handshake, network and codec peak
remain separate measurements. The policy returns
`diagnostic_budget_satisfied_not_install_approval` when the diagnostic thresholds
pass. The operating app remains in HOLD.
