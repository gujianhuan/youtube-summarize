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
        throw "Missing command: $CommandName. $InstallHint"
    }
}

function Invoke-Git {
    param(
        [Parameter(ValueFromRemainingArguments = $true)]
        [string[]]$Args
    )

    & git @Args
    if ($LASTEXITCODE -ne 0) {
        throw "Git command failed: git $($Args -join ' ')"
    }
}

function Test-GitFilterRepo {
    & py -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('git_filter_repo') else 1)" > $null 2>&1
    return $LASTEXITCODE -eq 0
}

Assert-CommandExists -CommandName "git" -InstallHint "Install Git for Windows first."
Assert-CommandExists -CommandName "py" -InstallHint "Install Python first and ensure the py launcher is available."

$ProjectRoot = (Resolve-Path $ProjectRoot).Path
if (-not $MirrorClonePath) {
    $parent = Split-Path $ProjectRoot -Parent
    $repoName = Split-Path $ProjectRoot -Leaf
    $MirrorClonePath = Join-Path $parent "${repoName}-history-clean"
}

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backupDir = Join-Path $ProjectRoot ".git-history-backups"
$bundlePath = Join-Path $backupDir "backup_$timestamp.bundle"

Write-Step "Check repository state"
Push-Location $ProjectRoot
try {
    $isRepo = (& git rev-parse --is-inside-work-tree 2>$null).Trim()
    if ($LASTEXITCODE -ne 0 -or $isRepo -ne "true") {
        throw "Current directory is not a Git repository: $ProjectRoot"
    }

    $statusOutput = & git status --short
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to read git status."
    }
    if ($statusOutput) {
        throw "Working tree is not clean. Commit or stash changes before rewriting history."
    }

    Write-Step "Create bundle backup"
    New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
    Invoke-Git bundle create $bundlePath --all
    Write-Host "Backup created: $bundlePath" -ForegroundColor Green

    if (-not (Test-GitFilterRepo)) {
        if (-not $InstallFilterRepo) {
            throw "git-filter-repo is missing. Re-run with -InstallFilterRepo, or install it manually: py -m pip install --user git-filter-repo"
        }

        Write-Step "Install git-filter-repo"
        & py -m pip install --user git-filter-repo
        if ($LASTEXITCODE -ne 0 -or -not (Test-GitFilterRepo)) {
            throw "git-filter-repo installation failed."
        }
    }
} finally {
    Pop-Location
}

Write-Step "Prepare mirror clone"
if (Test-Path $MirrorClonePath) {
    throw "Mirror clone path already exists. Remove it first or pass a new -MirrorClonePath: $MirrorClonePath"
}
Invoke-Git clone --mirror $ProjectRoot $MirrorClonePath

Push-Location $MirrorClonePath
try {
    Write-Step "Rewrite history"
    & py -m git_filter_repo --force --invert-paths `
        --path build `
        --path dist `
        --path local_cli_mvp_output `
        --path chrome_extension_mvp.zip `
        --path-glob tmp_* `
        --path-glob .tmp_*
    if ($LASTEXITCODE -ne 0) {
        throw "git_filter_repo execution failed."
    }

    Write-Step "Run cleanup and garbage collection"
    Invoke-Git reflog expire --expire=now --all
    Invoke-Git gc --prune=now --aggressive

    Write-Step "Print verification summary"
    & git count-objects -vH

    Write-Host ""
    Write-Host "History cleanup completed. Verify the mirror clone before force-pushing:" -ForegroundColor Yellow
    Write-Host "1. Set-Location `"$MirrorClonePath`""
    Write-Host "2. git log --oneline --stat -5"
    Write-Host "3. git remote -v"
    Write-Host "4. git push --force-with-lease $RemoteName refs/heads/$MainBranch:refs/heads/$MainBranch"
    Write-Host ""
    Write-Host "Risk: force-push rewrites remote history. Render will redeploy from the new history, and collaborators must resync." -ForegroundColor Yellow
} finally {
    Pop-Location
}
