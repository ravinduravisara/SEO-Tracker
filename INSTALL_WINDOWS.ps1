$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
Write-Host "Aviance SEO Pro Max v6.4.0 installer" -ForegroundColor Cyan
if (-not (Get-Command py -ErrorAction SilentlyContinue)) { throw "Windows Python launcher 'py' not found. Install Python 3.11+ and enable the launcher." }
if (-not (Test-Path ".venv\Scripts\python.exe")) { py -m venv .venv }
.\.venv\Scripts\python.exe -m pip install --disable-pip-version-check -q -r .\requirements.txt
.\.venv\Scripts\python.exe -c "import fastapi, requests, bs4, reportlab; print('Aviance dependencies verified.')"
Write-Host "Installation complete. Run START_AVIANCE.bat" -ForegroundColor Green
