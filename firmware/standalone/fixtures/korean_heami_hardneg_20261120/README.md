# Korean Heami close-word synthetic calibration negatives (2026-11-20)

**SYNTHETIC TRAINING / CALIBRATION ONLY — NOT INDEPENDENT VALIDATION**

16 Korean nonwake WAVs generated locally on Windows with the same Microsoft
Heami Desktop ko-KR SAPI voice, at 24kHz mono PCM16. All are intentionally
**not** the exact phrase `조수야`. Some phonetically similar words were already
seen in an earlier public holdout and are now explicitly treated as
**DEVELOPMENT/TRAINING examples**, never independent test evidence.

- `calibration/hard_negative_01.wav` ... `hard_negative_16.wav`
- `hard-negative-calibration.json` (all 16 labeled nonwake, calibration-only)
- `SHA256SUMS.txt` contains raw file digests; byte-exact JSON under `.gitattributes`
- `tools/experiment_contrastive_calibration.py` uses the first 8 examples in
  the negative comparison feature bank (together with 10 original calibration
  negatives) and the other 8 as development-only near-word probes.
- **Never use the other 8 as a new independently held-out evaluation** after
  viewing development scores. These 16 are one SAPI speaker, not humans.

The code/records are available for reproducibility with the owner's prior
approval to upload synthetic audio and SWK1 data. Independently licensed
redistribution rights for the Windows built-in voice's output were NOT verified;
the repository source MIT license does not automatically apply to these WAVs.
No real user voice, credentials, cloud API output, robot firmware or engine
binaries are included. This experiment does not authorize device installation.
