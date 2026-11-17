@echo off
setlocal DisableDelayedExpansion
chcp 65001 >nul
set "PYTHONUTF8=1"
set "STACKCHAN_LAUNCH_UV=%USERPROFILE%\.local\bin\uv.exe"
if not exist "%STACKCHAN_LAUNCH_UV%" (
    where uv.exe >nul 2>&1
    if errorlevel 1 (
        echo PC_UV_NOT_FOUND
        echo Install uv, then run this launcher again. See docs\GPT_ROBOT.ko.md.
        pause
        exit /b 2
    )
    set "STACKCHAN_LAUNCH_UV=uv.exe"
)
pushd "%~dp0.."
if errorlevel 1 (
    echo PC_PROJECT_DIRECTORY_UNAVAILABLE
    pause
    exit /b 2
)
"%STACKCHAN_LAUNCH_UV%" run --frozen stackchan-pc-mcp --gpt --reconnect
set "STACKCHAN_LAUNCH_EXIT=%errorlevel%"
popd
if "%STACKCHAN_LAUNCH_EXIT%"=="130" exit /b 130
if "%STACKCHAN_LAUNCH_EXIT%"=="-1073741510" exit /b -1073741510
if not "%STACKCHAN_LAUNCH_EXIT%"=="0" (
    echo PC_BRIDGE_STOPPED
    echo Read the error above. Press a key to close this window.
    pause
)
exit /b %STACKCHAN_LAUNCH_EXIT%
