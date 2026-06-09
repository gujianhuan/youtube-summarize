Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
$pythonExe = Join-Path $root ".python313\python.exe"
if (-not (Test-Path $pythonExe)) {
    $pythonExe = "python"
}
$bridgeUrl = "http://127.0.0.1:8765"
$env:BRIDGE_API_URL = $bridgeUrl

Write-Host "Checking local bridge service..." -ForegroundColor Cyan
try {
    $bridgeHealth = Invoke-WebRequest -Uri "$bridgeUrl/health" -UseBasicParsing -TimeoutSec 2
} catch {
    $bridgeHealth = $null
}

if (-not $bridgeHealth -or $bridgeHealth.StatusCode -ne 200) {
    Write-Host "Bridge not detected. Launching bridge_api.py in a new window..." -ForegroundColor Yellow
    Start-Process powershell -ArgumentList @(
        "-NoExit",
        "-Command",
        "Set-Location '$root'; `$env:BRIDGE_API_URL='$bridgeUrl'; & '$pythonExe' bridge_api.py"
    )
    Start-Sleep -Seconds 2
} else {
    Write-Host "Bridge is already running." -ForegroundColor Green
}

Write-Host "Starting local Streamlit app..." -ForegroundColor Cyan
try {
    & $pythonExe -m streamlit run app.py --server.port 8501 --server.address 127.0.0.1
} catch {
    Write-Host ("Startup failed: " + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
