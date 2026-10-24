<#
  Installs JARVIS as a desktop app: a separate copy of the `main` branch that updates itself from GitHub.
  Usage:  powershell -ExecutionPolicy Bypass -File .\install-app.ps1 [-AppDir D:\Apps\JARVIS] [-DataDir D:\Apps\JARVIS-data]

  - AppDir  : the app's own code (a git clone of main). Only "Check for updates" in the app changes it.
  - DataDir : .env, logins (browser profiles), history, prefs. Copied once from this folder; updates never touch it.
  Safe to run again: an existing install is kept and only checked (packages, shortcuts).
#>
param(
    [string]$AppDir = 'D:\Apps\JARVIS',
    [string]$DataDir = 'D:\Apps\JARVIS-data'
)

$ErrorActionPreference = 'Stop'
$Src = $PSScriptRoot

function Info($m) { Write-Host "[jarvis-app] $m" -ForegroundColor Cyan }
function Warn($m) { Write-Host "[jarvis-app] $m" -ForegroundColor Yellow }
function Fail($m) { Write-Host "[jarvis-app] ERROR: $m" -ForegroundColor Red; exit 1 }
function Run([string]$exe, [string[]]$argv) {
    & $exe @argv
    if ($LASTEXITCODE -ne 0) { Fail "'$exe $($argv -join ' ')' exited with code $LASTEXITCODE" }
}

# Per-user settings that keep caches on D: (a shell opened before they were set does not have them).
foreach ($name in 'PLAYWRIGHT_BROWSERS_PATH', 'HF_HOME', 'PIP_CACHE_DIR', 'npm_config_cache') {
    $v = [Environment]::GetEnvironmentVariable($name, 'User')
    if ($v -and -not [Environment]::GetEnvironmentVariable($name, 'Process')) { [Environment]::SetEnvironmentVariable($name, $v, 'Process') }
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Fail "Git not found." }
if (Test-Path "$Src\data\pids.json") { Fail "JARVIS is running from this folder. Run .\stop.ps1 first (its browser profiles are copied and must not be in use)." }

# ---------------------------------------------------------------- code: a clone of main
$origin = (& git -C $Src remote get-url origin).Trim()
if (Test-Path "$AppDir\.git") {
    Info "App already installed at $AppDir (updates come from the app: Updates > Check for updates)."
} else {
    if ((Test-Path $AppDir) -and (Get-ChildItem $AppDir -Force | Select-Object -First 1)) { Fail "$AppDir exists and is not empty." }
    Info "Copying the main branch to $AppDir ..."
    Run 'git' @('clone', '--quiet', '--branch', 'main', $Src, $AppDir)
    # Updates are pulled from GitHub, not from this working folder.
    Run 'git' @('-C', $AppDir, 'remote', 'set-url', 'origin', $origin)
    Run 'git' @('-C', $AppDir, 'fetch', '--quiet', 'origin', 'main')
    Run 'git' @('-C', $AppDir, 'branch', '--quiet', '--set-upstream-to=origin/main', 'main')
}
# Settings live in DataDir; this stub stops install.ps1 from creating a second .env from the example.
if (-not (Test-Path "$AppDir\.env")) { Set-Content -Path "$AppDir\.env" -Value "# JARVIS app: settings are in $DataDir\.env" -Encoding UTF8 }

# ---------------------------------------------------------------- data: .env, logins, history
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
if (-not (Test-Path "$DataDir\.env")) {
    if (Test-Path "$Src\.env") { Copy-Item "$Src\.env" "$DataDir\.env"; Info "Copied .env to $DataDir" }
    else { Copy-Item "$Src\.env.example" "$DataDir\.env"; Warn "Created $DataDir\.env from the example; fill your keys there." }
    # Claude Code and UFO keep working on this folder, not on the app's copy.
    $extra = @("", "# Added by install-app.ps1", "CLAUDE_CODE_DIR=$Src", "CLAUDE_CODE_PROJECTS_DIR=$(Split-Path $Src -Parent)")
    if (Test-Path "$Src\vendor\UFO") { $extra += "UFO_DIR=$Src\vendor\UFO" }
    Add-Content -Path "$DataDir\.env" -Value $extra -Encoding UTF8
}
if ((Test-Path "$Src\data") -and -not (Test-Path "$DataDir\profiles")) {
    Info "Copying logins and history to $DataDir (browser profiles, database, prefs)..."
    & robocopy.exe "$Src\data" $DataDir /E /XD logs screenshots webview /XF pids.json /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { Fail "robocopy failed with code $LASTEXITCODE" }
}

# ---------------------------------------------------------------- packages + dashboard (same steps as install.ps1)
Info "Installing the app's Python packages and building its dashboard (first time takes a few minutes)..."
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$AppDir\install.ps1" -Voice -SkipUfo
if ($LASTEXITCODE -ne 0) { Fail "install.ps1 failed (exit $LASTEXITCODE)" }
$venvPy = "$AppDir\backend\.venv\Scripts\python.exe"
Run $venvPy @('-m', 'pip', 'install', '--disable-pip-version-check', '-q', '-r', "$AppDir\backend\requirements-desktop.txt")

# ---------------------------------------------------------------- shortcuts
$shell = New-Object -ComObject WScript.Shell
$targets = @(
    (Join-Path ([Environment]::GetFolderPath('Desktop')) 'JARVIS.lnk'),
    (Join-Path ([Environment]::GetFolderPath('Programs')) 'JARVIS.lnk')
)
foreach ($lnk in $targets) {
    $s = $shell.CreateShortcut($lnk)
    $s.TargetPath = "$AppDir\backend\.venv\Scripts\pythonw.exe"
    $s.Arguments = "-m jarvis.desktop --data `"$DataDir`""
    $s.WorkingDirectory = "$AppDir\backend"
    $s.IconLocation = "$AppDir\assets\jarvis.ico,0"
    $s.Description = 'JARVIS desktop assistant'
    $s.Save()
}
Info "Done. Open JARVIS from the Start menu or the Desktop shortcut."
Info "Code: $AppDir   Data: $DataDir"
Info "To publish an update: merge into main and push to GitHub; then in the app: Updates > Check for updates."
