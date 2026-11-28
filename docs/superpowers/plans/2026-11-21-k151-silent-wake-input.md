# Exercise the shared WakeNet input without a microphone

1. Test the real K151 RX-only port and reader with the existing FIR and a
   recording WakeNet double. Cover a full 512-sample chunk, late STOP,
   cancellation with a partial chunk, and reuse with a fresh input.
2. Extract the current bounded PCM ingestion from NativeWakeController to
   reuse its FIR, frame size, model checks and non-elidable wipes. Keep the
   controller's time, session-epoch, capture and admission duties.
3. Feed the shared input using 32 synthetic 10ms frames in the existing
   silent resource bench. Use the embedded, verified WakeNet model and its
   existing one-shot consent gate. Report only numerical timings and
   outcome. Preserve prior benchmark fields and keep real microphone,
   speaker and network dormant.
4. Check the host tests, real pinned target build and PR. Mark the physical
   microphone, electrical isolation, STOP and voice turn separately.
