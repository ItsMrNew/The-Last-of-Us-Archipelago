@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" "tools\save_pack.py" install "dist\testing\TLOU-Main-Story-Test-Saves.zip"
pause
