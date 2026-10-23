
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$Python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$Req = Join-Path $PSScriptRoot "requirements.txt"
Write-Host "\n=== eSupport SEO v10.3.0 ===" -ForegroundColor Cyan
Write-Host "Project: $PSScriptRoot" -ForegroundColor DarkGray
if (-not (Test-Path $Python)) {
  Write-Host "Creating .venv..." -ForegroundColor Yellow
  & py -m venv (Join-Path $PSScriptRoot ".venv")
  if ($LASTEXITCODE -ne 0) { throw "Could not create virtual environment. Install Python 3.11+ with the Windows py launcher." }
}
Write-Host "Installing/verifying dependencies..." -ForegroundColor Yellow
& $Python -m pip install --disable-pip-version-check -q -r $Req
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }
& $Python -c "import fastapi, requests, bs4, reportlab; print('Dependencies OK: FastAPI / Requests / BeautifulSoup / ReportLab')"
if ($LASTEXITCODE -ne 0) { throw "Dependency verification failed." }
& $Python -c "import importlib.util; print('Playwright package: ' + ('available' if importlib.util.find_spec('playwright') else 'not installed'))"
$port = if ($env:PORT) { [int]$env:PORT } else { 8000 }
$inUse = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if ($inUse) {
  Write-Host "Notice: Port $port is in use. Finding an available port..." -ForegroundColor Yellow
  while (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
    $port++
  }
  $env:PORT = "$port"
}
Write-Host "Starting eSupport SEO v10.4.0 on http://127.0.0.1:$port" -ForegroundColor Green
& $Python -m backend.main
