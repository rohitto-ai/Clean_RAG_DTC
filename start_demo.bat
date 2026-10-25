@echo off
REM Phase 10.5b - double-click launcher for the 3.3L DTC demo (Windows).
REM Bypasses the execution policy for THIS process only; nothing is changed
REM machine-wide and no administrator rights are needed.
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_demo.ps1" %*
if errorlevel 1 (
  echo.
  echo The demo did not start. See docs\report\phase10_5_demo_runbook.md
  pause
)
endlocal
