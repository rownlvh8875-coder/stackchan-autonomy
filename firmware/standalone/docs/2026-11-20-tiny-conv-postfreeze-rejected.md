# 2026-11-20 — Frozen tiny CNN synthetic Korean holdout: rejected

**Final decision: NOT DEPLOYABLE. This is only a same-Heami TTS research experiment.**

## Verified order of operations

1. Host-only eight-filter temporal CNN was trained on 6 already known
   synthetic wake + 26 already known synthetic nonwake calibration utterances
   (five deterministic transformations each, NOT 160 independent recordings).
   No prior evaluation WAV was read during this training. Training setting
   650 epochs, learning step 0.30, L2 0.004, zero-logit decision.
2. The 1,423-byte `SKWC1` model and fixed training rule were **pushed to
   GitHub first** in commit
   [`92a3796`](https://github.com/rownlvh8875-coder/stackchan-autonomy/commit/92a3796).
   SHA-256 `3ed5d2aad7b933b62045c1c45e054a202bdf1b81da2fe7bd3dbd5bcd52c26cb5`.
3. **Only after this freeze** did the owner-authorized Windows Heami TTS engine
   create 4 new synthetic “조수야” and 12 new synthetic nonwake clips.
   One excessively slow-rate attempt exceeded the existing WAV duration
   contract and was discarded **before any classification**; the selected
   valid four calls were fixed independently of model results.
4. Unmodified original DTW, augmented DTW, previously frozen linear MFCC
   classifier, and newly frozen tiny CNN were compiled as offline host
   C++20 programs. Each received precisely the same new 16 WAV clips and
   deterministic gain/noise/single-echo perturbations. No method was tuned
   using the new evaluation output.

## Directly observed result (accepted / total)

All tests contain the same **4 wake** and **12 nonwake** base Heami clips.
Conditions reuse their waveforms; there are NOT 96 independent nonwake
recordings. “Nonwake accepted” is a false wake, which is undesirable.

| Condition | Original DTW wake /4 | Augmented DTW wake /4 | Linear wake /4 | CNN wake /4 | CNN nonwake falsely accepted /12 |
|---|---:|---:|---:|---:|---:|
| Clean | 4 | 4 | 4 | 4 | **3** |
| Half volume | 4 | 4 | 4 | 4 | **4** |
| Nominal Gaussian noise 20 dB SNR | 0 | 4 | 4 | 4 | **4** |
| Nominal Gaussian noise 10 dB SNR | 0 | 4 | 4 | 4 | **3** |
| Nominal Gaussian noise 5 dB SNR | 0 | 0 | 4 | 4 | **4** |
| Nominal Gaussian noise 0 dB SNR | 0 | batch rejected | 4 | 3 | **3** |
| Synthetic echo 80 ms | 0 | 1 | 4 | 4 | **3** |
| Synthetic echo 160 ms | 0 | 0 | 4 | 3 | **3** |

Nonwake comparisons for context:

| Condition | Original DTW nonwake wrong accepts /12 | Augmented DTW wrong accepts /12 | Linear wrong accepts /12 | CNN wrong accepts /12 |
|---|---:|---:|---:|---:|
| Clean | 1 | 1 | 4 | **3** |
| Half volume | 1 | 1 | 4 | **4** |
| Noise 20 dB | 0 | 1 | 5 | **4** |
| Noise 10 dB | 0 | 0 | 5 | **3** |
| Noise 5 dB | 0 | 0 | 5 | **4** |
| Noise 0 dB | 0 | no valid count | 5 | **3** |
| Echo 80 ms | 0 | 1 | 2 | **3** |
| Echo 160 ms | 0 | 0 | 3 | **3** |

**Observed conclusions:** the tiny CNN maintains more wake detections under
several synthetic noise/echo conditions than original DTW, but its high false
wake count (3/12 even in clean audio) makes it unsuitable for unattended
robot activation. The augmented DTW has fewer clean false accepts on this
particular set, although it misses more wake clips at high noise/echo.
No single candidate is approved. The 0dB augmented DTW batch was rejected
with **no valid group counts**; it must not be described as 0/12 false wakes.

## Reproduction and constraints

- `fixtures/korean_heami_conv_kws_20261120/conv-kws-frozen.skwc`: immutable
  model frozen *before* test samples.
- `fixtures/korean_heami_conv_postfreeze_20261120/`: 16 new synthetic WAVs,
  evaluation-only manifest, SHA256SUMS and this file's companion README.
- `tools/generate_conv_postfreeze_heami.py` (local Windows SAPI) and
  `tools/evaluate_conv_postfreeze.py` (host C++20, no network) reproduce
  synthesis and/or fixed model evaluation. Regenerated TTS clips may differ
  by installed voice engine revision; committed WAV hashes are canonical.
- `tests/test_conv_kws_postfreeze.py` validates SHA-256, counts, unchanged
  model, hardware isolation and Linux C++ end-to-end comparison.
- `app_main` remains HOLD. No flashing/OTA/NVS, GPIO/PMIC/I2C/I2S, live
  audio, servo, microphone, speaker or paid GPT/STT/TTS calls were performed.

The current dataset is **a single Windows Heami synthetic voice**, and
repeated perturbations are not independent. It cannot establish
real-human recognition, real false wakes/hour, speaker diversity,
physical room robustness, phone-level recognition, or ESP32-S3 latency,
memory/power and factory-recovery readiness.

**Recommendation:** reject this CNN for K151 deployment; further research
would need multiple real speakers and adversarial similar phrases, a
genuinely fresh holdout after training, and separate physical bench
verification. No change to the recorded outcomes to improve appearance.
