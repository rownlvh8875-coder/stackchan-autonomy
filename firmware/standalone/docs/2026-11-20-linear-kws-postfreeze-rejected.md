# 2026-11-20 Frozen 847-byte linear MFCC KWS — NEW synthetic holdout

**Final engineering verdict: NOT DEPLOYABLE.**

## Experimental chain and anti-leakage boundary

The new model is not DTW. `offline_linear_kws.hpp` linearly classifies 16×13
time-pooled MFCC coefficients using one bias and 208 weights (847-byte
`SKWL1` file including version, dimensions and CRC32). No pretrained model,
phoneme decoder, ASR or external service is used.

Only previously committed **enrollment/calibration** Heami Windows TTS WAVs
(6 labeled positive + 26 labeled negative original utterances, five
deterministic perturbations each) trained the model. This is one TTS voice;
augmented examples are not independent utterances. The initial training
experiment (240 epochs, L2=0.025) observed **30/30 wake, 15/130 wrong
nonwake accepts**. The revised training-only settings (650 epochs,
L2=0.012, learning step=0.20) observed **30/30 wake, 10/130 wrong
nonwake accepts**. These were **training counts**, not accuracy.

The 847-byte model, training code, settings and SHA-256
`4aa5c14fad637790aa33b0c512bd55ad64283aae34b13a9e78ae02247b981788`
were frozen in [`80e280c`](https://github.com/rownlvh8875-coder/stackchan-autonomy/commit/80e280c)
**before** creating a new set of synthetic evaluation WAVs. The script never
opened previously published evaluation WAVs for fitting. A subsequent batch
of 4 new wake and 12 new nonwake Heami synthetic utterances was generated
with valid 0.1–3s 24kHz PCM16 lengths. One attempted too-slow synthesizer
setting was rejected by the format validator *before testing*; it was not
used to alter the frozen model.

## One-shot observed results

All three classifiers were tested on exactly the same 16 new base WAVs in
each row: original 1-template DTW, previous 3-template + optional trim DTW,
and the new host-only linear model. Six noisy/echo cases are **deterministic
perturbations of those same 16 base utterances**, not new independent
recordings. The training threshold and model remained unchanged.

| Condition | Original DTW wake accepted /4 | Augmented DTW wake accepted /4 | Linear wake accepted /4 | Linear nonwake falsely accepted /12 |
|---|---:|---:|---:|---:|
| Clean | 4 | 3 | **4** | **2** |
| Gain ×0.5 | 4 | 3 | **4** | **2** |
| Gaussian noise nominal 20dB RMS SNR | 0 | 4 | **4** | **2** |
| Gaussian noise nominal 10dB RMS SNR | 0 | 2 | **4** | **2** |
| Gaussian noise nominal 5dB RMS SNR | 0 | 0 | **4** | **2** |
| Gaussian noise nominal 0dB RMS SNR | 0 | **full batch rejected; no counts** | **4** | **2** |
| Synthetic 80ms/0.35 single echo | 0 | 1 | **4** | **2** |
| Synthetic 160ms/0.55 single echo | 0 | 0 | **4** | **2** |

For both DTW variants, nonwake wrong accepts were 0/12 on clean speech; under
20dB nominal noise the augmented variant falsely accepted 2/12 and under
other 10dB/5dB/echo conditions it accepted 0/12. The original DTW had 0/12
nonwake wrong accepts under all eight conditions.

**Interpretation:** linear MFCC logistic scoring is robust to these chosen
artificial waveform changes for the four synthetic wake clips, **but it
falsely activates on two of the twelve other Korean phrases even in clean
audio** and continues to do so in every tested perturbation. A false wake
is operationally material, so this linear candidate **is rejected for
autonomous K151 use**. The evidence is too small and too synthetic for a
false wake per hour or real-human recognition rate claim; the same two
misclassifications could recur on each condition.

## Files and reproducibility

- `fixtures/korean_heami_linear_kws_20261120/linear-kws-training-frozen.skwl`
  is the model frozen *before* these samples.
- `fixtures/korean_heami_linear_postfreeze_20261120/` contains the new
  16 TTS WAVs, full role manifest and SHA-256 checksums.
- `tools/generate_linear_kws_postfreeze.py` rebuilds a local TTS batch using
  Windows Heami; regenerated audio may differ with voice engine version.
- `tools/evaluate_linear_kws_postfreeze.py` checks fixed model hashes and
  compiles C++20 host-only binaries for all three methods; it reports the
  same-sample grouped results. It creates and deletes temporary WAV
  perturbations, never modifies the model.
- `tests/test_offline_linear_kws.py` and
  `tests/test_linear_kws_postfreeze.py` assert file integrity, safety
  invariants, model validity and host tool behavior. The ESP32 firmware
  `app_main` never includes or activates the research model.

## Technical implications

A tiny linear classifier reduces classifier-model storage but does not
solve acoustic disambiguation. Next research directions may include a
small convolutional keyword model with adequate phonetic hard negatives,
a second-stage ASR confirmation, adaptive VAD and a larger genuinely
speaker/environment-diverse dataset. These are **future hypotheses**, not
outcomes established here. An ESP32-S3 build success is only a compile
check of a HOLD image and does not establish CPU/memory/power/latency
budgets, factory recovery, STOP or electrical audio safety.

**Do not flash, unlock, turn on speaker/PMIC, or call paid APIs.**
