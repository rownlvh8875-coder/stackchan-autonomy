# StackChan 2026-11-20 — tiny 1D convolutional MFCC wake experiment

**HOST-ONLY CNN research, not K151 firmware, not phoneme recognition, not deployment-ready.**

The experimental model `core/offline_conv_kws.hpp` uses **eight learned
1D temporal convolution filters**, three MFCC-frame taps, ReLU activations,
4-region temporal pooling, then a linear output. Each frame consists of
13 quantized MFCC coefficients from `wake_features.hpp`. No TensorFlow,
PyTorch, external pretraining, phone recognizer, OpenAI/ElevenLabs speech
API, or physical microphone is involved.

- Input: 16 × 13 temporally pooled MFCC values, **not** raw audio.
- Architecture: 8 filters × 3 frames × 13 channels; 8 hidden biases,
  32 output weights, one output bias; **353 float32 parameters**.
- Model format: `SKWC1` magic, 2-byte parameter count, 353 little-endian
  floats and CRC32 = **1,423 bytes**. Wrong size, CRC, nonfinite weights,
  oversized values are rejected; output created exclusively.
- Training: class-balanced deterministic full-batch cross entropy with
  fixed zero-logit threshold, 650 epochs, learning rate 0.30 and L2 0.004.
  Classifier weights were **not tuned on previously published evaluation
  data**. Earlier 180-epoch/0.14/0.008 attempt was modified based only on
  the already known training-set results.
- Data: 6 previously committed Heami TTS `wake` training/calibration WAVs
  and 26 previously committed `nonwake` calibration WAVs, augmented
  deterministically by clean/half gain/20dB/10dB noise/80ms echo to 30
  synthetic wake and 130 synthetic nonwake training cases. These are only
  **32 original utterances, one Microsoft Heami synthetic voice**.
  Repeated augmentations are NOT 160 independent observations.

## Development-only, in-sample observations

| Recipe | Training wake accepts | Training nonwake false accepts |
|---|---:|---:|
| 180 epochs, step 0.14, L2 0.008 | 24/30 | 52/130 |
| 650 epochs, step 0.30, L2 0.004 | **30/30** | **5/130** |

These are outcomes on the examples used for learning. The improvement
**cannot be characterized as real wake accuracy or generalization**.
Even 5/130 in-sample negative misclassifications is not acceptable evidence
for unattended activation, and no field false-wake rate was measured.

## Frozen boundary before new evaluation

The final research model was generated *before* any new holdout audio with
exact SHA-256:

`3ed5d2aad7b933b62045c1c45e054a202bdf1b81da2fe7bd3dbd5bcd52c26cb5`

Stored at `fixtures/korean_heami_conv_kws_20261120/conv-kws-frozen.skwc`.
Source `tools/train_synthetic_conv_kws.py`, compiled C++ trainers
`tools/wake_conv_train.cpp` and `tools/wake_conv_eval.cpp` are host-only.
Source label roles are screened; `training_sources()` skips the old
`evaluation` WAVs and uses only existing enrollment/calibration data.

Only after freezing this code/model may a **new synthetic evaluation set**
be created to compare with previously frozen DTW and linear variants,
without changing any model weights, training settings or classification
threshold. Even then Heami synthetic speech is not real-world evidence.
Sample count, noise levels, speaker diversity, inference latency, ESP32-S3
power/PSRAM and AXP2101/AW9523/STOP electrical conditions remain untested.

**Never flash K151, enable physical microphone/speaker, alter PMIC, OTA,
NVS, or pay for live STT/GPT/TTS APIs based on this experiment. The firmware
`app_main` remains the existing non-activating HOLD program.**
