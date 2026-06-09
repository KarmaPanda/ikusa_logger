@echo off
setlocal EnableExtensions

cd /d "%~dp0"

set "SKIP_BUILD=0"
if /I "%~1"=="--no-build" set "SKIP_BUILD=1"
if /I "%~1"=="-n" set "SKIP_BUILD=1"

if "%SKIP_BUILD%"=="1" (
	echo [INFO] Skipping build ^(no-build mode^).
) else (
	echo [INFO] Building latest artifacts before packaging...
	call "%~dp0build.bat"
	if errorlevel 1 (
		echo [ERROR] build.bat failed. Deployment package was not created.
		exit /b %errorlevel%
	)
)

echo [INFO] Syncing version manifest and updater resources...
call "%~dp0sync-version-manifest.bat"
if errorlevel 1 (
	echo [ERROR] Failed to sync version-manifest.json and resources.neu.
	exit /b %errorlevel%
)

set "PACKAGE_NAME=ikusa-logger"
set "DIST_ROOT=%~dp0dist"
set "DIST_DIR=%DIST_ROOT%\%PACKAGE_NAME%"

if not exist "%DIST_DIR%" (
	echo [ERROR] Distribution folder was not found: "%DIST_DIR%"
	exit /b 1
)

if not exist "%DIST_DIR%\logger\logger.exe" (
	echo [ERROR] Packaged logger payload was not found: "%DIST_DIR%\logger\logger.exe"
	exit /b 1
)

for /f "usebackq delims=" %%V in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "$config = Get-Content '.\neutralino.config.json' -Raw | ConvertFrom-Json; [Console]::Write($config.version)"`) do set "VERSION=%%V"

if not defined VERSION (
	echo [ERROR] Failed to read version from neutralino.config.json.
	exit /b 1
)

set "ISS_FILE=%~dp0build-setup.iss"
if not exist "%ISS_FILE%" (
	echo [ERROR] Installer script was not found: "%ISS_FILE%"
	exit /b 1
)

echo [INFO] Syncing installer script version to %VERSION%...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference = 'Stop'; $path = '%ISS_FILE%'; $version = '%VERSION%'; $found = $false; $updated = foreach ($line in Get-Content $path) { if (-not $found -and $line -match '^(\s*)#define MyAppVersion\s+') { $found = $true; ($matches[1] + '#define MyAppVersion ' + [char]34 + $version + [char]34) } else { $line } }; if (-not $found) { throw 'Failed to locate #define MyAppVersion in build-setup.iss.' }; Set-Content -Path $path -Value $updated -Encoding UTF8"
if errorlevel 1 (
	echo [ERROR] Failed to sync build-setup.iss version.
	exit /b 1
)

set "INSTALLER_PATH=%DIST_ROOT%\ikusa-logger-installer.exe"
set "ZIP_PATH=%DIST_ROOT%\%PACKAGE_NAME%-%VERSION%.zip"
set "STAGE_ROOT=%TEMP%\%PACKAGE_NAME%-deploy-%RANDOM%%RANDOM%"
set "STAGE_DIR=%STAGE_ROOT%\%PACKAGE_NAME%"

if exist "%STAGE_ROOT%" rmdir /s /q "%STAGE_ROOT%"
mkdir "%STAGE_DIR%" >nul 2>&1

echo [INFO] Preparing staging folder...
robocopy "%DIST_DIR%" "%STAGE_DIR%" /E /R:1 /W:1 /NFL /NDL /NJH /NJS /NP /XD .tmp .storage logger\.tmp logger\.storage /XF *.tmp record-session-recovery.json
set "ROBOCOPY_EXIT=%ERRORLEVEL%"
if %ROBOCOPY_EXIT% GEQ 8 (
	echo [ERROR] Failed to stage distribution files. Robocopy exit code: %ROBOCOPY_EXIT%
	if exist "%STAGE_ROOT%" rmdir /s /q "%STAGE_ROOT%"
	exit /b %ROBOCOPY_EXIT%
)

if exist "%ZIP_PATH%" del /f /q "%ZIP_PATH%"

echo [INFO] Creating archive: "%ZIP_PATH%"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -Path '%STAGE_DIR%' -DestinationPath '%ZIP_PATH%' -Force"
if errorlevel 1 (
	echo [ERROR] Failed to create archive.
	if exist "%STAGE_ROOT%" rmdir /s /q "%STAGE_ROOT%"
	exit /b 1
)

if exist "%STAGE_ROOT%" rmdir /s /q "%STAGE_ROOT%"

echo [INFO] Deployment package created successfully.
echo [INFO] Output: "%ZIP_PATH%"

echo [INFO] Compiling installer...
set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
	echo [WARN] Inno Setup 6 not found. Skipping installer build.
	exit /b 0
)

echo [INFO] Removing non-distributable runtime folders from dist root...
if exist "%DIST_DIR%\.tmp" rmdir /s /q "%DIST_DIR%\.tmp"
if exist "%DIST_DIR%\.storage" rmdir /s /q "%DIST_DIR%\.storage"

if exist "%INSTALLER_PATH%" del /f /q "%INSTALLER_PATH%"
"%ISCC%" "/DMyAppVersion=%VERSION%" "/O%DIST_ROOT%" "%~dp0build-setup.iss"
if errorlevel 1 (
	echo [ERROR] Inno Setup compilation failed.
	exit /b 1
)
echo [INFO] Installer created: "%INSTALLER_PATH%"
exit /b 0