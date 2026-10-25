@echo off
REM Phase 10.5b - stop the demo started by start_demo.bat (that server only).
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop_demo.ps1" %*
endlocal
