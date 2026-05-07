$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$release = Invoke-RestMethod -Uri "https://api.github.com/repos/git-for-windows/git/releases/latest" -UseBasicParsing
$asset = $release.assets | Where-Object { $_.browser_download_url -match "MinGit-.*-64-bit\.zip$" } | Select-Object -First 1
if (-not $asset) {
    throw "MinGit zip asset not found"
}

$root = "D:\Workspace\YouTubeSummarizer\DevTools"
$target = "D:\Workspace\YouTubeSummarizer\DevTools\Git"
$zip = "D:\Workspace\YouTubeSummarizer\DevTools\MinGit-64-bit.zip"

New-Item -ItemType Directory -Force -Path $root | Out-Null
if (Test-Path $target) {
    Remove-Item $target -Recurse -Force
}

Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zip -UseBasicParsing
Expand-Archive -Path $zip -DestinationPath $target -Force

$gitExe = Get-ChildItem $target -Recurse -Filter git.exe | Select-Object -First 1 -ExpandProperty FullName
if (-not $gitExe) {
    throw "git.exe not found after extraction"
}

$gitDir = Split-Path $gitExe -Parent
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if (-not $userPath) {
    $userPath = ""
}
if ($userPath -notlike "*$gitDir*") {
    $newPath = (($userPath.TrimEnd(";") + ";" + $gitDir).Trim(";"))
    [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
}

Write-Output $gitExe
