# 2026-11-20 — Frozen experimental wake profile: new Heami synthetic holdout

**OFFLINE EXPERIMENT / HARDWARE REJECTED / NOT REAL HUMAN SPEECH ACCURACY**

## 1. Why this test has a new group

The earlier baseline experiments had already exposed and analyzed the first 2 wake / 6 nonwake evaluation clips. We therefore did NOT use those clips to select trim thresholds or augmentations. The source code for the *new* energy trimming and three-template candidate was committed to [`5cd043f`](https://github.com/rownlvh8875-coder/stackchan-autonomy/commit/5cd043f) **before** generating these fresh synthetic clips.

The candidate SWK1 file was generated **only from the pre-existing 1 enrollment clip + 5 calibration wake + 10 calibration nonwake**. It is pinned to SHA-256:
`b0231cbe83f5dccdb0adc129ccb4ec899f410abcb83d50007c51247a3b7f7aec`.

A separate subsequent generation produced 4 "조수야" clips at SAPI speech rates **-6, -5, 5, 6**, and 12 phonetic-neighbor nonwake clips. Both baseline and experimental matcher used the SAME new utterances under the SAME deterministic waveform perturbations.

**All input was Microsoft Heami Desktop ko-KR synthetic TTS from the same software voice, not recordings from different humans.** Generating them at a later time reduces code/evaluation leakage but does not make the samples statistically independent of the training voice.

## 2. One-shot local observed values

The baseline is the published one-template SWK1 with original unmodified MFCC/DTW. The experimental candidate uses three templates (clean / 20dB synthetic noise / 80ms echo) and a host-only optional energy trim. Each row reuses the same **4 positive and 12 negative** base clips under a deterministic perturbation. The 8 conditions are not independent observations.

| Condition | Baseline wake accepted / 4 | Experimental wake accepted / 4 | Baseline nonwake accepted / 12 | Experimental nonwake accepted / 12 |
|---|---:|---:|---:|---:|
| Original clean | 4 | 4 | **2** | **2** |
| Half amplitude | 4 | 4 | **1** | **2** |
| White noise 20dB nominal RMS SNR | 0 | **4** | 0 | **4** |
| White noise 10dB nominal RMS SNR | 0 | **4** | 0 | **1** |
| White noise 5dB nominal RMS SNR | 0 | 0 | 0 | 0 |
| White noise 0dB nominal RMS SNR | 0 | **whole batch fail-closed** | 0 | **no counts** |
| Single reflection 80ms | 2 | 2 | 0 | **1** |
| Single reflection 160ms | 0 | **2** | 0 | 0 |

The 0dB experimental run **returned an error without usable aggregate counts**; it must never be misreported as 0/12 false detections.

## 3. Conclusions

1. **Wake detection improved** for this same-voice TTS holdout at nominal 20dB and 10dB noise (0/4 → 4/4), and for one 160ms echo condition (0/4 → 2/4).
2. **False wake detection worsened**, including clean speech (2/12) and nominal 20dB noise (4/12). The original candidate already false-triggered 2/12 clean new clips; the initial smaller 0/6 result was not sufficient to expose this.
3. This experimental candidate is **NOT ADMISSIBLE FOR HARDWARE INSTALLATION**. The exact test results must remain as recorded. Do not change the candidate threshold or template recipe to make this now-exposed evaluation set look better.
4. The algorithm remains fragile at nominal 5dB and 0dB SNR, and the 80ms echo scenario had no improvement. No population-level accuracy, false alarms/hour, speaker recognition, wake-to-answer latency, power draw, CPU/PSRAM, or K151 electrical safety claims are supported.

## 4. Reproducibility

- Audio generation plan (Windows local SAPI): `tools/generate_fresh_heami_holdout.py`.
- Calibration-only recipe: `tools/experiment_wake_trim_calibration.py`; deliberately ignores the `evaluation` directory.
- Fixed candidate SHA enforced by `tools/evaluate_fresh_frozen_heami.py`.
- The full comparison uses `tools/evaluate_fresh_frozen_heami.py` with the baseline public SWK1 and the experimental frozen SWK1 in [the fresh synthetic fixture directory](../fixtures/korean_heami_fresh_holdout_20261120/README.md). The 16 WAVs, corpus manifest, and frozen SWK1 have integrity hashes in `SHA256SUMS.txt`.
- Linux CI compiles and executes the host-only offline code, never K151 I2C/I2S. The firmware `app_main` remains in the HOLD loop; no NVS, OTA, PMIC, servo, microphone or speaker is touched.

## 5. Next research gate

Before another prototype, use **new training/calibration negatives that include the similar Korean phrases found in this test**, and plan an entirely different future holdout. Do not reuse the current 16 clips as an unbiased validation set. Consider a reject-margin score, minimum duration/phonetic discrimination, stronger contrastive examples, and a validated small-footprint acoustic keyword model, but these are **hypotheses**, not proven improvements. Real-speaker and in-room acoustic tests require a separate authorized bench setup with a reliable factory recovery path.

The current result supports **continued research only**; it is not ready for autonomous operation on the K151.
