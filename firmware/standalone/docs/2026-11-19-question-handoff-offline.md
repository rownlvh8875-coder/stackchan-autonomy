# Completed-question to GPT handoff — offline proof only

The `WakeVoiceEntry::answer_captured` method connects `QuestionCapture` to the already implemented budget-guarded STT → Responses → TTS cycle. Dispatch is refused unless recording has completed, the session is in `record` and its exact wake epoch matches, STOP and playback are inactive, and owner consent is still present. On an attempted completed handoff, the retained PCM is zeroed and removed whether the response succeeds or fails; an old completed utterance cannot be replayed.

`QuestionCapture::push` also invalidates a previously ready buffer when a late STOP or playback signal arrives. The host tests cover unfinished capture, wrong epoch, successful three-stage fake exchange and late STOP. Tests are synthetic; they do not recognize Korean speech or run actual I2S, Wi-Fi, API, codec, amplifier, or servo hardware. ESP32-S3 entrypoint remains HOLD/compile-only, and existing factory firmware is not changed.

Before an actual deployment: provide a real calibrated microphone capture/VAD adapter with correct clock/format, verify stop-latch concurrency and storage lifetime, prove independent factory recovery, and obtain explicit device installation authorization. Never interpret compile-only success as a safe flash candidate.
