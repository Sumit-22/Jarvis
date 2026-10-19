<#
  Stops processes started by start.ps1 (by saved PIDs, including their child processes).
#>
$Root = $PSScriptRoot
$pidFile = "$Root\data\pids.json"
if (-not (Test-Path $pidFile)) { Write-Host "Nothing to stop (no data\pids.json)."; exit 0 }

$pids = Get-Content $pidFile -Raw | ConvertFrom-Json
foreach ($p in $pids.PSObject.Properties) {
    $proc = Get-Process -Id $p.Value -ErrorAction SilentlyContinue
    if ($proc) {
        # /T also ends children: Playwright's Chromium windows, Vite's node process.
        & taskkill.exe /PID $p.Value /T /F | Out-Null
        Write-Host "Stopped $($p.Name) (PID $($p.Value))"
    } else {
        Write-Host "$($p.Name) (PID $($p.Value)) was not running"
    }
}
Remove-Item $pidFile -Force
