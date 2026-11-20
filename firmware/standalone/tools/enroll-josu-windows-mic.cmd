@echo off
setlocal
if /I "%~1"=="--help" goto HELP
call "%~dp0build-pc-wake-probe.cmd" --offline
if errorlevel 1 goto FAILED
set "SC_UV=uv"
if exist "%USERPROFILE%\.local\bin\uv.exe" set "SC_UV=%USERPROFILE%\.local\bin\uv.exe"
pushd "%~dp0..\..\.."
if errorlevel 1 exit /b 2
echo Explicit PC-only private JOSU enrollment. Ctrl+C cancels.
echo Each recording is 3 seconds. Wait for the next prompt before pressing Enter again.
echo 3 enrollment, 5+10 calibration, 5+10 fresh evaluation, 3 quiet windows.
echo No WAV/features saved. Only a passing SWK1 is saved to .local\josu\owner.swk1
"%SC_UV%" run --offline --no-project --with sounddevice==0.5.3 --with numpy==2.3.5 python firmware\standalone\tools\pc_mic_enroll.py --enroll --probe-exe .local\pc-wake\wake-stage1.exe --choose-device --seconds 3 --output .local\josu\owner.swk1
set "SC_RESULT=%ERRORLEVEL%"
popd
pause
exit /b %SC_RESULT%
:FAILED
pause
exit /b 2
:HELP
echo Explicitly enroll and independently evaluate the PC microphone wake phrase.
echo No robot/API/continuous listening. A new ignored personal SWK1 file only.
echo Existing profiles are never overwritten; choose a fresh output via Python CLI.
exit /b 0
