# VoiceApiPort ↔ K151 HTTPS/TLS stage bridge (2026-11-19)

**Compile and synthetic host tests only. Not approved for K151 installation.**

The previously separate `OfflineVoiceCycle` and `K151HttpsVoicePort` had overlapping
paid-stage enforcement. Their contract is now explicit:

1. `PersistentGuard::reserve` durably books a single conversation with all three
   potential paid calls before the first dispatch. `authorize_step` consumes a
   stage once in strict order, even if an HTTP call fails.
2. `OfflineVoiceCycle` emits an **ephemeral `DispatchPermit`** that is bound
   to exactly one stage and session epoch. This RAM-only ticket is NOT a new
   persistent budget reservation.
3. `BoundVoiceApiPort` validates the exact fixed endpoint, deadline, STOP,
   trusted clock, paid owner consent and the ticket; the trusted HTTP channel
   calls `consume_once` before the network socket is opened.
4. `K151HttpChannel` delegates that callback to the preexisting
   `K151HttpsVoicePort::post_once`, which already requires the fixed
   `api.openai.com:443` target, TLS certificate bundle, no redirect and
   no retry. Responses are routed to `K151VoiceDecoder`.
5. Typed STT text, completed GPT message text and PCM16 are accepted
   only after decoding and strict UTF-8/size/session/clock checks.

The new test `voice_api_bridge_test.cpp` injects synthetic data into a fake
HTTP port (no socket) and a fake decoder. It explicitly tests three-call
success, redundant dispatch denial, missing ticket, STOP, revoked paid
consent, late response, failure at each stage and time/consent preflight.
The existing cJSON and local HTTP request tests remain separate;
synthetic decoder bytes do NOT represent actual OpenAI payloads.

**Important limitations:** `app_main` references a compile-only marker,
never constructs `K151VoiceApiAdapter`. No device activation, Wi-Fi manager,
key provisioning, SNTP bootstrap, physical STOP interrupt or live API call.
The synchronous ESP-IDF HTTP adapter checks STOP between IO operations; it
does NOT prove subsecond cancellation or hard realtime latency.
The full 90s session budget still belongs to `OfflineVoiceCycle`.
No measured PSRAM/heap, reset recovery, live Korean STT/TTS or amplifier
playback has been demonstrated. No firmware flash, OTA, NVS write, fee-bearing
request, or `main` merge is authorized by these changes.
