<#
  JARVIS installer. Idempotent, no admin, never changes system settings.
  Usage:  powershell -ExecutionPolicy Bypass -File .\install.ps1 [-Voice] [-SkipUfo]
#>
param(
    [switch]$Voice,    # also install faster-whisper (M6)
    [switch]$SkipUfo   # skip cloning/installing Microsoft UFO2
)

$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
Set-Location $Root

function Info($m) { Write-Host "[jarvis] $m" -ForegroundColor Cyan }
function Warn($m) { Write-Host "[jarvis] $m" -ForegroundColor Yellow }
function Fail($m) { Write-Host "[jarvis] ERROR: $m" -ForegroundColor Red; exit 1 }

# Run a native command and stop on a non-zero exit code (PowerShell 5.1 does not do this itself).
function Run([string]$exe, [string[]]$argv) {
    & $exe @argv
    if ($LASTEXITCODE -ne 0) { Fail "'$exe $($argv -join ' ')' exited with code $LASTEXITCODE" }
}

# Returns the path of python.exe for the first listed version the py launcher knows, or $null.
function Find-Python([string[]]$versions) {
    if (-not (Get-Command py -ErrorAction SilentlyContinue)) { return $null }
    $ErrorActionPreference = 'Continue'  # PS 5.1 turns redirected native stderr into terminating errors under 'Stop'
    foreach ($v in $versions) {
        $exe = & py "-$v" -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $exe) { return $exe.Trim() }
    }
    return $null
}

# ---------------------------------------------------------------- prerequisites
Info "Checking prerequisites..."
$py = Find-Python @('3.12', '3.11')
if (-not $py) { Fail "Python 3.12 or 3.11 not found. Install it from https://www.python.org/downloads/windows/ (tick 'py launcher'), then re-run." }
Info "Python for JARVIS: $py"

if (-not (Get-Command node -ErrorAction SilentlyContinue)) { Fail "Node.js not found. Install Node 20+ LTS from https://nodejs.org/ then re-run." }
$nodeMajor = [int]((& node --version).TrimStart('v').Split('.')[0])
if ($nodeMajor -lt 20) { Fail "Node $nodeMajor found; Node 20+ is required. Install the LTS from https://nodejs.org/" }
if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) { Fail "npm not found (it ships with Node.js)." }
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Fail "Git not found. Install it from https://git-scm.com/download/win then re-run." }

# ---------------------------------------------------------------- folders + .env
foreach ($d in 'data', 'data\logs', 'data\profiles') { New-Item -ItemType Directory -Force -Path (Join-Path $Root $d) | Out-Null }
if (-not (Test-Path "$Root\.env")) {
    Copy-Item "$Root\.env.example" "$Root\.env"
    Info "Created .env from .env.example (fill your keys there, never in chat)."
}

# ---------------------------------------------------------------- backend venv
$venvPy = "$Root\backend\.venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    Info "Creating backend venv..."
    Run $py @('-m', 'venv', "$Root\backend\.venv")
}
Info "Installing Python dependencies..."
Run $venvPy @('-m', 'pip', 'install', '--disable-pip-version-check', '-q', '--upgrade', 'pip')
Run $venvPy @('-m', 'pip', 'install', '--disable-pip-version-check', '-q', '-r', "$Root\backend\requirements-dev.txt")
if ($Voice) {
    Info "Installing voice dependencies (faster-whisper)..."
    Run $venvPy @('-m', 'pip', 'install', '--disable-pip-version-check', '-q', '-r', "$Root\backend\requirements-voice.txt")
}
Info "Installing Playwright Chromium (per-user, no admin)..."
Run $venvPy @('-m', 'playwright', 'install', 'chromium')

# ---------------------------------------------------------------- frontend
Info "Installing and building the dashboard..."
Push-Location "$Root\frontend"
try {
    if (Test-Path 'package-lock.json') { Run 'npm.cmd' @('ci', '--no-audit', '--no-fund') }
    else { Run 'npm.cmd' @('install', '--no-audit', '--no-fund') }
    Run 'npm.cmd' @('run', 'build')
} finally { Pop-Location }

# ---------------------------------------------------------------- Microsoft UFO2 (own venv)
if ($SkipUfo) {
    Warn "Skipping UFO2 (-SkipUfo). Set UFO_ENABLED=false in .env."
} else {
    $ufoDir = "$Root\vendor\UFO"
    if (-not (Test-Path "$ufoDir\.git")) {
        Info "Cloning Microsoft UFO into vendor\UFO..."
        New-Item -ItemType Directory -Force -Path "$Root\vendor" | Out-Null
        Run 'git' @('clone', 'https://github.com/microsoft/UFO.git', $ufoDir)
    }
    # UFO's README badge lists Python 3.10 | 3.11.
    $ufoPy = Find-Python @('3.11', '3.10')
    if (-not $ufoPy) {
        Warn "UFO2 needs Python 3.11 or 3.10 (per its README). Install 3.11 from https://www.python.org/downloads/windows/ and re-run. Skipping UFO for now."
    } else {
        $ufoVenvPy = "$ufoDir\.venv\Scripts\python.exe"
        if (-not (Test-Path $ufoVenvPy)) {
            Info "Creating UFO venv with $ufoPy ..."
            Run $ufoPy @('-m', 'venv', "$ufoDir\.venv")
        }
        Info "Installing UFO requirements (this can take a while)..."
        # UFO pins pandas==1.4.3, which has no Python 3.11 wheel and fails to build from source
        # (its setup.py needs pkg_resources). 1.5.3 is the oldest pandas with 3.11 wheels.
        # Patch a copy inside the venv so vendor\UFO itself stays unmodified.
        $ufoReq = "$ufoDir\.venv\jarvis-requirements.txt"
        (Get-Content "$ufoDir\requirements.txt") -replace '^pandas==1\.4\.3\s*$', 'pandas==1.5.3' | Set-Content -Encoding ASCII $ufoReq
        Run $ufoVenvPy @('-m', 'pip', 'install', '--disable-pip-version-check', '-q', '--prefer-binary', '-r', $ufoReq)
        $cfg = "$ufoDir\config\ufo\agents.yaml"
        if (-not (Test-Path $cfg)) {
            Copy-Item "$ufoDir\config\ufo\agents.yaml.template" $cfg
            Warn "Created vendor\UFO\config\ufo\agents.yaml. Open it yourself and fill API_TYPE / API_BASE / API_KEY / API_MODEL."
            Warn "JARVIS never reads, prints or copies that key."
        }
    }
}

Info "Install finished. Next: .\start.ps1"
