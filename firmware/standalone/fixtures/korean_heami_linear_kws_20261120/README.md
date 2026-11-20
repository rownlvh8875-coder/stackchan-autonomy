# Frozen same-speaker Korean TTS linear MFCC research model

**HOST-ONLY / NOT A REAL PHONEME MODEL / NEVER FLASH TO K151**

`linear-kws-training-frozen.skwl` is the 847-byte, CRC32-protected
`SKWL1` host research model trained only on **previously known
training/calibration Heami synthetic WAV** (6 wake + 26 nonwake source clips),
augmented deterministically to 30 wake + 130 nonwake training examples.
Source code and all hyperparameters were frozen **before** new synthetic
evaluation clips were generated. Model SHA-256:
`4aa5c14fad637790aa33b0c512bd55ad64283aae34b13a9e78ae02247b981788`.

This is a 16×13 time-pooled-MFCC logistic-linear classifier (208 float32
weights + bias), not an acoustic phoneme recognizer, speaker verification,
ASR, certified WakeNet or deployed ESP32-S3 model.

On its **own correlated training examples**, 30/30 synthetic wake accepts,
10/130 wrong nonwake accepts. Those counts are unsuitable for accuracy
claims; **the candidate is not approved for real hardware**.

See `../../docs/2026-11-20-tiny-linear-mfcc-kws-development.md` for exact
training recipe and no-leakage boundary. This model was synthesized from
the user's expressly approved synthetic TTS test data. The underlying
Windows voice audio rights are not independently verified; no Microsoft
endorsement or independent WAV sublicense is asserted by the MIT code license.
