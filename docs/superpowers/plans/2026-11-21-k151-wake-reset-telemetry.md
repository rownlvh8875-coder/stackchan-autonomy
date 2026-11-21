# Preserve the silent wake probe's last checkpoint

1. Test a reset failure, STOP at a checkpoint and the model detect boundary
   using the real 24kHz input streamer and a model double.
2. Add begin/return checkpoints only to the synthetic bench. Report the
   pinned ESP-IDF reset reason in its existing USB start message. Preserve
   the limits, local STOP/consent, model ownership and PCM wiping.
3. Add an offline-tested allowlist for the receiver. Retain the reason from
   a valid second start message before stopping that trial. The receiver
   sends one START and writes no nonce, PCM or raw serial lines to the report.
4. Run host and target verification, publish the evidence on the same
   branch and prepare a separate review artifact. The interrupted trial's
   cause remains unresolved until a newly approved measurement supplies it.
