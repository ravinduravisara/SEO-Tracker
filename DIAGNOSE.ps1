$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot
Write-Host "=== Aviance diagnostics ===" -ForegroundColor Cyan
Write-Host "Folder: $PSScriptRoot"
Write-Host "run.ps1:     $(Test-Path .\run.ps1)"
Write-Host "backend:     $(Test-Path .\backend\main.py)"
Write-Host "frontend:    $(Test-Path .\frontend\index.html)"
Write-Host "requirements:$(Test-Path .\requirements.txt)"
Write-Host ".venv python:$(Test-Path .\.venv\Scripts\python.exe)"
if (Get-Command py -ErrorAction SilentlyContinue) { py --version } else { Write-Host "py launcher: MISSING" -ForegroundColor Red }
if (Test-Path .\.venv\Scripts\python.exe) {
  .\.venv\Scripts\python.exe --version
  .\.venv\Scripts\python.exe -c "import fastapi,requests,bs4,reportlab; print('Python dependencies: OK')"
} 
Write-Host "Version marker: v8.0.0"
