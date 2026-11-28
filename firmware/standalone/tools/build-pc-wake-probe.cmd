@echo off
setlocal
if /I "%~1"=="--help" goto HELP
set "SC_UV=uv"
if exist "%USERPROFILE%\.local\bin\uv.exe" set "SC_UV=%USERPROFILE%\.local\bin\uv.exe"
set "SC_OFFLINE="
if /I "%~1"=="--offline" set "SC_OFFLINE=--offline"
pushd "%~dp0..\..\.."
if errorlevel 1 exit /b 2
if not exist ".local\pc-wake" mkdir ".local\pc-wake"
"%SC_UV%" tool run %SC_OFFLINE% --from ziglang==0.15.2 python-zig c++ -std=c++20 -O2 -s -Wall -Wextra -Werror -pedantic -Ifirmware/standalone/core firmware/standalone/tools/wake_stage1_probe.cpp -o .local\pc-wake\wake-stage1.exe
set "SC_RESULT=%ERRORLEVEL%"
popd
if not "%SC_RESULT%"=="0" echo PC probe build failed. See the human microphone guide for offline tool preparation.
exit /b %SC_RESULT%
:HELP
echo Build the current PC-only C++20 helper. No microphone, robot, or API.
echo --offline requires the pinned Zig tool package already cached.
exit /b 0
