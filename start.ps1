Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

Write-Host "启动服务中..." -ForegroundColor Cyan
try {
    python -m streamlit run app.py --server.port 8501 --server.address 127.0.0.1
} catch {
    Write-Host ("启动失败: " + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
