<#
  Starts the JARVIS backend on 127.0.0.1:8765 (and the Vite dev server with -Dev).
  Usage:  powershell -ExecutionPolicy Bypass -File .\start.ps1 [-Dev] [-NoBrowser]
#>
param([switch]$Dev, [switch]$NoBrowser)

$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
$pidFile = "$Root\data\pids.json"
$logs = "$Root\data\logs"
New-Item -ItemType Directory -Force -Path $logs | Out-Null

$venvPy = "$Root\backend\.venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) { Write-Host "Backend venv missing. Run .\install.ps1 first." -ForegroundColor Red; exit 1 }
if (Test-Path $pidFile) { Write-Host "JARVIS seems to be running already (data\pids.json exists). Run .\stop.ps1 first." -ForegroundColor Yellow; exit 1 }

$pids = @{}
$backend = Start-Process -FilePath $venvPy -ArgumentList '-m', 'jarvis.main' -WorkingDirectory "$Root\backend" `
    -RedirectStandardOutput "$logs\backend.out.log" -RedirectStandardError "$logs\backend.err.log" -WindowStyle Hidden -PassThru
$pids.backend = $backend.Id

if ($Dev) {
    $vite = Start-Process -FilePath 'npm.cmd' -ArgumentList 'run', 'dev' -WorkingDirectory "$Root\frontend" `
        -RedirectStandardOutput "$logs\vite.out.log" -RedirectStandardError "$logs\vite.err.log" -WindowStyle Hidden -PassThru
    $pids.vite = $vite.Id
}
$pids | ConvertTo-Json | Set-Content -Encoding UTF8 $pidFile

$ok = $false
for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Milliseconds 500
    try {
        $r = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8765/api/health' -TimeoutSec 2
        if ($r.StatusCode -eq 200) { $ok = $true; break }
    } catch { }
    if ($backend.HasExited) { break }
}
if (-not $ok) {
    Write-Host "Backend did not become healthy. See data\logs\backend.err.log" -ForegroundColor Red
    & "$Root\stop.ps1"
    exit 1
}
$url = if ($Dev) { 'http://127.0.0.1:5173' } else { 'http://127.0.0.1:8765' }
Write-Host "JARVIS is up: $url  (GET /api/health = 200)" -ForegroundColor Cyan
if (-not $NoBrowser) { Start-Process $url }
