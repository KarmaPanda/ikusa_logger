@echo off
setlocal

set "SCRIPT_PATH=%~dp0scripts\build.bat"
if not exist "%SCRIPT_PATH%" (
    echo [ERROR] Missing script: %SCRIPT_PATH%
    exit /b 1
)

call "%SCRIPT_PATH%" %*
exit /b %errorlevel%
