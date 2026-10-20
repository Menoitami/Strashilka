@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_windows.ps1" -Offline --neural-demo %*
if errorlevel 1 pause
