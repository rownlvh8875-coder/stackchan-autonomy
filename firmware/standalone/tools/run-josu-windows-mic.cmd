@echo off
setlocal
if /I "%~1"=="--help" goto HELP
call "%~dp0build-pc-wake-probe.cmd" --offline
if errorlevel 1 goto FAILED
set "SC_UV=uv"
if exist "%USERPROFILE%\.local\bin\uv.exe" set "SC_UV=%USERPROFILE%\.local\bin\uv.exe"
pushd "%~dp0..\..\.."
if errorlevel 1 exit /b 2
set "SC_PROFILE=firmware\standalone\fixtures\korean_josu_sapi_20261120\josu-20261120.swk1"
if exist ".local\josu\owner.swk1" set "SC_PROFILE=.local\josu\owner.swk1"
echo PC NOTEBOOK microphone only. Select the current input device explicitly.
echo One 3-second recording in RAM. No K151, GPT, network, or audio file.
"%SC_UV%" run --offline --no-project --with sounddevice==0.5.3 --with numpy==2.3.5 python firmware\standalone\tools\pc_mic_wake_probe.py --probe-exe .local\pc-wake\wake-stage1.exe --profile "%SC_PROFILE%" --listen --choose-device --seconds 3 --diagnostics
set "SC_RESULT=%ERRORLEVEL%"
popd
pause
exit /b %SC_RESULT%
:FAILED
pause
exit /b 2
:HELP
echo One explicit PC-only microphone test with quality and DTW diagnostics.
echo The current device list is shown; device 9 is not silently reused.
echo Uses a passing .local\josu\owner.swk1 when present, otherwise the TTS baseline.
echo Prepare tools as described in firmware\standalone\docs\2026-11-20-josu-human-mic.md
exit /b 0
