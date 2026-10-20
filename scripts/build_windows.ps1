$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $root
& (Join-Path $PSScriptRoot 'setup_windows.ps1') -SkipModels -Dev
if (!(Test-Path .tools\export\templates\windows_release_x86_64.exe)) {
    Invoke-WebRequest -UseBasicParsing -Uri 'https://github.com/godotengine/godot-builds/releases/download/4.7.2-stable/Godot_v4.7.2-stable_export_templates.tpz' -OutFile .tools\export_templates.zip
    & .venv\Scripts\python.exe -c "import zipfile; z=zipfile.ZipFile('.tools/export_templates.zip'); [z.extract(n,'.tools/export') for n in z.namelist() if n.startswith('templates/windows_') and 'x86_64' in n]"
    if ($LASTEXITCODE -ne 0) { throw 'Could not extract Windows export templates.' }
}
& .venv\Scripts\python.exe scripts\package_windows.py
if ($LASTEXITCODE -ne 0) { throw 'Windows build failed.' }
