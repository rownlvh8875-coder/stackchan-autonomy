# K151 10ms microphone -> bounded 20ms question bridge

Status: **OFFLINE HOST TEST / COMPILE ONLY / NO DEVICE INSTALL**.

The existing dormant `K151CodecPort::capture_mono_24k` accepts up to 240 mono PCM16 samples (10ms at 24kHz) per read. The new `MonoMicReader` interface and `MicFrameBridge` join exactly two successful reads into the 480-sample frame expected by `QuestionCapture`. `K151MicReader` is a thin guarded hardware adapter; it rejects wrong frame sizes and unprepared/faulted codec state. It is included by the ESP32-S3 HOLD entrypoint for compilation only, never constructed or invoked at boot.

Any STOP, speaker activity, failed or incomplete read latches the bridge in fault and discards the question buffer, including a previously completed recording. Tests use a synthetic reader rather than K151 hardware, explicitly covering half-frame I/O failure, STOP racing with input, speaker exclusion, and the silence-completed path.

**Not proven:** microphone electrical/clock routing, I2S/TDM data alignment, true 24kHz capture, mic gain/noise, acoustic recognition of Korean '조수야', STOP latency, memory headroom, live GPT API, playback or device flashing. Actual deployment requires verified hardware identity, factory recovery, independent power/mute validation and explicit device approval. Do not initialize peripherals or overwrite factory firmware as part of this stage.
