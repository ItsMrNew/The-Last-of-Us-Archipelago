@echo off
cd /d "%~dp0"
.venv\Scripts\python.exe tools\local_game.py host
pause
