# Fresh Heami synthetic evaluation after frozen tiny CNN commit

**SYNTHETIC SINGLE SPEAKER / NOT REAL Korean wake-word accuracy / NO DEPLOYMENT**

The 1,423-byte tiny temporal CNN research classifier was frozen in GitHub
commit `92a3796620d6a87aa651d914e19e5aca5af390c9` **before** generating
these 16 new Windows Heami Desktop (ko-KR) SAPI WAV clips. Fixed model
SHA-256: `3ed5d2aad7b933b62045c1c45e054a202bdf1b81da2fe7bd3dbd5bcd52c26cb5`.

- 4 labeled synthetic wake `조수야` utterances (2 fresh rates and 2
  prosodic punctuation variants).
- 12 different, phonetically similar Korean synthetic nonwake phrases.
- 16 files in `evaluation/`, all 24kHz mono PCM16; none are training or
  calibration files.
- `cnn-postfreeze.wake-corpus.json` contains only final-evaluation roles.
- `SHA256SUMS.txt` checks the 17 original assets. Do not modify manifest
  newline bytes in Git; `.gitattributes` marks it as binary.

The owner explicitly approved making synthetic voice test fixtures public
in GitHub. Rights to independently redistribute Microsoft built-in TTS
outputs have **not** been established; MIT code licensing does not
constitute an independent audio license or Microsoft endorsement.

New holdout observations with the fixed CNN: synthetic wake accepted 4/4
on clean audio, nominal noise 20dB, 10dB, 5dB and 80ms synthetic echo.
Synthetic nonwake incorrectly accepted **3/12 even on clean audio**,
**4/12 at 20dB**, **3/12 at 10dB**, and **3/12 at 80ms echo**.
The same 12 negative utterances were transformed repeatedly, so these
are not independent trials. **Reject CNN for unattended K151 activation.**
See `../../docs/2026-11-20-tiny-conv-postfreeze-rejected.md`.

No real user recording, paid API, physical robot, GPIO, PMIC, NVS, OTA,
microphone or speaker was accessed or changed.
