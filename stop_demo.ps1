<#
    Phase 10.5b - stop the Windows demo server.

    Double-click stop_demo.bat, or:
        powershell -ExecutionPolicy Bypass -File .\stop_demo.ps1 [-Port 8000]

    Stops ONLY the server started by start_demo.ps1: the pid file written at start
    identifies it, and the process is confirmed to be that python before anything
    is sent. Any other python on the machine is left alone.
#>
[CmdletBinding()]
param(
    [int]$Port = 8000
)

$ErrorActionPreference = 'Stop'
$pidFile = Join-Path $env:TEMP "dtc_demo_$Port.pid"

Write-Host '============================================================'
Write-Host "  Stopping the demo server on port $Port"
Write-Host '============================================================'

if (-not (Test-Path $pidFile)) {
    Write-Host "No demo server was started by start_demo on port $Port (no $pidFile)."
    try {
        $r = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 3 -ErrorAction Stop
        if ($r.status -eq 'ok') {
            Write-Host ''
            Write-Host "Something else IS answering on port $Port. It was not started by" -ForegroundColor Yellow
            Write-Host 'these scripts, so it is left alone. Close its window to stop it.'
        }
    } catch {
        # nothing listening: nothing to do
    }
    Read-Host 'Press Enter to close'
    exit 0
}

$serverPid = (Get-Content $pidFile -Raw).Trim()
$proc = Get-Process -Id $serverPid -ErrorAction SilentlyContinue
if (-not $proc) {
    Remove-Item $pidFile -ErrorAction SilentlyContinue
    Write-Host "The demo server on port $Port is already stopped."
    Read-Host 'Press Enter to close'
    exit 0
}

if ($proc.ProcessName -notmatch '^python') {
    Write-Host "PID $serverPid is '$($proc.ProcessName)', not the demo server. Leaving it alone." -ForegroundColor Yellow
    Remove-Item $pidFile -ErrorAction SilentlyContinue
    Read-Host 'Press Enter to close'
    exit 1
}

Stop-Process -Id $serverPid -ErrorAction SilentlyContinue
for ($i = 0; $i -lt 20; $i++) {
    if (-not (Get-Process -Id $serverPid -ErrorAction SilentlyContinue)) { break }
    Start-Sleep -Milliseconds 250
}
if (Get-Process -Id $serverPid -ErrorAction SilentlyContinue) {
    Stop-Process -Id $serverPid -Force -ErrorAction SilentlyContinue
}
Remove-Item $pidFile -ErrorAction SilentlyContinue

Write-Host "Demo server on port $Port stopped (pid $serverPid)." -ForegroundColor Green
Read-Host 'Press Enter to close'
