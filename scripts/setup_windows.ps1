param([switch]$SkipModels, [switch]$Dev)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $root
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $root '.tools\python'
$env:UV_LINK_MODE = 'copy'
New-Item -ItemType Directory -Force .tools | Out-Null

function Invoke-Checked {
    param([string]$Program, [string[]]$Arguments)
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Program failed with exit code $LASTEXITCODE" }
}

function Get-VerifiedArchive {
    param([string]$Url, [string]$Path, [string]$Sha256)
    Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $Path
    if ((Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash -ne $Sha256) {
        throw "Download checksum mismatch: $Path"
    }
}

if (!(Test-Path .tools\uv.exe)) {
    Get-VerifiedArchive 'https://github.com/astral-sh/uv/releases/download/0.13.4/uv-x86_64-pc-windows-msvc.zip' '.tools\uv.zip' 'CCEC7508A07D9933D7CB1261880633EFCF1F30D6E6EDDAB21823F1DAE6F23225'
    Expand-Archive -LiteralPath .tools\uv.zip -DestinationPath .tools -Force
}
$python = Join-Path $env:UV_PYTHON_INSTALL_DIR 'cpython-3.12.12-windows-x86_64-none\python.exe'
if (!(Test-Path -LiteralPath $python)) {
    Invoke-Checked '.tools\uv.exe' @('python', 'install', '3.12.12', '--no-bin', '--no-registry')
}
$sync = @('sync', '--frozen', '--extra', 'mesh', '--extra', 'mask', '--python', $python)
if ($Dev) { $sync += @('--extra', 'dev') }
Invoke-Checked '.tools\uv.exe' $sync

if (!(Test-Path SpookyNeuro.exe) -and !(Test-Path .tools\godot.exe)) {
    Get-VerifiedArchive 'https://github.com/godotengine/godot-builds/releases/download/4.7.2-stable/Godot_v4.7.2-stable_win64.exe.zip' '.tools\godot-win.zip' '731980F9608D61333E5BAF54A2EF17210ACC7A538446C0CB9969F002ACA1E953'
    Expand-Archive -LiteralPath .tools\godot-win.zip -DestinationPath .tools -Force
    Copy-Item -LiteralPath .tools\Godot_v4.7.2-stable_win64.exe -Destination .tools\godot.exe
}
if (!(Test-Path .tools\TripoSR\tsr\system.py)) {
    $revision = '107cefdc244c39106fa830359024f6a2f1c78871'
    Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/VAST-AI-Research/TripoSR/archive/$revision.zip" -OutFile .tools\triposr.zip
    Expand-Archive -LiteralPath .tools\triposr.zip -DestinationPath .tools -Force
    # Move one known source directory; never recursively move a computed workspace root.
    $source = Join-Path $root ".tools\TripoSR-$revision"
    $destination = Join-Path $root '.tools\TripoSR'
    if (!(Test-Path $destination)) { New-Item -ItemType Directory $destination | Out-Null }
    Copy-Item -Path "$source\*" -Destination $destination -Recurse -Force
}
if (!(Test-Path SpookyNeuro.exe)) {
    Invoke-Checked '.tools\godot.exe' @('--headless', '--path', 'godot', '--editor', '--import', '--quit')
}
if (!$SkipModels) {
    Invoke-Checked '.venv\Scripts\python.exe' @('scripts\download_models.py')
    Invoke-Checked '.venv\Scripts\python.exe' @('scripts\doctor.py')
    Set-Content -LiteralPath .tools\windows-ready -Value 'Python 3.12.12; CUDA 12.8; Godot 4.7.2' -Encoding ascii
}
Write-Host 'Ready. Run Start SpookyNeuro.cmd.'
