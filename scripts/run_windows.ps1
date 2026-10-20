param([switch]$Offline, [Parameter(ValueFromRemainingArguments=$true)][string[]]$GameArguments)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $root
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:SPOOKY_ROOT = $root
try {
    if ($Offline) {
        $game = if (Test-Path SpookyNeuro.exe) { Join-Path $root 'SpookyNeuro.exe' } else { Join-Path $root '.tools\godot.exe' }
        if (!(Test-Path -LiteralPath $game)) { throw 'Run scripts\setup_windows.ps1 first.' }
        $engineArguments = if (Test-Path SpookyNeuro.exe) { @() } else { @('--path', (Join-Path $root 'godot')) }
        & $game @engineArguments -- --offline @GameArguments
    } else {
        if (!(Test-Path .venv\Scripts\python.exe) -or !(Test-Path .tools\windows-ready)) {
            & (Join-Path $PSScriptRoot 'setup_windows.ps1')
        }
        & .venv\Scripts\python.exe scripts\launch_3d.py @GameArguments
    }
    exit $LASTEXITCODE
} catch {
    Write-Error $_
    exit 1
}
