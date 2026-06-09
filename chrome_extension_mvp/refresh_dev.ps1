$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$buildScript = Join-Path $root "build_packages.ps1"
$manifestPath = Join-Path $root "manifest.json"

if (-not (Test-Path $buildScript)) {
    throw "未找到 build_packages.ps1: $buildScript"
}

if (-not (Test-Path $manifestPath)) {
    throw "未找到 manifest.json: $manifestPath"
}

$manifest = Get-Content -Path $manifestPath -Raw | ConvertFrom-Json
$version = [string]$manifest.version
if ([string]::IsNullOrWhiteSpace($version)) {
    throw "manifest.json 中缺少 version"
}

& powershell -ExecutionPolicy Bypass -File $buildScript

$distDir = Join-Path $root "dist"
$chromeDir = Join-Path $distDir ("chrome_unpacked_v{0}" -f $version)

Write-Output ""
Write-Output "开发刷新提示:"
Write-Output "- Chrome: 打开 chrome://extensions/ ，刷新已加载的 $chromeDir"
Write-Output "- 当前发布范围为 Chrome-only；Edge / Firefox 暂不处理"
