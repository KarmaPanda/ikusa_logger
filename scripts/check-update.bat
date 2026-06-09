@echo off
setlocal

set "SCRIPT_PATH=%~dp0check-update.ps1"

if not exist "%SCRIPT_PATH%" (
    exit /B 1
)

for /f "usebackq delims=" %%v in (`powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_PATH%" 2^>nul`) do (
    set "LATEST_VERSION=%%v"
)

if not defined LATEST_VERSION (
    exit /B 1
)

echo %LATEST_VERSION%
exit /B 0
