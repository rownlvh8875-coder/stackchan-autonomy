# Korean “조수야” synthetic speech fixture — Windows Heami (2026-11-20)

**SYNTHETIC TEST AUDIO / NOT REAL USER VOICE / NOT A HARDWARE VALIDATION**

This folder was explicitly approved for GitHub upload by the project owner on 2026-11-20. It contains 24 WAV files synthesized on the owner's Windows PC with the locally installed **Microsoft Heami Desktop (ko-KR)** SAPI voice, the generated `SWK1` wake profile (843 bytes), and the associated corpus manifest.

- `enrollment/`: 1 generated “조수야” utterance
- `calibration/`: 5 additional “조수야” utterances at other speech rates and 10 other Korean utterances
- `evaluation/`: 2 generated “조수야” utterances and 6 nonwake Korean utterances
- `synthetic-sapi.wake-corpus.json`: role, label, self-declared split and relative filename; it does **not** prove recording-session independence
- `heami-korean-offline-zig.swk1`: one-template output of the existing C++20 MFCC/DTW enrollment pipeline, validated by `scfg_offline.py`
- `SHA256SUMS.txt`: integrity digests for the 24 WAVs, profile, and manifest

**Observed baseline (clean synthetic evaluation only):** 2/2 positive clips accepted, 0/6 nonwake clips accepted. All files use **24 kHz mono signed PCM16**. The synthesis engine is the same across enrollment, calibration and evaluation; the split is not acoustically or statistically independent, and these 8 samples cannot establish real Korean speech recognition accuracy, user-speaker recognition, hardware performance, or false wakes per hour.

**Creation and verification**

`firmware/standalone/tools/synthesize_korean_wake_sapi.py` reconstructs the *plan* using the local Windows speech engine; output may vary between voice revisions. `wake_corpus_audit.py`, `wake_corpus_pipeline.py`, `wake_wav_eval.cpp`, and the included C++ test workflow can verify the format and software behavior without opening a robot. See [2026-11-20 Korean TTS smoke result](../../docs/2026-11-20-korean-heami-tts-smoke.md).

**Audio usage / rights caution**

The included voice is an output of a Microsoft Windows built-in speech engine. Rights to independently redistribute or sublicense this particular SAPI voice's output were **not independently established**. This repository's source-code MIT license should **not** be interpreted as an independent license grant for this third-party synthesized speech content. Verify the applicable Microsoft Windows voice terms before reuse or redistribution. This folder does not contain Microsoft's speech engine binaries, the owner's real recorded voice, secrets, or paid API outputs. No claim of Microsoft endorsement.

**Safety:** Never flash a device, enable a microphone/speaker, weaken HOLD, or call paid APIs based on this dataset. Keep any later *human* WAV files and human-derived SWK1 profiles private and outside the repository; their general-purpose `.gitignore` exclusions remain in force.
