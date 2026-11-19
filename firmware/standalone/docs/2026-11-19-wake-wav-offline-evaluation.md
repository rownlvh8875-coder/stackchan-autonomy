# K151 '조수야' — offline WAV wake evaluation (2026-11-19)

**STATUS: PRIVATE HOST EVALUATION ONLY. NO REAL KOREAN RECOGNITION RESULT / NO HARDWARE / NO FLASH / NO PAID API.**

## Purpose

The portable C++20 tool `tools/wake_wav_eval.cpp` runs the **same** `core/wake_features.hpp` MFCC/DTW matcher as the existing experimental standalone runtime. It reads a *pre-existing, privately held* `SWK1` enrollment profile and owner-labeled WAV recordings of positive (wake phrase) and negative (other words/noise) samples, reporting only aggregate accepted counts.

- WAV input must be canonical RIFF/WAVE, uncompressed integer PCM16, **24,000 Hz, mono**, between **0.1 and 3 seconds**. Other formats, truncated files, malformed/oversized RIFF chunks and duplicate PCM samples are rejected.
- The `SWK1` profile must have a valid CRC, feature count and calibrated threshold. The evaluator does **not** create the profile, record the microphone, calibrate from samples, upload files or write to devices. A separate reviewed procedure must produce and retain SWK1 privately.
- The user must label positive and negative recordings correctly and keep training/holdout/test samples separate. Duplicate PCM is rejected, but this cannot detect re-recordings of the same utterance, relabeling, or data leakage.
- At least one positive and one negative WAV is necessary to run a local smoke evaluation; that **does not** constitute statistically meaningful Korean wake-word performance.
- Output contains only aggregate counts, e.g. `positive_accepted=1/1` and `negative_accepted=0/1`. This means **one user-labeled example**, not a recognized Korean word or a measured false-wake rate per hour.

## Build on a private machine with C++20 GCC

```bash
g++ -std=c++20 -O2 -Wall -Wextra -Werror -pedantic \
  -Ifirmware/standalone/core \
  firmware/standalone/tools/wake_wav_eval.cpp \
  -o wake_wav_eval

./wake_wav_eval PRIVATE.swk1 \
  --positive PRIVATE_POSITIVE_24k.wav \
  --negative PRIVATE_NEGATIVE_24k.wav
```

Repeat the `--positive FILE` and `--negative FILE` pairs for more samples. Keep all private recordings and `SWK1` files **outside Git**, CI and public cloud storage. The program neither creates output files nor echoes input file paths. The input file itself and parsed PCM are necessarily read into local memory for the comparison.

The Python test `tests/test_wake_wav_eval_build.py` generates **synthetic 520Hz/900Hz tones** in a temporary directory, compiles both the parser and evaluator with GCC C++20, and tests the accepted/rejected/duplicate paths. Passing this proves the parser and code path on a host compiler only.

## Acceptance still outstanding

The requested Korean phrase `조수야` must be tested using **actual recordings**, independent negative/environment samples, different speakers/distances and playback-echo trials. The exact K151 mic timing, TDM channels, calibration, false-wake frequency and CPU/PSRAM behavior are not tested here. Never report a synthetic 520Hz tone as Korean speech recognition. This tool does **not** authorize device installation, firmware/OTA update, credential access or paid STT calls.
