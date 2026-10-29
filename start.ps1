# SkyCast AI - launcher that always works from any directory.
# Uses THIS script's location so paths survive folder moves/copies.
# Auto-picks a free port and opens the browser once the server is up.

$BASE = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $BASE

$PIDFILE = Join-Path $BASE "skycast.pid"
$OUTLOG  = Join-Path $BASE "skycast-out.log"
$ERRLOG  = Join-Path $BASE "skycast-err.log"

# ---- pick the first free browser-safe port (avoid 5060/5061: browsers block them) ----
$candidates = @(8080, 8000, 3000, 5001, 5050, 8060, 8099)
$PORT = $null
foreach ($p in $candidates) {
    if (-not (Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue)) {
        $PORT = $p
        break
    }
}
if (-not $PORT) { Write-Host "No free port found - close something and retry." -ForegroundColor Red; return }

$URL = "http://127.0.0.1:$PORT"

# ---- already running? just reopen the browser ----
if ((Test-Path $PIDFILE) -and (Get-Process -Id (Get-Content $PIDFILE).Trim() -ErrorAction SilentlyContinue)) {
    Write-Host "SkyCast AI is already running -> $URL" -ForegroundColor Green
    Start-Process $URL
    return
}

$env:SKYCAST_PORT = "$PORT"
$p = Start-Process python -ArgumentList "app.py" -WorkingDirectory $BASE `
    -PassThru -WindowStyle Hidden `
    -RedirectStandardOutput $OUTLOG `
    -RedirectStandardError  $ERRLOG
$p.Id | Set-Content $PIDFILE

Write-Host "Starting SkyCast AI (PID $($p.Id))..." -ForegroundColor Cyan
Start-Sleep 5
try {
    $r = Invoke-WebRequest $URL -UseBasicParsing -TimeoutSec 15
    Write-Host "SkyCast AI is live -> $URL  (status $($r.StatusCode))" -ForegroundColor Green
    Start-Process $URL
} catch {
    Write-Host "Server check failed: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Tip: try http://127.0.0.1 instead of localhost - some systems map" -ForegroundColor Yellow
}