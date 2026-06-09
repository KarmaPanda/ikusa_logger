@echo off
if exist ".venv\Scripts\pyinstaller.exe" (
	".venv\Scripts\pyinstaller.exe" logger.spec -y
) else (
	pyinstaller logger.spec -y
)