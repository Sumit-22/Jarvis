<#
  M0: read-only machine inspection. Changes nothing. Paste the output into PROGRESS.md (Environment section).
#>
$ErrorActionPreference = 'Continue'
function Try-Run([scriptblock]$b) { try { (& $b 2>$null | Out-String).Trim() } catch { 'not found' } }

$os = Get-CimInstance Win32_OperatingSystem
$cpu = (Get-CimInstance Win32_Processor | Select-Object -First 1).Name
$ramGb = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB, 1)
$freeC = [math]::Round((Get-PSDrive C).Free / 1GB, 1)

"Windows:     $($os.Caption) $($os.Version) (build $($os.BuildNumber))"
"CPU:         $cpu"
"RAM:         $ramGb GB"
"Free on C:   $freeC GB"
"Python (py -0p):"
Try-Run { py -0p }
"Git:         $(Try-Run { git --version })"
"Node:        $(Try-Run { node --version })"
"npm:         $(Try-Run { npm.cmd --version })"
"PowerShell:  $($PSVersionTable.PSVersion)"
"ExecPolicy:  $(Try-Run { Get-ExecutionPolicy -List | Out-String })"
if (Test-Path "$PSScriptRoot\vendor\UFO\.git") {
    "UFO commit:  $(Try-Run { git -C "$PSScriptRoot\vendor\UFO" rev-parse HEAD })"
} else { "UFO:         not cloned yet (install.ps1 clones it)" }
