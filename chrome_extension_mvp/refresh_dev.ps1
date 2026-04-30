$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$zipPath = Join-Path $root "chrome_extension_mvp.zip"
$tempDir = Join-Path ([System.IO.Path]::GetTempPath()) ("chrome_extension_mvp_" + [guid]::NewGuid().ToString("N"))

New-Item -ItemType Directory -Force -Path $tempDir | Out-Null
Copy-Item -Path (Join-Path $root "*") -Destination $tempDir -Recurse -Force

$excludeNames = @(
    "chrome_extension_mvp.zip",
    "refresh_dev.ps1"
)

foreach ($name in $excludeNames) {
    $target = Join-Path $tempDir $name
    if (Test-Path $target) {
        Remove-Item $target -Recurse -Force
    }
}

if (Test-Path $zipPath) {
    Remove-Item $zipPath -Force
}

Compress-Archive -Path (Join-Path $tempDir "*") -DestinationPath $zipPath -Force
Remove-Item $tempDir -Recurse -Force

Write-Output "插件打包完成: $zipPath"
Write-Output "如果你使用“加载已解压的扩展程序”，请到 chrome://extensions/ 手动点一次刷新。"
