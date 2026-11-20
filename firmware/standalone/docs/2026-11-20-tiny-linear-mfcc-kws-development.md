# 2026-11-20 — Small discriminative MFCC keyword classifier (HOST ONLY)

**STATUS: LINEAR RESEARCH PROTOTYPE / NOT A KOREAN PHONEME OR ASR MODEL / NOT READY FOR K151.**

This work introduces a **deterministic 208-input linear logistic classifier**
(`core/offline_linear_kws.hpp`) over 16 temporal bins × 13 original MFCC
coefficients, computed from the existing unmodified 24kHz PCM feature core.
It does **not** use DTW at inference time. No pre-trained external model or
cloud API is involved. The model and training tools are strictly host-only;
the ESP32-S3 firmware's `app_main`, physical STOP, audio hardware, NVS and
OTA are unchanged and the HOLD gate remains in place.

The model file `linear-kws-training-frozen.skwl` has a fixed 847-byte
`SKWL1` little-endian layout with 208 float32 weights, float32 bias, version,
dimensions and CRC32. A corrupt, NaN, Inf, wrong-size or tampered model fails
closed; tools reject duplicate PCM across labeled examples and will not
overwrite an existing model output. The decision threshold is **fixed at
logit greater than zero**; this is not an empirically validated human speech
threshold. Unlike an actual phonetic/linguistic classifier, this is simply
one supervised linear boundary on pooled MFCCs.

## Training partition and frozen recipe

Only the **already published training/development** recordings were used.
The previous Heami source corpus contributed **6 wake** clips (enrollment plus
calibration) and **10 nonwake** clips (calibration only). The prior 16
`korean_heami_hardneg_20261120` calibration negatives were added. Any clips
with role `evaluation`, including all prior held-out sets, were **skipped,
not opened, and not used to select hyperparameters**.

Five deterministic augmentations per original waveform:
clean, half-amplitude, nominal 20dB RMS SNR Gaussian noise, nominal 10dB
Gaussian noise and synthetic 80ms echo. Thus **30 positive and 130 negative
training examples**, derived from only **6+26 base utterances**. Augmented
examples are correlated and cannot be reported as independent observations.
All waveforms derive from **one Heami Windows TTS speaker**, not real humans.

Training algorithm: fixed class-balanced full-batch logistic gradient descent,
step size **0.20**, **650 epochs**, L2 coefficient **0.012**, with a fixed
zero-logit decision boundary. The preliminary development attempt used
240 epochs/L2 0.025, giving 30/30 wake and 15/130 negative accepts on its
*training* examples; the revised recipe was selected on training counts only
and gave 30/30 wake and 10/130 wrong accepts on the same *training* cases.

These training metrics **do not establish generalization**; a classifier
that produces 10 wrong accepts on 130 even in-sample is clearly not reliable
enough for unattended autonomous wake. The fact that model size is small says
nothing about the peak RAM/CPU of the MFCC extractor on ESP32-S3.

**Frozen model SHA-256** (commit the file and code before generating the
next evaluation set):
`4aa5c14fad637790aa33b0c512bd55ad64283aae34b13a9e78ae02247b981788`

## Reproduce locally without network or hardware

```powershell
# An already cached C++20 compiler is required for compiling the tools.
uvx --offline --from ziglang==0.15.2 python-zig c++ -std=c++20 -O2 -Wall -Wextra -Werror -pedantic -Ifirmware/standalone/core firmware/standalone/tools/wake_linear_train.cpp -o C:\private\wake_linear_train.exe

uvx --offline --from ziglang==0.15.2 python-zig c++ -std=c++20 -O2 -Wall -Wextra -Werror -pedantic -Ifirmware/standalone/core firmware/standalone/tools/wake_linear_eval.cpp -o C:\private\wake_linear_eval.exe

uv run --frozen python firmware/standalone/tools/train_synthetic_linear_kws.py --trainer C:\private\wake_linear_train.exe --evaluator C:\private\wake_linear_eval.exe --output C:\private\NEW-linear-kws.skwl
```

The script trains using deterministic augmented PCM from already committed
development WAVs; it creates a *new* model only at an explicitly supplied
path outside the repository. For the checked-in frozen output, the exact
SHA-256 is verified by tests on the host. Linux and Windows may have
compiler floating-point differences, so binary identical training output
across operating systems is **not** asserted without proof.

### Limits and next validation gate

Generate **new synthetic Korean Heami audio only after this frozen commit**,
with separate wake and previously unused nonwake phrases. Compare fixed
model vs the frozen three-template MFCC/DTW baseline with **no tuning**.
That fresh same-speaker TTS experiment will still be insufficient to
estimate real human recognition, false wake/hour, motor noise, speaker echo,
K151 clock/power/STOP or user safety. If the new classifier misses wakes or
accepts similar Korean nonwake words, record rejection rather than tune on
the already exposed set.

**No K151 firmware installation, hardware read/write, paid API call, or change
to factory recovery state is authorized or performed by this project step.**
