# 2026-11-19 standalone HTTPS request/response step — NO DEVICE INSTALL

Status: compile-only ESP32-S3 adapter + offline host/network-loopback fixtures.

Official API sources reviewed:
- https://developers.openai.com/api/reference/resources/audio/subresources/transcriptions/methods/create
- https://developers.openai.com/api/reference/resources/responses/methods/create
- https://developers.openai.com/api/reference/resources/audio/subresources/speech/methods/create
- https://developers.openai.com/api/docs/guides/text-to-speech
- https://docs.espressif.com/projects/esp-idf/en/release-v6.1/esp32s3/api-reference/protocols/esp_http_client.html

Scope: 24kHz mono PCM16 WAV + multipart STT request, bounded JSON Responses with store=false, PCM TTS 24kHz little-endian, strict 200/media/Content-Length/stream completion and length limits, no automated retry, fixed api.openai.com:443 endpoint with certificate bundle/hostname verification, redirect disabled, and one-shot persisted paid-stage permit requirement. ESP-IDF v6.1 cJSON is an explicitly pinned managed component; transcription text and completed assistant output_text only are eligible for use. Wrong schema, duplicate fields, refusal, tool-call response, invalid UTF-8 and incomplete output are rejected. Untrusted response bodies and API keys are never emitted to logs by this implementation.

Tests: portable C++ body/response fixture, Python JSON check and 127.0.0.1 HTTP server request roundtrip, native cJSON parser tests on Linux. The local fixture is intentionally **plain HTTP to localhost** and does not prove ESP32 TLS correctness. CI compile proof is separate from host tests.

Limits: 8s PCM upload, 500-character STT transcript, 400 requested GPT output tokens and 300-character reply, 20s/960kB PCM output, 256KiB max JSON body, 30s per API call; hardware/overall session budget remains in existing Session/PersistentGuard code. Model names and speech voices are not enabled on device. Deprecated Speech API models are scheduled to retire Jan 6 2027; no automatic fallback to Live/Realtime exists.

WARNING: The new network and JSON sources are compile-only. HOLD app_main links markers but does not construct or invoke this transport. No actual HTTPS/API, verified clock lifecycle, credential provisioning, 24h real runtime, ESP32 memory/PSRAM test, hardware audio, electric STOP, NVS write, flash/OTA or GPT playback is claimed. Only a separately approved, recovery-validated physical test can clear these HOLD items.
