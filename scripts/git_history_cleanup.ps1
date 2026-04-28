<#
.SYNOPSIS
Safely rewrites Git history in a separate mirror clone to remove generated artifacts.

.DESCRIPTION
This script is designed for Windows/PowerShell usage. It avoids rewriting the current
working repository directly. Instead, it creates a bundle backup, clones a mirror copy,
installs `git-filter-repo` if needed, removes known generated artifacts from the full
history, runs garbage collection, and prints the follow-up commands required to force-push.

.PARAMETER ProjectRoot
Path to the current working repository.

.PARAMETER RemoteName
Remote name to inspect and later force-push.

.PARAMETER MainBranch
Primary branch name that Render tracks.

.PARAMETER MirrorClonePath
Optional path for the temporary mirror clone. Defaults to a sibling directory.

.PARAMETER InstallFilterRepo
When provided, installs `git-filter-repo` with `py -m pip install --user git-filter-repo`
if the tool is missing.
#>
param(
    [string]$ProjectRoot = (Get-Location).Path,
    [string]$RemoteName = "origin",
    [string]$MainBranch = "main",
    [string]$MirrorClonePath = "",
    [switch]$InstallFilterRepo
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Assert-CommandExists {
    param(
        [string]$CommandName,
        [string]$InstallHint
    )

    if (-not (Get-Command $CommandName -ErrorAction SilentlyContinue)) {
        throw "缺少命令: $CommandName。$InstallHint"
    }
}

function Invoke-Git {
    param(
        [Parameter(ValueFromRemainingArguments = $true)]
        [string[]]$Args
    )

    & git @Args
    if ($LASTEXITCODE -ne 0) {
        throw "git 命令失败: git $($Args -join ' ')"
    }
}

function Test-GitFilterRepo {
    $null = & git filter-repo --version 2>$null
    return $LASTEXITCODE -eq 0
}

Assert-CommandExists -CommandName "git" -InstallHint "请先安装 Git for Windows。"
Assert-CommandExists -CommandName "py" -InstallHint "请先安装 Python，并确保 `py` 可用。"

$ProjectRoot = (Resolve-Path $ProjectRoot).Path
if (-not $MirrorClonePath) {
    $parent = Split-Path $ProjectRoot -Parent
    $repoName = Split-Path $ProjectRoot -Leaf
    $MirrorClonePath = Join-Path $parent "${repoName}-history-clean"
}

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backupDir = Join-Path $ProjectRoot ".git-history-backups"
$bundlePath = Join-Path $backupDir "backup_$timestamp.bundle"

Write-Step "检查仓库状态"
Push-Location $ProjectRoot
try {
    $isRepo = (& git rev-parse --is-inside-work-tree 2>$null).Trim()
    if ($LASTEXITCODE -ne 0 -or $isRepo -ne "true") {
        throw "当前目录不是 Git 仓库: $ProjectRoot"
    }

    $statusOutput = & git status --short
    if ($LASTEXITCODE -ne 0) {
        throw "无法读取 git status。"
    }
    if ($statusOutput) {
        throw "工作区不干净。请先提交或暂存当前改动，再执行历史改写。"
    }

    Write-Step "创建 bundle 备份"
    New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
    Invoke-Git bundle create $bundlePath --all
    Write-Host "备份已创建: $bundlePath" -ForegroundColor Green

    if (-not (Test-GitFilterRepo)) {
        if (-not $InstallFilterRepo) {
            throw "未检测到 git-filter-repo。请重新运行并加上 -InstallFilterRepo，或手动执行: py -m pip install --user git-filter-repo"
        }

        Write-Step "安装 git-filter-repo"
        & py -m pip install --user git-filter-repo
        if ($LASTEXITCODE -ne 0 -or -not (Test-GitFilterRepo)) {
            throw "git-filter-repo 安装失败。"
        }
    }
} finally {
    Pop-Location
}

Write-Step "准备 mirror 克隆"
if (Test-Path $MirrorClonePath) {
    throw "目标 mirror 目录已存在，请先删除或传入新的 -MirrorClonePath: $MirrorClonePath"
}
Invoke-Git clone --mirror $ProjectRoot $MirrorClonePath

Push-Location $MirrorClonePath
try {
    Write-Step "执行历史清理"
    Invoke-Git filter-repo --force --invert-paths `
        --path build `
        --path dist `
        --path local_cli_mvp_output `
        --path chrome_extension_mvp.zip `
        --path-glob tmp_* `
        --path-glob .tmp_*

    Write-Step "回收历史垃圾对象"
    Invoke-Git reflog expire --expire=now --all
    Invoke-Git gc --prune=now --aggressive

    Write-Step "输出验证信息"
    & git count-objects -vH

    Write-Host ""
    Write-Host "历史清理已完成。下一步请人工确认后再强推：" -ForegroundColor Yellow
    Write-Host "1. Set-Location `"$MirrorClonePath`""
    Write-Host "2. git log --oneline --stat -5"
    Write-Host "3. git remote -v"
    Write-Host "4. git push --force-with-lease $RemoteName refs/heads/$MainBranch:refs/heads/$MainBranch"
    Write-Host ""
    Write-Host "风险提示: force-push 会改写远程历史，Render 会基于新历史重新拉取，协作者需要重新同步仓库。" -ForegroundColor Yellow
} finally {
    Pop-Location
}
