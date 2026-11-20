# Heami synthetic holdout after contrastive filter freeze (2026-11-20)

**SYNTHETIC KOREAN VOICE / NO HARDWARE / DEPLOYMENT REJECTED**

This dataset was generated **after** commit `a59e7be` froze a host-only
MFCC/DTW nonwake veto with a 2.0 negative-to-positive distance margin. It
contains 4 new SAPI "조수야" clips at new synthetic rates and 12 different
Korean nonwake phrases. All WAVs are 24kHz mono PCM16, synthesized with the
same Microsoft Heami Desktop voice.

- `evaluation/`: 16 post-freeze synthetic WAV files
- `post-freeze.wake-corpus.json`: user-defined roles and relative paths,
  all `evaluation`, never a calibration/training source
- `SHA256SUMS.txt`: SHA-256 for 16 WAVs + manifest (17 assets)

**Observed result:** original 3-template positive SWK1 and the contrastive
filter were applied to exactly the same new audio. No false accepts in either
system on these 12 negative utterances. The veto *increased* false rejection
of real labeled wake clips (clean 3/4 -> 2/4, 10dB noise 2/4 -> 1/4,
80ms echo 2/4 -> 0/4). The 20dB noise condition stayed 4/4 and 160ms
echo stayed 2/4. 0dB full-batch input was rejected by both, so no valid
recognition denominator was obtained. **This experiment does not establish
an improvement. Never deploy it on the K151.**

Same computer voice, limited utterances and deterministic perturbations:
no real-human false wake/hour, multispeaker or room/noise acoustics measured.
No audio/SDK interactions with a physical robot.

Audio redistribution rights to output from Microsoft Windows built-in TTS
were not independently established. Source-code MIT license does not
automatically grant rights to these third-party synthesized WAV assets.
The user previously authorized publishing synthetic speech/test profile
artifacts to GitHub; this is not a claim of Microsoft endorsement.
