# Off-device STT → Responses → PCM speech orchestration

**NO real HTTP, TLS, microphone, amplifier, OpenAI account, API key or paid calls.**
The `core/offline_voice_cycle.hpp` class is a deterministic C++20 host contract.
It uses the existing `Session` epoch/deadline state machine and
`PersistentGuard` to reserve three possible billed API stages *durably before*
the first fake dispatch. Each stage's permit is one-shot and never refreshed on
failure, STOP or reboot. No automatic retries or provider fallback are present.

The fake port sees fixed endpoint identifiers:
- `/v1/audio/transcriptions`: 24kHz PCM16 mono, <=8s, language `ko`
- `/v1/responses`: 400 output tokens, `store=false`, <=500 Unicode
  characters in the synthetic transcript
- `/v1/audio/speech`: PCM output, <=300 Unicode characters in the
  synthetic answer and <=20s/480,000 PCM16 samples in the fake reply

The simulator validates model/voice identifiers, rejects malformed UTF-8,
strictly bounds text and audio sizes, enforces no additional request after
a late/failing/STOP response and requires an explicit owner paid-consent latch,
a trusted SNTP latch, and an explicitly enabled Session (defaults OFF).
Both the fake cloud and fake speaker provide *typed, already parsed* results.
They do not build multipart WAV or JSON requests; HTTP response streaming,
content-length, chunked framing, TLS certificate/time verification,
model-specific schema parsing, acoustic VAD and interruptible I2S playback
are **NOT implemented**. The ESP32 application only links a compile marker;
it does not construct a voice cycle or call any remote endpoint.

The host test exercises: success, three individual API failure stages,
STOP after each async mock boundary, late timeout, transcript/answer/PCM
overflow, invalid UTF-8, missing consent, untrusted time, cloud OFF,
oversized input, speaker error and stop during playback. Synthetic data only.
Run `python -m pytest -q firmware/standalone/tests/test_offline_voice_cycle_build.py`.

This is a first integration seam, **not** a device-ready GPT voice firmware.
No flash, audio/NVS mutation, credentials, network or paid traffic permitted.
