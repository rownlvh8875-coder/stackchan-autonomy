# Korean Heami synthetic voice — fixed-profile noise/echo robustness probe

Date: **2026-11-20**. This report is a *software-only* experiment with publicly shared **synthetic test fixtures** that the project owner explicitly approved for GitHub. It is not an evaluation of Korean speech spoken by real people, and it does **not** authorize robot installation.

## Materials and methodology

- Source corpus: [24 Heami Korean TTS clips](../fixtures/korean_heami_sapi_20261120/README.md) (1 enrollment wake, 5 calibration wake, 10 calibration nonwake, 2 evaluation wake, 6 evaluation nonwake).
- Fixed profile: `fixtures/korean_heami_sapi_20261120/heami-korean-offline-zig.swk1`, 843 bytes, single template, CRC verified by the offline SWK1 tool.
- Existing C++20 `tools/wake_wav_eval.cpp` uses the firmware's own MFCC / DTW features. It was compiled and run on the owner's Windows laptop using the already cached Zig C++ toolchain. No robot, microphone, physical speaker, OpenAI call or paid TTS service was accessed during evaluation.
- For every condition, the **same eight independent-from-calibration TTS files** (2 labeled wake, 6 labeled nonwake) were modified deterministically. The transformed output audio is generated under a temporary folder and not committed.
- Noise is added zero-mean synthetic Gaussian PCM noise at **nominal RMS SNR** 20/10/5/0 dB, with clipping to PCM16. Echo is a single reflected sample stream with a 80 ms / 0.35 or 160 ms / 0.55 delay/gain and normalization to reduce clipping. These are **not measurements of a real room acoustic impulse response**, and across-condition trials are *not independent*.
- Only the WAV waveform was perturbed; training templates and the SWK1 acceptance threshold were **not** re-trained or selected using evaluation clips.

## Directly observed counts (C++ matcher, same SWK1)

| Synthetic waveform condition | Wake accepted / 2 | Nonwake accepted / 6 | Interpretation |
|---|---:|---:|---|
| Clean Heami TTS | 2 / 2 | 0 / 6 | Baseline matching on a small same-speaker TTS set |
| Gain × 0.5 | 2 / 2 | 0 / 6 | Invariant to this one synthetic amplitude change |
| Gaussian noise, nominal 20 dB SNR | 0 / 2 | 0 / 6 | Both positive utterances missed |
| Gaussian noise, nominal 10 dB SNR | 0 / 2 | 0 / 6 | Both positive utterances missed |
| Gaussian noise, nominal 5 dB SNR | 0 / 2 | 0 / 6 | Both positive utterances missed |
| Gaussian noise, nominal 0 dB SNR | 0 / 2 | 0 / 6 | Both positive utterances missed |
| Single echo, 80 ms / 0.35 | 0 / 2 | 0 / 6 | Both positive utterances missed |
| Single echo, 160 ms / 0.55 | 0 / 2 | 0 / 6 | Both positive utterances missed |

**Conclusion:** the current one-template, clean-speech MFCC/DTW wake profile **failed this synthetic noise/echo stress test**, despite clean baseline success. The zero observed nonwake accepts is based on only six TTS clips repeatedly transformed, so this is **not** a measured real-world false-alarm rate or proof of safety. At nominal 20 dB noise it already missed both labeled wake samples; that observation is a concrete blocker for considering the wake implementation robust.

## Reproduction (no audio/data upload)

After cloning the fixture files and installing a local C++20 compiler, compile the existing `tools/wake_wav_eval.cpp` into a private executable. Example for the Windows machine with the previously cached Zig toolchain:

```powershell
uvx --offline --from ziglang==0.15.2 python-zig c++ -std=c++20 -O2 -Wall -Wextra -Werror -pedantic -I firmware/standalone/core firmware/standalone/tools/wake_wav_eval.cpp -o C:\private\wake_eval.exe

uv run --frozen python firmware/standalone/tools/evaluate_synthetic_robustness.py --fixtures firmware/standalone/fixtures/korean_heami_sapi_20261120 --profile firmware/standalone/fixtures/korean_heami_sapi_20261120/heami-korean-offline-zig.swk1 --evaluator C:\private\wake_eval.exe
```

The JSON output identifies **synthetic** matching counts only; it never returns authorization to flash firmware. Generated perturbation WAVs are deleted when the test exits. `tests/test_heami_shared_synthetic_fixtures.py` verifies the 26 committed binary assets against `SHA256SUMS.txt`, the 24 WAV format/corpus split, and runs the host C++ matcher on Linux when a compiler is available.

## Recommended next algorithm research

Experiment **offline** on a separate development branch with denoising, front-end voice activity segmentation, adaptive feature normalization, and/or augmented enrollment templates. Freeze the independent evaluation split; do not use these 8 evaluation clips to choose hyperparameters or tune an acceptance threshold. Collect new separate real-speaker and competing speech data before estimating miss and false-wake rates. Actual K151 microphone clock/channel routing, power/reset, STOP and factory-recovery evidence are still missing. **Device installation stays HOLD.**
