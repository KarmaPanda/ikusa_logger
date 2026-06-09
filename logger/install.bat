@echo off
setlocal

set "TARGET_VENV=%CD%\.venv"
set "REQ_FILE=requirements.txt"

if not exist ".venv\Scripts\python.exe" (
	echo Creating logger virtual environment...
	python -m venv .venv
	if errorlevel 1 (
		echo Failed to create .venv.
		exit /b 1
	)
) else (
	if defined VIRTUAL_ENV (
		if /I "%VIRTUAL_ENV%"=="%TARGET_VENV%" (
			echo Using already-activated logger venv: %VIRTUAL_ENV%
		) else (
			echo Active venv detected: %VIRTUAL_ENV%
			echo Continuing with logger venv at %TARGET_VENV%
		)
	)
)

".venv\Scripts\python.exe" -m pip install scapy pyinstaller
".venv\Scripts\python.exe" -m pip install --upgrade pip setuptools wheel
if errorlevel 1 (
	echo Failed to upgrade pip tooling.
	exit /b 1
)

if exist "%REQ_FILE%" (
	echo Installing Python dependencies from %REQ_FILE%...
	".venv\Scripts\python.exe" -m pip install -r "%REQ_FILE%"
) else (
	echo %REQ_FILE% not found, using fallback dependencies.
	".venv\Scripts\python.exe" -m pip install scapy pyinstaller
)
if errorlevel 1 (
	echo Failed to install Python dependencies.
	exit /b 1
)

CALL build
