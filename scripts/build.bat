@echo off
setlocal EnableExtensions
set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "PROJECT_ROOT=%%~fI"
cd /d "%PROJECT_ROOT%"

:: Close running app/helper processes so build outputs are not locked.
echo [INFO] Closing running Ikusa Logger processes...
for %%P in (
	"ikusa-logger-win_x64.exe"
	"ikusa-logger.exe"
	"logger.exe"
) do (
	taskkill /F /IM %%~P >nul 2>&1
)

:: Build the logger
cd logger
CALL install.bat
if errorlevel 1 exit /b %errorlevel%

:: Copy everything from logger/dist/logger to dist/ikusa-logger/logger/
cd .. 
if not exist "logger\dist\logger\logger.exe" (
	echo [ERROR] Missing built logger payload: logger\dist\logger\logger.exe
	exit /b 1
)
if exist "dist\ikusa-logger\logger" rmdir /s /q "dist\ikusa-logger\logger"
if not exist "dist\ikusa-logger\logger" mkdir "dist\ikusa-logger\logger"
xcopy logger\dist\logger dist\ikusa-logger\logger\ /E /Y /I



:: Install Dependencies for the Frontend
cd ui 
CALL npm i

CALL npm i -g @neutralinojs/neu@11.3.1

:: Patch app.html BEFORE neu update to prevent localhost URLs
cd .. 
PowerShell -NoProfile -ExecutionPolicy Bypass -Command "$path = Resolve-Path '.\ui\src\app.html'; $content = Get-Content $path -Raw; $updated = $content -replace 'http://localhost:\d+/__neutralino_globals\.js', '/__neutralino_globals.js'; if ($updated -ne $content) { [System.IO.File]::WriteAllText($path, $updated, [System.Text.UTF8Encoding]::new($false)) }"

:: Compile the program
set "NEU_UPDATE_LOG=%TEMP%\ikusa-neu-update.log"
if exist "%NEU_UPDATE_LOG%" del /f /q "%NEU_UPDATE_LOG%"

CALL neu update > "%NEU_UPDATE_LOG%" 2>&1
if errorlevel 1 (
	set "NEU_UPDATE_EXIT=%errorlevel%"
	findstr /I /C:"End of central directory record signature not found" "%NEU_UPDATE_LOG%" >nul
	if not errorlevel 1 (
		echo [WARN] Neutralino update cache looks corrupted. Retrying with cache cleanup...
		CALL :recover_neu_update_cache
		CALL neu update > "%NEU_UPDATE_LOG%" 2>&1
		set "NEU_UPDATE_EXIT=%errorlevel%"
	)
	type "%NEU_UPDATE_LOG%"
	if not "%NEU_UPDATE_EXIT%"=="0" exit /b %NEU_UPDATE_EXIT%
)

CALL neu build
if errorlevel 1 exit /b %errorlevel%

:: Ensure final packaged app includes the freshly built logger helper.
if exist "dist\ikusa-logger\logger" rmdir /s /q "dist\ikusa-logger\logger"
if not exist "dist\ikusa-logger\logger" mkdir "dist\ikusa-logger\logger"
xcopy logger\dist\logger dist\ikusa-logger\logger\ /E /Y /I
if not exist "dist\ikusa-logger\logger\logger.exe" (
	echo [ERROR] Final packaged app is missing logger\logger.exe
	exit /b 1
)

:: Keep distribution Windows-only to reduce package size.
for %%F in (
	"dist\ikusa-logger\ikusa-logger-linux_arm64"
	"dist\ikusa-logger\ikusa-logger-linux_armhf"
	"dist\ikusa-logger\ikusa-logger-linux_x64"
	"dist\ikusa-logger\ikusa-logger-mac_arm64"
	"dist\ikusa-logger\ikusa-logger-mac_universal"
	"dist\ikusa-logger\ikusa-logger-mac_x64"
) do (
	if exist %%~F del /f /q %%~F
)

:: Patch build output files in case they still contain localhost URLs
PowerShell -NoProfile -ExecutionPolicy Bypass -Command "Get-ChildItem '.\ui\build\*.html' -ErrorAction SilentlyContinue | ForEach-Object { $content = Get-Content $_.FullName -Raw; $updated = $content -replace 'http://localhost:\d+/__neutralino_globals\.js', '/__neutralino_globals.js'; if ($updated -ne $content) { [System.IO.File]::WriteAllText($_.FullName, $updated, [System.Text.UTF8Encoding]::new($false)) } }"
copy config.ini dist\ikusa-logger\config.ini /Y
if exist dist\ikusa-logger\config.ini.bak del /f /q dist\ikusa-logger\config.ini.bak
copy scripts\update.bat dist\ikusa-logger\update.bat /Y
copy scripts\update.ps1 dist\ikusa-logger\update.ps1 /Y
copy scripts\check-update.bat dist\ikusa-logger\check-update.bat /Y
copy scripts\check-update.ps1 dist\ikusa-logger\check-update.ps1 /Y

echo Build completed. Compiled files are in dist/ikusa-logger/
exit /b 0

:recover_neu_update_cache
for %%D in (
	"%LOCALAPPDATA%\neutralinojs"
	"%LOCALAPPDATA%\Neutralinojs"
	"%USERPROFILE%\.neutralinojs"
	"%TEMP%\neutralinojs"
	"%TEMP%\neu"
) do (
	if exist %%~D (
		echo [INFO] Removing %%~D
		rmdir /s /q %%~D
	)
)

for %%F in (
	"bin\neutralino-linux_arm64"
	"bin\neutralino-linux_armhf"
	"bin\neutralino-linux_x64"
	"bin\neutralino-mac_arm64"
	"bin\neutralino-mac_universal"
	"bin\neutralino-mac_x64"
	"bin\neutralino-win_arm64.exe"
	"bin\neutralino-win_x64.exe"
) do (
	if exist %%~F del /f /q %%~F
)

CALL npm i -g @neutralinojs/neu@11.3.1
exit /b %errorlevel%