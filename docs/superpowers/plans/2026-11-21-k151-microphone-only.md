# Prepare the K151 microphone without opening the amplifier

1. Add a dormant, one-owner microphone preparation entry to the existing
   codec port. Require current owner/STOP state and independent board,
   electrical, amplifier-isolation and I2S ownership evidence. Keep the
   existing duplex entry and physical output flags.
2. Allocate simplex I2S RX in the fixed ES7210 input format. The bounded
   data adapter handles the already-configured RX directly, avoiding the
   vendor data layer's port-wide search for a paired output. Reuse the
   ES7210 control observer, codec device, bounded read and PCM handoff.
3. Execute the actual port with ABI doubles. Check missing evidence, an
   unexpected I2S peer, no TX/amp access, open/read/release, STOP and
   consent loss, short PCM and denied output callbacks. Retain existing
   SDK fault, cleanup and wipe regressions.
4. Run full host and pinned target checks and update the existing branch
   and PR. HOLD startup has no new activation. Physical rail/isolation,
   real PCM routing, STOP and an actual wake/GPT turn still require evidence.
