# Standalone voice heap/PSRAM headroom preflight (2026-11-19)

Status: **STATIC/SYNTHETIC POLICY ONLY; NO LIVE K151 HEAP MEASURED**.

The current bounded audio pipeline can retain the **8-second, 24 kHz mono PCM16 question** (192,000 samples = 384,000 bytes) while simultaneously receiving the **20-second synthesized PCM16 reply** (480,000 samples = 960,000 bytes). The known theoretical peak is **1,344,000 raw PCM bytes**, excluding capacity growth in `std::vector`, codec DMA, network TLS, response JSON, application stacks, MFCC features and other transient buffers.

`core/audio_memory_admission.hpp` records these source-derived sizes and a conservative **policy** requiring 512 KiB additional PSRAM free beyond raw PCM, 128 KiB beyond the largest TTS contiguous block, at least 128 KiB internal free and at least 32 KiB contiguous internal allocation. These policy thresholds are **not measured requirements of the customer's K151** and do not prove `std::vector` uses PSRAM. The gate reports "not measured" or "allocator unverified" unless real measurement, allocator placement and simultaneous-peak observations are independently provided.

Even if all hypothetical measurements pass, the result is `diagnostic_budget_satisfied_not_install_approval`; compile-time `kAudioMemoryReadinessCanAuthorizeInstall=false` cannot be overridden. Tests are all synthetic. A future hardware test must instrument actual heap/PSRAM allocation and fragmentation under real STT/TTS traffic, measure failure handling, and independently prove backup restoration and physical mute/STOP before any device installation. The HOLD `app_main` only includes the header; it performs no heap probe, cloud call or hardware action.
