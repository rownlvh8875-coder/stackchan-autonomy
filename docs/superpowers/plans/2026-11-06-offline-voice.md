# Offline Voice and Audio Implementation Plan

> Execute inline with test-driven-development and a fresh final read-only review.

**Goal:** Explicit touch/voice trigger → simulated Korean transcription → existing
autonomy decision/safety/action → simulated PCM playback, plus consent-gated OpenAI
audio adapters and independently tested WAV/PCM/Opus conversion.
**Spec:** User approved the recommended offline voice-adapter/audio-conversion next step;
docs/DEVELOPMENT_BRIEF.md and docs/NEXT_STEPS.md describe Phase 5.
**Base:** e9e5c561fed7be1d90f673a8fe720ce77a091c9e; local branch feat/offline-voice.

## Architecture / constraints
- Reuse current checkout; no worktree, publication or unrequested push.
- Keep physical microphone, speaker, motors and cloud audio disabled by default.
- PCM16Audio is bounded signed-16-bit little-endian mono/stereo; WAV parser uses
  actual headers. Normalize to 16kHz mono with antialias filtering before playback.
- OpenAI STT uses in-memory WAV; TTS requests documented raw PCM (24kHz mono s16le).
  Model/voice IDs are explicit settings, not hardcoded model names.
- Reserve persistent shared API budget before STT/TTS; no automatic retry/refund.
- Native libopus is optional (system library, not redistributed), 16kHz mono 60ms
  packets per audited gateway. Missing codec disables only Opus, never fakes success.
- No raw media/transcript in logs, SQLite, files or unbounded histories.
- Fake ASR uses a fixture transcript; fake TTS is a tone, not Korean speech quality proof.
- Gateway listen already performs STT; raw microphone/Opus capture is not a public MCP
  contract. Actual /pcm transport/auth and hardware remain blocked; prepare payloads only.

## Review focus
Media bounds/alignment, WAV truncation, endianness and aliasing, native codec lifetime,
consent and shared quota, STOP during capture/STT/synthesis/conversion/playback,
lease loss while listening, duplicate recording and task cleanup, private error text.

## Tasks
1. [x] Verify official audio docs/SDK and audited gateway constants; add failing audio
   tests then implement audio.py and optional opus_codec.py with bounded round trips.
2. [x] Add failing SDK MockTransport STT/TTS consent/budget/error/size tests; implement
   cloud_audio.py using explicit model/voice settings and streaming response limits.
3. [x] Add failing manual-trigger/STOP/lease-loss tests; implement voice.py ports,
   fake microphone/ASR/TTS/playback, speaking-robot decorator and conversation lifecycle.
4. [x] Add voice-sim CLI tests and wire bounded explicit-trigger demo; optionally encode
   Opus when --opus requested. Preserve prior mock/cloud/mcp-sim summaries.
5. [x] Full tests/Ruff/build/wheel smoke, fresh read-only review, regression fixes,
   updated README/VOICE.md/TEST_REPORT/WORK_LOG. Do not claim real hardware/cloud quality.

## Interfaces
- PCM16Audio(pcm, sample_rate, channels), from_wav/to_wav, normalize_pcm(target_rate=16000).
- encode_opus(audio) -> OpusFrames; decode_opus(frames) -> PCM16Audio, lossy with codec delay/padding.
- OpenAIAudioService.transcribe(audio, language='ko') -> str; synthesize(text) -> PCM16Audio.
- RecordedVoiceInput.listen(language,duration_ms) -> Event(VOICE_REQUEST).
- SpeakingRobotAdapter.execute(RobotCommand) normalizes/synthesizes speak; other commands delegate.
- VoiceConversation.handle(Event) -> ActionResult; rejects timer, serializes recording,
  watches engine stop/lease loss; no always-on capture. CLI --mode voice-sim --event touch.
