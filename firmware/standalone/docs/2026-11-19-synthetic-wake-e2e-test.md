# End-to-end synthetic wake → microphone → GPT/TTS host regression

This change tightens `tests/voice_turn_coordinator_test.cpp`: instead of calling `Session::wake()` directly, the test now creates one synthetic 24kHz PCM waveform, extracts a feature with the real `wake_mfcc_from_24k()` implementation, stores its encoded profile in fake persistent storage, and invokes `WakeVoiceEntry::detect()`. Silence must be ignored before the synthetic feature is accepted.

All existing fake microphone / `AudioGuard` / question-end / STT → Responses → TTS / guarded-speaker error tests then use the **detected wake session epoch**. This tests more of the offline application chain without contacting K151 hardware or OpenAI.

**Accuracy scope:** a generated 520Hz tone is not a Korean "조수야" recording. Matching a feature to the identical synthetic waveform is not evidence of speech recognition accuracy, false-wake performance or speaker authentication. The firmware remains in perpetual HOLD; no microphone, amplifier, servo, flash or paid API request is performed.
