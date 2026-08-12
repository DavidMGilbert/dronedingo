# DroneDingo — run the appliance locally on Windows for setup & push testing.
#   Right-click → Run with PowerShell, or:  powershell -File deploy\run-local.ps1
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

if (-not (Test-Path ".venv")) {
    Write-Host "Creating virtual environment..." -ForegroundColor Cyan
    python -m venv .venv
}
Write-Host "Installing dependencies (quiet)..." -ForegroundColor Cyan
& .\.venv\Scripts\python.exe -m pip install --quiet --upgrade pip
& .\.venv\Scripts\python.exe -m pip install --quiet -r backend\requirements.txt

$ip = (Get-NetIPAddress -AddressFamily IPv4 -PrefixOrigin Dhcp -ErrorAction SilentlyContinue |
        Select-Object -First 1 -ExpandProperty IPAddress)
Write-Host ""
Write-Host "DroneDingo is starting." -ForegroundColor Green
Write-Host "  This PC:        http://localhost:8000"
if ($ip) { Write-Host "  Other devices:  http://$ip`:8000" }
Write-Host "  First visit creates the admin login. Ctrl+C to stop."
Write-Host ""
& .\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000
