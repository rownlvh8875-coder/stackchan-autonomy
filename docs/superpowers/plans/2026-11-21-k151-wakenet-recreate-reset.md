# Reset WakeNet with a fresh context

1. Run the actual K151 port against ABI doubles. Fail on the previous clean
   call and cover creation failure, changed format, STOP and owner loss
   before and during the replacement.
2. Retire the old context before creating a new one with the same verified
   model name and DET_MODE_90. Keep the existing global loader lease, check
   the full model format, and close on any failed reset.
3. Use the existing synthetic bench's pre/post-reset telemetry to build the
   next candidate. Verify model assets and bounds, run the host suites and
   pinned target CI, and record the exact install/restore review separately.
4. Leave physical execution pending a scoped approval. The prior SDK panic
   is localized to the reset boundary, with the exception site unresolved.
