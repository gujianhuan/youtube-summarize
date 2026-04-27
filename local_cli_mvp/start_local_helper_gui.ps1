$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Windows.Forms

function Show-ErrorAndExit {
    param(
        [string]$Message
    )

    [System.Windows.Forms.MessageBox]::Show(
        $Message,
        "本地转写助手启动失败",
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Error
    ) | Out-Null
    exit 1
}

try {
    $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    $guiLauncher = Join-Path $scriptDir "video_local_helper_gui_launcher.pyw"

    if (-not (Test-Path $guiLauncher)) {
        Show-ErrorAndExit "未找到 GUI 启动文件：`n$guiLauncher"
    }

    $runner = $null
    foreach ($name in @("pythonw", "pyw", "python", "py")) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if ($command) {
            $runner = $command.Source
            break
        }
    }

    if (-not $runner) {
        Show-ErrorAndExit "未找到 Python / Python Launcher，请先安装 Python 并加入 PATH。"
    }

    $useConsoleRunner = $runner.ToLower().EndsWith("python.exe") -or $runner.ToLower().EndsWith("\py.exe")
    if ($useConsoleRunner) {
        Start-Process -FilePath $runner -ArgumentList @($guiLauncher) -WorkingDirectory $scriptDir
    }
    else {
        Start-Process -FilePath $runner -ArgumentList @($guiLauncher) -WorkingDirectory $scriptDir -WindowStyle Hidden
    }
}
catch {
    Show-ErrorAndExit $_.Exception.ToString()
}
