param(
    [string]$ProjectRoot = "D:\Program Files\Trae\YouTubeSummarizer"
)

$ProgressPreference = "SilentlyContinue"

$extensionDir = Join-Path $ProjectRoot "chrome_extension_mvp"
$zipPath = Join-Path $ProjectRoot "chrome_extension_mvp.zip"
$manifestPath = Join-Path $extensionDir "manifest.json"

if (-not (Test-Path $extensionDir)) {
    Write-Error "未找到扩展目录: $extensionDir"
    exit 1
}

if (-not (Test-Path $manifestPath)) {
    Write-Error "未找到 manifest.json: $manifestPath"
    exit 1
}

$manifest = Get-Content $manifestPath -Raw | ConvertFrom-Json
$version = $manifest.version

if (Test-Path $zipPath) {
    Remove-Item $zipPath -Force
}

Compress-Archive -Path (Join-Path $extensionDir "*") -DestinationPath $zipPath -Force

Write-Host ""
Write-Host "Chrome 扩展已重新打包。" -ForegroundColor Green
Write-Host "版本: $version"
Write-Host "目录: $extensionDir"
Write-Host "Zip : $zipPath"
Write-Host ""
Write-Host "如果你当前是“加载已解压的扩展程序”模式：" -ForegroundColor Yellow
Write-Host "1. 打开 chrome://extensions/"
Write-Host "2. 找到 Video Transcript Helper MVP"
Write-Host "3. 点一次“刷新”按钮"
Write-Host ""
Write-Host "注意：未打包目录模式下，Chrome 不支持真正的无感自动更新。" -ForegroundColor Yellow
Write-Host "如果后面要自动更新，需要走 Chrome Web Store 或自托管 CRX/update_url。"
