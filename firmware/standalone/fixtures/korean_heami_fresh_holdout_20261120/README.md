# Korean Heami fresh evaluation — generated AFTER development recipe freeze

**SYNTHETIC SAME-VOICE TTS ONLY / NOT REAL SPEECH / NEVER DEPLOY.**

This folder contains 16 **new** Microsoft Heami Desktop (Windows SAPI ko-KR)
synthesized WAVs created **after** the experimental preprocessing, template
augmentation, calibration gates, and fixed SWK1 hash had already been committed
in `5cd043f`. The data was not opened by the development/calibration script.

- `evaluation/fresh_01.wav` … `fresh_16.wav`: 4 new "조수야" rates (-6, -5, 5, 6) and 12 new competing Korean phrases. All 24kHz mono PCM16.
- `fresh-evaluation.wake-corpus.json`: only `stage=evaluation` entries and user/algorithm-declared labels.
- `robust_trim_aug_frozen.swk1`: **experimental host-only** profile created from the OLD enrollment/calibration examples. Three MFCC templates; SHA-256 `b0231cbe83f5dccdb0adc129ccb4ec899f410abcb83d50007c51247a3b7f7aec`. Not a certified biometric profile.
- `SHA256SUMS.txt`: binary hash integrity list for the 18 assets, bytes preserved across platforms.

The published **baseline profile** is in the older `korean_heami_sapi_20261120` directory. Compare the frozen experimental profile against that profile with `tools/evaluate_fresh_frozen_heami.py`.

**Rights:** these WAV files were generated with Microsoft Windows built-in speech technology. Separate rights to redistribute the synthetic speech content were not independently verified, and the source MIT license is **not** an independent license grant for those WAVs. No real human speech, paid API data, user secrets or model voice engine binaries are included.

## One-shot observed result (same TTS voice; not human validation)

| Condition | Baseline: wake / 4 | Experimental: wake / 4 | Baseline nonwake accepted / 12 | Experimental nonwake accepted / 12 |
|---|---:|---:|---:|---:|
| Clean | 4 | 4 | 2 | 2 |
| Half gain | 4 | 4 | 1 | 2 |
| Synthetic Gaussian noise 20dB | 0 | **4** | 0 | **4** |
| Synthetic Gaussian noise 10dB | 0 | **4** | 0 | **1** |
| Synthetic Gaussian noise 5dB | 0 | 0 | 0 | 0 |
| Synthetic Gaussian noise 0dB | 0 | **whole batch rejected** | 0 | **no counts** |
| Synthetic echo 80ms | 2 | 2 | 0 | **1** |
| Synthetic echo 160ms | 0 | 2 | 0 | 0 |

**Verdict: NOT ADMISSIBLE FOR K151 INSTALLATION.** Wake detections under moderate
synthetic noise improved, but false accepts on competing Korean phrases are
unacceptable: 4/12 at 20dB, 1/12 at 10dB, and 2/12 even on clean audio.
The new input set was generated after freezing the algorithm; however it is
the SAME TTS speaker and is too small for population-level recognition/false
wakes per hour. It is now exposed and **must not be reused as an independent
holdout to tune a future candidate**.

No K151 flashing, NVS, microphone, servo, speaker, power rail or paid API call
was executed.
