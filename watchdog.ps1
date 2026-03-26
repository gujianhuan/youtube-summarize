Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$port = 8501
$address = "127.0.0.1"
$maxRestart = 0
$restartCount = 0

Write-Host "守护进程已启动，将自动重启服务..." -ForegroundColor Cyan

while ($true) {
    try {
        $restartCount++
        Write-Host ("启动服务 (第 " + $restartCount + " 次)") -ForegroundColor Green
        python -m streamlit run app.py --server.port $port --server.address $address
    } catch {
        Write-Host ("服务异常退出: " + $_.Exception.Message) -ForegroundColor Red
    }
    if ($maxRestart -gt 0 -and $restartCount -ge $maxRestart) {
        Write-Host "已达到最大重启次数，停止守护。" -ForegroundColor Yellow
        break
    }
    Start-Sleep -Seconds 3
}
