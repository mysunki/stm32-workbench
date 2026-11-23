@echo off
setlocal
cd /d "%~dp0"
title STM32 Workbench - fresh environment verification
python -I -B tools\verify_from_scratch.py --output "local\verify-%RANDOM%-%RANDOM%"
set "verifyExitCode=%ERRORLEVEL%"
echo.
if "%verifyExitCode%"=="0" (echo Desktop verification passed. Results and screenshots are in the printed output folder.) else (echo Verification failed. See the message and preserved logs above.)
pause
exit /b %verifyExitCode%
