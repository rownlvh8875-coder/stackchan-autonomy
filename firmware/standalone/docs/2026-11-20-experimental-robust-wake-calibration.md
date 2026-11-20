# 2026-11-20 Experimental “조수야” energy trim + augmented SWK1

**Status: OFFLINE DEVELOPMENT / NOT K151 FIRMWARE / NO PRODUCTION WAKE CHANGE.**

## Fixed training/calibration partition and no-leakage controls

The previously committed Korean Heami TTS corpus has 1 `enrollment` wake clip, 5 `calibration` wake clips, 10 `calibration` nonwake clips, and 8 `evaluation` clips. The earlier robustness report **already looked at** those 8 evaluation clips, so they are no longer an unbiased holdout for choosing a new algorithm. **The new experiment script intentionally skips and never opens that evaluation directory.**

This experiment implements a separate host-only energy-region trim in `core/offline_wake_trim.hpp`. The original C++ `wake_wav_enroll.cpp` / `wake_wav_eval.cpp` compile unchanged in their **default feature behavior**; `-DSTACKCHAN_EXPERIMENTAL_WAKE_TRIM=1` must be explicitly supplied to invoke the new trim. The ESP32-S3 `app_main`, K151 microphone, PMIC, speaker and persistent profile paths are not changed.

The trim uses 24kHz mono PCM16, 10ms RMS frames, a 20th-percentile background estimate, a threshold equal to max(2.5× background, 0.1× peak), and 40ms context padding. It **fails closed** if estimated background exceeds 35% of peak, speech activity is insufficient, or the input violates 0.1–3s limits. This is a simple experimental energy heuristic, not a calibrated VAD or noise removal algorithm.

For augmented enrollment, the **same one training utterance** is used to create three templates: clean, nominal 20dB SNR Gaussian noise, and one 80ms/0.35 echo. That is **not three independent voices**. The acceptance threshold is calibrated ONLY on 5 clean positive / 10 clean negative calibration clips. Development diagnostics for each candidate use deterministic perturbations of those calibration clips. This is *development-set* evidence and may overestimate performance.

## Observed development-only counts (not final performance)

| Test condition | Original MFCC/DTW baseline accepted / 5 | Trim only / 5 | Trim + three templates / 5 | Wrong accepts with trim+3 / 10 |
|---|---:|---:|---:|---:|
| Clean | 5/5 | 5/5 | 5/5 | 0/10 |
| Gain 50% | 5/5 | 5/5 | 5/5 | 0/10 |
| Nominal 20dB SNR noise | 0/5 | 0/5 | **5/5** | 0/10 |
| Nominal 10dB SNR noise | 0/5 | 0/5 | **5/5** | 0/10 |
| Nominal 5dB SNR noise | 0/5 | 0/5 | 0/5 | 0/10 |
| Nominal 0dB SNR noise | 0/5 | matcher rejects input | matcher rejects input | **No counts** |
| Single echo 80ms / 0.35 | 0/5 | 0/5 | **5/5** | 0/10 |
| Single echo 160ms / 0.55 | 0/5 | 0/5 | 0/5 | 0/10 |

**Crucial:** The 0dB failure is a rejected full evaluation batch; it is NOT “zero false alarms”. No metric from that condition is available for the experimental matcher. The new method is not generally noise-robust and does not satisfy real-world safety conditions.

The calibration-only recipe was **frozen before any new holdout WAVs were generated**. The experimental three-template SWK1 output was privately generated from the training/calibration inputs with fixed SHA-256:

`b0231cbe83f5dccdb0adc129ccb4ec899f410abcb83d50007c51247a3b7f7aec`

The dev tool refuses to freeze unless the calibration counts match predefined development gates (clean, half gain, 20dB/10dB noise, 80ms echo; zero negative accepts). This is a development gate, not an independent validation criterion. It exclusively creates a new private SWK1; existing files are never overwritten.

## Reproduce the development step

```powershell
# Uses only already-cached Zig compiler, never sends audio to the network.
uv run --frozen python firmware/standalone/tools/experiment_wake_trim_calibration.py --freeze-profile C:\private\experimental-robust.swk1
```

The newly added `tools/generate_fresh_heami_holdout.py` prepares **NEW** Heami TTS samples at previously unused positive speech rates, and `tools/evaluate_fresh_frozen_heami.py` compares the published baseline and the **SHA-pinned** candidate using these new samples. Generating the holdout is a *later step*; it must not inform changes to the frozen algorithm or threshold. Even a fresh TTS set is **not evidence of different human speakers or acoustic field performance**.

Future real validation needs new human and competing-speech recordings at different distances/noises/rooms, a measured false-wake rate per time, and independent K151 power/microphone/physical STOP and factory firmware recovery verification. **Do not flash hardware or remove HOLD on the basis of this development experiment.**
