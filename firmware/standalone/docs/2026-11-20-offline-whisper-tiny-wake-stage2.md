# StackChan Korean wake stage 2 — pinned local Whisper tiny (2026-11-20)

**HOST-ONLY / NOT DEPLOYMENT-READY / NO HUMAN OR K151 ACOUSTIC TEST**

## Purpose and frozen method

The earlier fixed Vosk Korean recognizer rejected **all four** true wake
utterances in an already public, same-speaker Windows Heami TTS set.
This experiment implements a different **offline ASR verifier** using
**Systran/faster-whisper-tiny** (CTranslate2-converted, **multilingual**,
not the English-only `tiny.en` variant). This is a pre-trained
speech-to-text model and is NOT trained/fine-tuned on our TTS clips.

1. Stage 1 remains the **previously frozen 3-template DTW/SWK1**
   host C++ wake detector `tools/wake_stage1_probe.cpp`. The experimental
   trim compilation macro is needed for that specific positive profile;
   the real ESP32-S3 `app_main` remains untouched.
2. Only when stage 1 returns `OFFLINE_STAGE1_ACCEPT` does stage 2
   receive PCM from the *same local file* (converted 24kHz -> 16kHz mono
   PCM16 using the existing deterministic 33-tap windowed sinc).
3. Stage 2 runs the **local Whisper tiny** model on CPU, int8, 4 worker
   threads, single worker, forced Korean `language="ko"`, beam size 5,
   temperature 0, no prompt/hotwords, no previous context, no VAD,
   max 32 generated tokens. No audio is uploaded.
4. **Final acceptance rule:** normalize transcript with Unicode NFKC,
   strip whitespace and *trailing* basic punctuation only; accept **exactly
   `조수야`**, otherwise reject. No edit-distance, substring, confidence
   heuristic, or "fallback to stage 1 when Whisper fails" is allowed.
   Failures in model loading, audio validation or ASR execution fail
   closed and do not grant hardware access.

## Pinning and local installation

Official model card: `https://huggingface.co/Systran/faster-whisper-tiny`.
The converted model declares an MIT license and a multilingual language
list including Korean. The **English-only `tiny.en` is not used**.

- Model HF revision (frozen):
  `d90ca5fe260221311c53c58e660288d3deb8d356`
- `model.bin` size: **75,538,270 bytes**; SHA-256:
  `dcb76c6586fc06cbdac6dd21f14cfd129cc4cdd9dce19bf4ffa62e59cbe6e6d1`
- `config.json` SHA-256:
  `a73a28cdfe1c43ccc7202fa333d1f89c202477271407ae9a7f19afa52039cac8`
- `tokenizer.json` SHA-256:
  `fb7b63191e9bb045082c79fd742a3106a12c99513ab30df4a0d47fa6cb6fd0ab`
- Python local research package: `faster-whisper==1.2.1` plus
  dependencies including native CTranslate2. All versions above are
  research-environment **pins**, not vendor authenticity attestations.
- The owner's Windows PC keeps model assets separately at
  `C:\Users\user\stackchan-whisper-tiny-lab\faster-whisper-tiny`.
  Model files are **not committed into GitHub**, and inference requires
  the *already installed local directory* with exact expected hashes.
  Runtime sets `HF_HUB_OFFLINE=1` and uses
  `WhisperModel(..., local_files_only=True)`.
- One-time model/package download occurred only during development setup,
  **not** while sending synthetic voice to an API. Audio inference
  itself was offline.

**No measurable ESP32-S3 runtime/PSRAM suitability is established.**
The pretrained ~75MB model is significantly larger than the previous
847B linear and 1,423B tiny CNN *classifier parameter files*, and these
sizes are not a valid comparison of accuracy. CTranslate2 decoding,
tokenization, audio front-end and model RAM/runtime overhead must be
budgeted separately.

## Preliminary functionality check on already public Heami TTS

The existing set `fixtures/korean_heami_conv_postfreeze_20261120/`
was previously evaluated, so it was used **only for smoke**, NOT new
independent accuracy or to tune the fixed model/decoding rule.

| Offline architecture | Labeled wake accepted /4 | Nonwake erroneously accepted /12 |
|---|---:|---:|
| Frozen 3-template DTW only | 4 | 1 |
| DTW + local Vosk exact Korean transcript | 0 | 0 |
| DTW + local Whisper tiny exact Korean transcript | **2** | **0** |

The Whisper result was observed with genuine pre-trained model inference
on the owner's PC, not simulated ASR responses. Five utterances passed
stage 1 and Whisper ran only those five; local host step excluding model
load took about **2.0 seconds for five** (different environments and
model-loading time excluded; not a K151 latency measurement).

**No conclusion yet about new, blinded evaluation samples.** The rule
and pinned local model/code must be committed **before new synthetic WAV
generation**, and then compared on the *same* new holdout as the fixed
Vosk baseline with no tuning. Even new same-Heami synthetic audio cannot
establish real-human accuracy or false wakes/hour.

## Local CLI (never invoke on physical K151)

```powershell
# One-time package/model setup is permitted, separately from audio inference.
# For inference use the installed offline model; no model downloads permitted.
uv run --offline --frozen --with faster-whisper==1.2.1 python firmware/standalone/tools/whisper_wake_second_stage.py --manifest firmware/standalone/fixtures/korean_heami_conv_postfreeze_20261120/cnn-postfreeze.wake-corpus.json --stage1-binary C:\private\wake_stage1_probe.exe --stage1-profile firmware/standalone/fixtures/korean_heami_fresh_holdout_20261120/robust_trim_aug_frozen.swk1 --whisper-model-dir C:\private\faster-whisper-tiny
```

Local model data need not and should not be redistributed in the project.
The full workflow is explicitly **not** part of the K151 HOLD firmware,
and does not start I2S microphone, amplifier, speaker, PMIC, AW9523,
GPIO, NVS, OTA, factory recovery or any paid GPT/STT/TTS service.

**Hardware/production verdict remains REJECTED until independent
multi-speaker/room/audio tests, repeated false-wake-hour measurements and
bench safety/recovery checks are completed.**
