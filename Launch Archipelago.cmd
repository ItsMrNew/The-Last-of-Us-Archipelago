@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Run Setup Client.cmd first.
  pause
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" -m tlou_ap.launcher
