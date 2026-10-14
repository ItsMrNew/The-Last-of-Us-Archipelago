@echo off
cd /d "%~dp0"
py -3.12 -m venv .venv
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe -m pip install -e .
if errorlevel 1 exit /b 1
echo Setup complete. Use Launch Archipelago.cmd.
pause
