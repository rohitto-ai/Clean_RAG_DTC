<#
    Phase 10.5b - Windows one-click demo launcher.

    Double-click start_demo.bat (which calls this with -ExecutionPolicy Bypass for
    that one process only). Or, from a PowerShell prompt:

        powershell -ExecutionPolicy Bypass -File .\start_demo.ps1
        powershell -ExecutionPolicy Bypass -File .\start_demo.ps1 -Port 8080

    No administrator rights. No internet, once the environment is installed. No
    language model: every demo path is rule-based, and llama_cpp is imported
    lazily, so the demo runs without the .gguf and without llama-cpp-python. Only
    the optional "add AI one-line summary" checkbox needs them.

    Written for Windows PowerShell 5.1 (what Windows ships) as well as 7.x.
    Setup instructions: docs\report\phase10_5_demo_runbook.md
#>
[CmdletBinding()]
param(
    [int]$Port = 8000,
    [int]$TimeoutSeconds = 120,
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$py       = Join-Path $root '.venv\Scripts\python.exe'
$base     = "http://127.0.0.1:$Port"
$pidFile  = Join-Path $env:TEMP "dtc_demo_$Port.pid"
$runbook  = 'docs\report\phase10_5_demo_runbook.md'

function Write-Step { param([string]$Text) Write-Host "`n>> $Text" -ForegroundColor Cyan }
function Write-Note { param([string]$Text) Write-Host "   $Text" }

function Get-Health {
    param([string]$Url)
    try {
        $r = Invoke-RestMethod -Uri "$Url/health" -TimeoutSec 5 -ErrorAction Stop
        if ($r.status -eq 'ok') { return $r }
        return $null
    } catch {
        return $null
    }
}

Write-Host '============================================================'
Write-Host '  3.3L DTC Diagnostic Assistant - demo launcher (Windows)'
Write-Host '============================================================'

# ---------------------------------------------------------------- 1. the venv
if (-not (Test-Path $py)) {
    Write-Host ''
    Write-Host 'ERROR: the Python environment is missing.' -ForegroundColor Red
    Write-Host "Expected: $py"
    Write-Host ''
    Write-Host 'This laptop has not been set up yet. The offline install takes about'
    Write-Host '10 minutes and needs Python 3.12 (NOT 3.13 or 3.14).'
    Write-Host ''
    Write-Host "Follow section 2 of:  $runbook"
    Write-Host '  py -3.12 -m venv .venv'
    Write-Host '  .\.venv\Scripts\pip install --no-index --find-links wheels -r requirements.txt'
    Write-Host ''
    Read-Host 'Press Enter to close'
    exit 1
}

$pyVersion = & $py -c "import sys; print('%d.%d' % sys.version_info[:2])"
if ($pyVersion -ne '3.12') {
    Write-Host ''
    Write-Host "WARNING: the virtual environment is Python $pyVersion, not 3.12." -ForegroundColor Yellow
    Write-Host 'Several dependencies have no wheels outside 3.12; if the demo fails to'
    Write-Host "start, rebuild the environment with py -3.12. See $runbook"
}

try {
    & $py -c "import pdfplumber, chromadb, rank_bm25, sentence_transformers" 2>$null
    if ($LASTEXITCODE -ne 0) { throw 'import failed' }
} catch {
    Write-Host ''
    Write-Host 'ERROR: core packages are missing from .venv.' -ForegroundColor Red
    Write-Host '  .\.venv\Scripts\pip install --no-index --find-links wheels -r requirements.txt'
    Write-Host "See section 2 of $runbook"
    Read-Host 'Press Enter to close'
    exit 1
}

$env:PYTHONPATH = 'src'
$env:ANONYMIZED_TELEMETRY = 'False'

# ------------------------------------------------------- 2. data and index
if (-not (Test-Path 'index\meta.json')) {
    Write-Step 'Building the search index (about 30 seconds, one time only)...'
    & $py src\build_index.py --rebuild --aliases bm25 --cylinder-token | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'ERROR: the index build failed.' -ForegroundColor Red
        Read-Host 'Press Enter to close'
        exit 1
    }
}
if (-not (Test-Path 'data\demo\synthetic_fleet_log.csv')) {
    Write-Step 'Generating the synthetic demo data (seeded, a few seconds)...'
    & $py scripts\gen_demo_data.py | Out-Null
}
if (-not (Test-Path 'models\qwen2.5-0.5b-instruct-q4_k_m.gguf')) {
    Write-Step 'Running WITHOUT the local language model.'
    Write-Note 'Every demo path is rule-based and works: fleet, vehicle, advisories,'
    Write-Note 'candidates, refusals, verify-code, audit and the symptom search.'
    Write-Note 'Only the optional "add AI one-line summary" checkbox needs the model.'
}

# ------------------------------------------------------- 3. already running?
$existing = Get-Health -Url $base
if ($existing) {
    Write-Step "A demo is already answering on $base - reusing it."
    if (-not $NoBrowser) { Start-Process $base }
    Write-Host ''
    Write-Host "  DEMO READY   $base/" -ForegroundColor Green
    Write-Host '  Stop it with stop_demo.bat'
    Read-Host 'Press Enter to close this window (the demo keeps running)'
    exit 0
}

# ------------------------------------------------------------ 4. start it
Write-Step "Starting the service on 127.0.0.1:$Port in a new window..."
$proc = Start-Process -FilePath $py `
    -ArgumentList '-m', 'uvicorn', 'app:app', '--host', '127.0.0.1', '--port', "$Port", '--log-level', 'warning' `
    -WorkingDirectory $root -PassThru
Set-Content -Path $pidFile -Value $proc.Id -Encoding ASCII
Write-Note "server pid $($proc.Id), pid file $pidFile"

# ------------------------------------------------------ 5. wait for health
Write-Step "Waiting for the service to answer (up to $TimeoutSeconds s)..."
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
$health = $null
while ((Get-Date) -lt $deadline) {
    if ($proc.HasExited) {
        Write-Host ''
        Write-Host "ERROR: the server exited during start-up (code $($proc.ExitCode))." -ForegroundColor Red
        Write-Host 'Run this to see the error:'
        Write-Host "  .\.venv\Scripts\python -m uvicorn app:app --host 127.0.0.1 --port $Port"
        Remove-Item $pidFile -ErrorAction SilentlyContinue
        Read-Host 'Press Enter to close'
        exit 1
    }
    $health = Get-Health -Url $base
    if ($health) { break }
    Start-Sleep -Seconds 2
}

if (-not $health) {
    Write-Host ''
    Write-Host "ERROR: the demo did not become healthy on $base within $TimeoutSeconds s." -ForegroundColor Red
    Write-Host 'The first start on a cold machine can be slower; try again, or run'
    Write-Host "  .\.venv\Scripts\python -m uvicorn app:app --host 127.0.0.1 --port $Port"
    Write-Host "to see the error directly. See the panic section of $runbook"
    Read-Host 'Press Enter to close'
    exit 1
}
Write-Note "health ok - startup $($health.startup_seconds)s, hash $($health.determinism_hash)"
Write-Note "records $($health.counts.records), vectors $($health.counts.vectors), rows $($health.counts.log_rows_in_scope)"

# ---------------------------------------------------------- 6. warm it up
Write-Step 'Warming the models (first retrieval pays the embedding cost)...'
try {
    $body = @{ query = 'rail pressure sensor short to ground'; summary = $false } | ConvertTo-Json
    $t = Get-Date
    $s = Invoke-RestMethod -Uri "$base/symptom" -Method Post -Body $body `
                           -ContentType 'application/json' -TimeoutSec 180
    $ms = [int]((Get-Date) - $t).TotalMilliseconds
    Write-Note ("/symptom warm : {0,6} ms  -> {1}" -f $ms, (($s.results | ForEach-Object { $_.code_full }) -join ', '))

    $t = Get-Date
    $v = Invoke-RestMethod -Uri "$base/vehicle/DEMO-MAT-0001" -TimeoutSec 180
    $ms = [int]((Get-Date) - $t).TotalMilliseconds
    Write-Note ("/vehicle warm : {0,6} ms  -> {1}, {2} episode(s)" -f $ms, $v.worst_severity, $v.episodes.Count)
} catch {
    Write-Host "WARNING: a warm-up call failed ($($_.Exception.Message))." -ForegroundColor Yellow
    Write-Host 'The service is up; the first click in the UI will just be slower.'
}

# --------------------------------------------------------- 7. open browser
if (-not $NoBrowser) {
    Write-Step "Opening $base in your browser..."
    Start-Process $base
}

Write-Host ''
Write-Host '============================================================'
Write-Host "  DEMO READY     $base/" -ForegroundColor Green
Write-Host '  server window  the separate python window this script opened'
Write-Host '                 (its output IS the server log; leave it open)'
Write-Host '  stop           double-click stop_demo.bat'
Write-Host '  pre-flight     .\.venv\Scripts\python scripts\demo_smoke.py --base ' -NoNewline
Write-Host $base
Write-Host '============================================================'
Write-Host ''
Read-Host 'Press Enter to close this window (the demo keeps running)'
