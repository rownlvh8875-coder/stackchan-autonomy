@echo off
setlocal DisableDelayedExpansion
chcp 65001 >nul
set "PYTHONUTF8=1"
pushd "%~dp0.."
if errorlevel 1 (
    echo PC_PROJECT_DIRECTORY_UNAVAILABLE
    pause
    exit /b 2
)
set "STACKCHAN_LAUNCH_PY=%CD%\.venv\Scripts\python.exe"
if not exist "%STACKCHAN_LAUNCH_PY%" goto setup_required
"%STACKCHAN_LAUNCH_PY%" -c "import stackchan_autonomy.official_mcp_cli" >nul 2>&1
if errorlevel 1 goto setup_required
"%STACKCHAN_LAUNCH_PY%" -m stackchan_autonomy.official_mcp_cli --gpt --reconnect
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

:setup_required
echo PC_PYTHON_ENV_REQUIRED
echo Prepare the local environment once, then start this launcher again:
echo "%USERPROFILE%\.local\bin\uv.exe" --directory "%CD%" sync --frozen
pause
popd
exit /b 2
