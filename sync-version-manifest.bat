@echo off
setlocal

cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0sync-version-manifest.ps1"
exit /b %errorlevel%