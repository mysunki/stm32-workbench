@echo off
setlocal
cd /d "%~dp0"
title STM32 Workbench - GitHub publication
python -I -B tools\publish_interactive.py
set "publishExitCode=%ERRORLEVEL%"
echo.
if not "%publishExitCode%"=="0" echo Publication did not complete. See the message above.
pause
exit /b %publishExitCode%
