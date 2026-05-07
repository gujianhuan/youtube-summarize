$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$installer = Join-Path $env:TEMP "python-3.13.12-amd64.exe"
$targetDir = "D:\Program Files\Trae\YouTubeSummarizer\.python313"

if (!(Test-Path $installer)) {
    Invoke-WebRequest -Uri "https://www.python.org/ftp/python/3.13.12/python-3.13.12-amd64.exe" -OutFile $installer -UseBasicParsing
}

if (Test-Path $targetDir) {
    Remove-Item $targetDir -Recurse -Force
}

$argumentList = @(
    "/quiet",
    "InstallAllUsers=0",
    "TargetDir=$targetDir",
    "PrependPath=0",
    "Include_pip=1",
    "Include_launcher=0",
    "Include_test=0",
    "SimpleInstall=1"
)

$proc = Start-Process -FilePath $installer -ArgumentList $argumentList -Wait -PassThru

Write-Output ("PythonInstallerExitCode=" + $proc.ExitCode)
Write-Output ("PythonTargetExists=" + (Test-Path (Join-Path $targetDir "python.exe")))
