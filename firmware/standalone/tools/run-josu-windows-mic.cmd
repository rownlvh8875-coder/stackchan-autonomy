@echo off
setlocal
if /I "%~1"=="--help" goto HELP
set "ROOT=%~dp0..\..\.."
set "PROBE=%USERPROFILE%\Documents\josu_pcm_stdin_probe_20261120.exe"
set "PROFILE=firmware\standalone\fixtures\korean_josu_sapi_20261120\josu-20261120.swk1"
if not exist "%PROBE%" (
  echo PC-only C++ probe binary is missing. See firmware\standalone\docs\2026-11-20-pc-mic-josu-probe.md
  exit /b 2
)
pushd "%ROOT%"
if errorlevel 1 exit /b 2
echo ==========================================================
echo PC NOTEBOOK microphone ONLY. This does not use K151 mic.
echo 2.5 seconds, local RAM only. No GPT, cloud, or robot output.
echo Say the Korean wake word "JOSU" once after RECORDING starts.
echo ==========================================================
uv run --offline --no-project --with sounddevice==0.5.3 --with numpy python firmware\standalone\tools\pc_mic_wake_probe.py --probe-exe "%PROBE%" --profile "%PROFILE%" --listen --device 9 --seconds 2.5
set "RESULT=%ERRORLEVEL%"
popd
echo.
echo This does not confirm real K151 wake recognition.
pause
exit /b %RESULT%
:HELP
echo Run this .cmd in a Windows terminal (or double-click) for a single
echo local laptop mic recording. No K151 hardware or network is contacted.
echo Device 9 was observed only on the owner's Windows laptop.
echo The recording is analyzed in memory and is never saved to a WAV file.
exit /b 0
