$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$Python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { & py -m venv (Join-Path $PSScriptRoot ".venv") }
& $Python -m pip install --disable-pip-version-check playwright
if ($LASTEXITCODE -ne 0) { throw "Playwright installation failed." }
Write-Host "Installing Chromium for rendered JS audits..." -ForegroundColor Yellow
& $Python -m playwright install chromium
if ($LASTEXITCODE -ne 0) { throw "Chromium installation failed." }
Write-Host "Browser rendering is ready." -ForegroundColor Green
