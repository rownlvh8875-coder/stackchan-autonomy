# Korean Heami synthetic holdout after linear classifier freeze (2026-11-20)

**NEW SAME-TTS SYNTHETIC WAVs / NOT HUMAN SPEECH / NOT K151-READY**

A deterministic **847-byte** linear MFCC model was frozen in GitHub commit
[`80e280c`](https://github.com/rownlvh8875-coder/stackchan-autonomy/commit/80e280c)
**before** these samples were synthesized. The model SHA-256 is
`4aa5c14fad637790aa33b0c512bd55ad64283aae34b13a9e78ae02247b981788`.
Its parameters were not changed after evaluating these files.

This folder contains 16 newly generated Windows Heami Desktop ko-KR SAPI
WAVs: four user-labeled "조수야" utterances (two fast speeds, two with
punctuation/prosody) and 12 competing Korean words. WAV inputs are 24kHz,
mono, PCM16. The original SAPI TTS generator rejected an excessively slow
clip outside the 3-second limit; that material never became a test example.
No model results were consulted to choose a threshold or revise the frozen
model. The final 16 clips were generated without real microphones.

Files:
- `evaluation/linear_eval_01.wav` through `linear_eval_16.wav`: 4 wake and
  12 nonwake synthetic utterances.
- `linear-postfreeze.wake-corpus.json`: labels and declared evaluation
  partition only (no training/calibration).
- `SHA256SUMS.txt`: 17 original assets checksummed; raw JSON bytes must not
  change through Git's newline normalization.

## Observed frozen-model comparison (identical 16 clips per condition)

| Condition | Original one-template DTW wake /4 | Three-template trimmed DTW wake /4 | New linear MFCC wake /4 | New linear wrong nonwake accepts /12 |
|---|---:|---:|---:|---:|
| Clean | 4 | 3 | 4 | **2** |
| Half gain | 4 | 3 | 4 | **2** |
| Gaussian noise 20dB SNR | 0 | 4 | 4 | **2** |
| Gaussian noise 10dB SNR | 0 | 2 | 4 | **2** |
| Gaussian noise 5dB SNR | 0 | 0 | 4 | **2** |
| Gaussian noise 0dB SNR | 0 | batch rejected | 4 | **2** |
| Synthetic echo 80ms | 0 | 1 | 4 | **2** |
| Synthetic echo 160ms | 0 | 0 | 4 | **2** |

Same 12 words recur under deterministic transforms. **These are NOT 96
independent negatives**, and 2/12 per condition is not a real-world
false-wake rate. Both DTW variants' nonwake counts are available in the
complete comparison documentation; the compact table focuses on the new
linear result. The linear model's clean false accepts establish a material
safety blocker even on synthetic samples. Do **not deploy**.

See `../../docs/2026-11-20-linear-kws-postfreeze-rejected.md` and
`tools/evaluate_linear_kws_postfreeze.py` for detailed reproducibility.

These WAVs derive from Microsoft Windows built-in SAPI Heami synthetic
speech. Redistribution rights were not independently verified, and a
repository's MIT source-code license does not imply an audio sublicense.
The project owner previously expressly allowed public GitHub synthetic
speech and profile artifacts. No live voice, credentials, paid API output,
Microsoft binaries, physical robot, or NVS/OTA modifications are included.
