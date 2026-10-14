@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" "tools\save_pack.py" restore
pause
