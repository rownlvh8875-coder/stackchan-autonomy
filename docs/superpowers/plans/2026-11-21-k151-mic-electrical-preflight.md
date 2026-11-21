# K151 microphone electrical preflight

1. Compare the existing readback with the CoreS3 drawing and the AXP2101,
   AW9523B and AW88298 data sheets. Record the discrepancy between the
   schematic note and wiring for the analog rail. Keep earlier evidence.
2. Extend the actual read-only I2C fixture, fail it against the old read
   sequence, then add AXP2101 0x92/0x93 and AW9523B 0x12 to the existing
   observer. Preserve prior report fields. Abort and discard the entire
   observation on errors, STOP or consent loss.
3. Test the additive board-probe report and the reset-latch interpretation.
   Describe the remaining electrical measurements using the schematic.
   Run host tests and the pinned target build on the existing branch.
4. Review the local artifact and backup verification. Use these observations
   to prepare the microphone trial after physical evidence is available.
   Configuration data supplies no trial admission or electrical measurement.
