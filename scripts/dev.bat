@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "PROJECT_ROOT=%%~fI"
cd /d "%PROJECT_ROOT%"

set "DEV_RUNTIME_DIR=%PROJECT_ROOT%\.dev-runtime"
set "DEV_NEU_RUNNER=%PROJECT_ROOT%\scripts\dev-run-neutralino.ps1"
set "APP_HTML=%PROJECT_ROOT%\ui\src\app.html"
set "APP_HTML_BACKUP=%DEV_RUNTIME_DIR%\app.html.neu.bak"

if not exist "%DEV_RUNTIME_DIR%" mkdir "%DEV_RUNTIME_DIR%"
if not exist "%DEV_RUNTIME_DIR%\logger" mkdir "%DEV_RUNTIME_DIR%\logger"
if not exist "%DEV_RUNTIME_DIR%\logger\.tmp" mkdir "%DEV_RUNTIME_DIR%\logger\.tmp"
if not exist "%DEV_RUNTIME_DIR%\config.ini" copy "%PROJECT_ROOT%\config.ini" "%DEV_RUNTIME_DIR%\config.ini" /Y >nul

set "VITE_IKUSA_PROJECT_ROOT=%PROJECT_ROOT%"
set "VITE_IKUSA_DEV_RUNTIME=%DEV_RUNTIME_DIR%"

set "SKIP_BUILD=0"
if /I "%~1"=="--no-build" set "SKIP_BUILD=1"
if /I "%~1"=="-n" set "SKIP_BUILD=1"

if "%SKIP_BUILD%"=="1" (
	echo [INFO] Skipping build ^(no-build mode^).
) else (
	echo [INFO] Building latest artifacts before launch...
	call "%PROJECT_ROOT%\scripts\build.bat"
	if errorlevel 1 (
		echo [ERROR] build.bat failed. Dev launch aborted.
		exit /b %errorlevel%
	)
)

echo [INFO] Normalizing Neutralino globals script URL in ui\src\app.html...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$path = Resolve-Path '.\ui\src\app.html'; $content = Get-Content $path -Raw; $updated = $content -replace 'http://localhost:\d+/__neutralino_globals\.js', '/__neutralino_globals.js'; if ($updated -ne $content) { [System.IO.File]::WriteAllText($path, $updated, [System.Text.UTF8Encoding]::new($false)) }"
if errorlevel 1 (
	echo [WARN] Failed to normalize ui\src\app.html. Continuing dev launch.
)

if exist "%APP_HTML%" (
	copy "%APP_HTML%" "%APP_HTML_BACKUP%" /Y >nul
)

if defined NVM_SYMLINK (
	set "PATH=%NVM_SYMLINK%;%PATH%"
)
if exist "C:\nvm4w\nodejs\node.exe" (
	set "PATH=C:\nvm4w\nodejs;%PATH%"
)

set "NEU_NODE="
set "NEU_JS="

if defined NVM_SYMLINK if exist "%NVM_SYMLINK%\node.exe" if exist "%NVM_SYMLINK%\node_modules\@neutralinojs\neu\bin\neu.js" (
	set "NEU_NODE=%NVM_SYMLINK%\node.exe"
	set "NEU_JS=%NVM_SYMLINK%\node_modules\@neutralinojs\neu\bin\neu.js"
)

if not defined NEU_NODE if exist "C:\nvm4w\nodejs\node.exe" if exist "C:\nvm4w\nodejs\node_modules\@neutralinojs\neu\bin\neu.js" (
	set "NEU_NODE=C:\nvm4w\nodejs\node.exe"
	set "NEU_JS=C:\nvm4w\nodejs\node_modules\@neutralinojs\neu\bin\neu.js"
)

if defined NEU_NODE (
	for %%D in ("%NEU_NODE%") do set "PATH=%%~dpD;%PATH%"
	powershell -NoProfile -ExecutionPolicy Bypass -Command "& '%DEV_NEU_RUNNER%' -Launcher '%NEU_NODE%' -ProjectRoot '%PROJECT_ROOT%' -Arguments '%NEU_JS% run -- --window-enable-inspector'"
	set "NEU_EXIT=%errorlevel%"
	goto restore_app_html
)

set "NEU_CMD="
if exist "%APPDATA%\npm\neu.cmd" set "NEU_CMD=%APPDATA%\npm\neu.cmd"
if not defined NEU_CMD for %%I in (neu.cmd) do if not "%%~$PATH:I"=="" set "NEU_CMD=%%~$PATH:I"
if defined NEU_CMD (
	powershell -NoProfile -ExecutionPolicy Bypass -Command "& '%DEV_NEU_RUNNER%' -Launcher '%NEU_CMD%' -ProjectRoot '%PROJECT_ROOT%' -Arguments 'run -- --window-enable-inspector'"
	set "NEU_EXIT=%errorlevel%"
	goto restore_app_html
)

echo [ERROR] Neutralino CLI "neu" was not found on PATH.
echo [ERROR] Install it globally (npm i -g @neutralinojs/neu) or ensure your Node shim path is available.
set "NEU_EXIT=1"

:restore_app_html
if exist "%APP_HTML_BACKUP%" (
	copy "%APP_HTML_BACKUP%" "%APP_HTML%" /Y >nul
	del /f /q "%APP_HTML_BACKUP%" >nul 2>&1
)

if not defined NEU_EXIT set "NEU_EXIT=0"
exit /b %NEU_EXIT%