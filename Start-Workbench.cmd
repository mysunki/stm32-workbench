@echo off
setlocal
cd /d "%~dp0"
python -I -B run.py gui
if errorlevel 1 pause
