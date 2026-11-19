# Offline question capture checkpoint — 2026-11-19

Status: **HOST TEST ONLY / NO MICROPHONE / NO LIVE VAD / NO FLASH**.

The portable `QuestionCapture` accepts fixed 480-sample PCM16 mono frames at an assumed 24kHz. Three consecutive above-threshold frames start the capture (60ms); twenty-five consecutive below-threshold frames finish it (500ms). Silence tail is discarded and captured audio is available only in the `ready` state. A malformed frame, STOP, speaker playback, or more than 8 seconds of captured/waiting frames fails closed and zeroes retained audio. Reset explicitly clears the buffer.

The RMS threshold is a **fixed, uncalibrated energy heuristic**, not voice recognition. Quiet speech, high background noise and false starts can cause errors. The mock test exercises synthetic constant-value frames, not microphone input or the Korean wake phrase. A real capture driver must apply proper acoustic gating, owner consent, actual STOP, rate/channel verification, sample clock validation, echo control and model calibration. It must hand off the `ready` buffer to `WakeVoiceEntry::answer` only when the correct session epoch is active and question-start callback has succeeded.

The ESP-IDF `app_main` only includes this header for build visibility. Startup remains in a perpetual HOLD loop with no I2S, Wi-Fi, actuator or paid API activity. This checkpoint does not approve installation, NVS modification or physical tests.
