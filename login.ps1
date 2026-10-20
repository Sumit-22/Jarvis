<#
  One-time manual login. Opens JARVIS's two browser profiles (main, side) in Playwright's Chromium
  WITHOUT automation, so Google / LeetCode / claude.ai accept a normal sign-in. JARVIS reuses the
  saved logins afterwards. JARVIS must be stopped (a profile can only be open in one browser).
  Usage:  powershell -ExecutionPolicy Bypass -File .\login.ps1
#>
$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
$venvPy = "$Root\backend\.venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) { Write-Host "Backend venv missing. Run .\install.ps1 first." -ForegroundColor Red; exit 1 }
if (Test-Path "$Root\data\pids.json") { Write-Host "JARVIS is running. Run .\stop.ps1 first, then this script." -ForegroundColor Yellow; exit 1 }

# Same Chromium build JARVIS drives, so the profile format matches.
$chrome = (& $venvPy -c "from playwright.sync_api import sync_playwright as s; p = s().start(); print(p.chromium.executable_path); p.stop()").Trim()
if ($LASTEXITCODE -ne 0 -or -not (Test-Path $chrome)) { Write-Host "Playwright Chromium not found. Run .\install.ps1 first." -ForegroundColor Red; exit 1 }

$windows = [ordered]@{
    main = @('https://accounts.google.com/', 'https://www.youtube.com/', 'https://leetcode.com/accounts/login/')
    side = @('https://claude.ai/login')
}
$procs = @()
foreach ($name in $windows.Keys) {
    $profile = "$Root\data\profiles\$name"
    New-Item -ItemType Directory -Force -Path $profile | Out-Null
    $argv = @("--user-data-dir=`"$profile`"", '--no-first-run', '--no-default-browser-check', '--new-window') + $windows[$name]
    $procs += Start-Process -FilePath $chrome -ArgumentList $argv -PassThru
}
Write-Host "Log in by hand:" -ForegroundColor Cyan
Write-Host "  main window: Google/YouTube and LeetCode (one tab each)"
Write-Host "  side window: claude.ai"
Write-Host "Then CLOSE both windows (this saves the logins). Waiting..."
$procs | Wait-Process
Write-Host "Done. Start JARVIS with .\start.ps1" -ForegroundColor Cyan
