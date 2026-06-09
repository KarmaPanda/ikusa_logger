@echo off
setlocal

REM Check if the version number argument is provided
if "%~1"=="" (
    echo Error: Version number argument is missing.
    exit /B 1
)

REM Save the version number argument to a variable
set "VERSION=%~1"

set "SCRIPT_DIR=%~dp0"
set "ASSET_NAME=ikusa-logger-installer.exe"
set "UPDATE_SCRIPT=%SCRIPT_DIR%update.ps1"
set "INSTALL_DIR=%SCRIPT_DIR%"

if not exist "%INSTALL_DIR%ikusa-logger-win_x64.exe" (
    for %%I in ("%SCRIPT_DIR%..") do set "INSTALL_DIR=%%~fI\"
)

if "%INSTALL_DIR:~-1%"=="\" set "INSTALL_DIR=%INSTALL_DIR:~0,-1%"

REM Temporary location to save the downloaded file
set "TEMP_DIR=%TEMP%\%RANDOM%"
mkdir "%TEMP_DIR%"
set "EXECUTABLE_PATH=%TEMP_DIR%\%ASSET_NAME%"

if not exist "%UPDATE_SCRIPT%" (
    echo Error: update script not found: %UPDATE_SCRIPT%
    goto :cleanup
)

echo Resolving and downloading %ASSET_NAME% for release %VERSION% via GitHub REST API...
powershell -NoProfile -ExecutionPolicy Bypass -File "%UPDATE_SCRIPT%" -Version "%VERSION%" -OutputPath "%EXECUTABLE_PATH%" -AssetName "%ASSET_NAME%" || (
    echo Failed to download %ASSET_NAME% via GitHub REST API
    goto :cleanup
)

REM Ensure the app and logger helper are not still locking files.
taskkill /F /IM ikusa-logger-win_x64.exe >nul 2>&1
taskkill /F /IM logger.exe >nul 2>&1

REM Execute installer with visible progress but no user prompts.
echo Executing %ASSET_NAME% with visible progress...
start "" /wait "%EXECUTABLE_PATH%" /SP- /SILENT /SUPPRESSMSGBOXES /NOCANCEL /NORESTART /DIR="%INSTALL_DIR%"
if errorlevel 1 (
    echo Installer exited with an error.
    goto :cleanup
)

:cleanup
REM Clean up temporary directory
if exist "%TEMP_DIR%" (
    rmdir /s /q "%TEMP_DIR%"
)

echo Script execution completed.
