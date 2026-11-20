# Frozen same-speaker tiny CNN keyword research model

**HOST-ONLY / EXPERIMENTAL / NOT A PHONEME ASR MODEL / NEVER FLASH**

`conv-kws-frozen.skwc` is a 1,423-byte CRC32-protected `SKWC1`
tiny time-convolution model from the owner's explicitly approved Heami
synthetic development WAVs (6 known wake + 26 known nonwake utterances,
5 deterministic transformations each). It was frozen and published
**before** creating any new synthetic evaluation clips.

Architecture: 8 trainable 3-tap temporal filters over 13 MFCC coefficients,
ReLU, 4-region average pooling and logistic binary output (353 float32
parameters). This is **not** a Korean phoneme recognizer or verified
keyword model.

**SHA256:** `3ed5d2aad7b933b62045c1c45e054a202bdf1b81da2fe7bd3dbd5bcd52c26cb5`.

Training-only results (correlated examples): 30/30 synthetic wake accepted,
5/130 synthetic nonwake incorrectly accepted. This is **NOT** independent
validation, real-human accuracy or false wakes/hour. Deployment denied.

Source and fixed settings are described in
`../../docs/2026-11-20-tiny-conv-mfcc-kws-development.md`.
No private human voice, paid API data, Microsoft TTS engine binary, K151
firmware, OTA/NVS or physical hardware action is included.
