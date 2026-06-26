$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$manifestPath = Join-Path $root "manifest.json"
$distDir = Join-Path $root "dist"

if (-not (Test-Path $manifestPath)) {
    throw "manifest.json not found: $manifestPath"
}

$manifest = Get-Content -Path $manifestPath -Raw | ConvertFrom-Json
$version = [string]$manifest.version
if ([string]::IsNullOrWhiteSpace($version)) {
    throw "manifest.json is missing version"
}

$errors = New-Object System.Collections.Generic.List[string]
$warnings = New-Object System.Collections.Generic.List[string]

function Assert-Exists {
    param(
        [string]$path,
        [string]$label
    )
    if (-not (Test-Path $path)) {
        $script:errors.Add("Missing ${label}: $path")
    }
}

Assert-Exists -path (Join-Path $root "background.js") -label "file"
Assert-Exists -path (Join-Path $root "content.js") -label "file"
Assert-Exists -path (Join-Path $root "popup.js") -label "file"
Assert-Exists -path (Join-Path $root "popup.html") -label "file"
Assert-Exists -path (Join-Path $root "README.md") -label "document"
Assert-Exists -path (Join-Path $root "RELEASE_GUIDE.md") -label "document"
Assert-Exists -path (Join-Path $root "RELEASE_NOTES.md") -label "document"

$packageZip = Join-Path $distDir ("video_transcript_helper_chrome_v{0}.zip" -f $version)
$chromeDir = Join-Path $distDir ("chrome_unpacked_v{0}" -f $version)
$storePackageZip = Join-Path $distDir ("video_transcript_helper_chrome_store_v{0}.zip" -f $version)
$storeChromeDir = Join-Path $distDir ("chrome_store_unpacked_v{0}" -f $version)
$releaseInfoPath = Join-Path $distDir ("release_info_v{0}.json" -f $version)

foreach ($path in @($packageZip, $chromeDir, $storePackageZip, $storeChromeDir, $releaseInfoPath)) {
    if (-not (Test-Path $path)) {
        $warnings.Add("Missing package artifact: $path")
    }
}

if ($null -eq $manifest.PSObject.Properties["action"]) {
    $errors.Add("manifest.json is missing action config")
}

if ($null -eq $manifest.PSObject.Properties["background"]) {
    $errors.Add("manifest.json is missing background config")
}

$hasIcons = $null -ne $manifest.PSObject.Properties["icons"] -or
    ($null -ne $manifest.action -and $null -ne $manifest.action.PSObject.Properties["default_icon"])
if (-not $hasIcons) {
    $warnings.Add("manifest.json does not define icons/default_icon; add 16/32/48/128 icons before store submission")
}

$storeListingDoc = Join-Path $root "STORE_LISTING.md"
if (-not (Test-Path $storeListingDoc)) {
    $warnings.Add("Missing store listing doc: $storeListingDoc")
}

$storeManifestPath = Join-Path $storeChromeDir "manifest.json"
if (Test-Path $storeManifestPath) {
    $storeManifest = Get-Content -Path $storeManifestPath -Raw | ConvertFrom-Json
    $storePermissions = @($storeManifest.permissions)
    $storeHostPermissions = @($storeManifest.host_permissions)
    $storeContentMatches = @()
    foreach ($contentScript in @($storeManifest.content_scripts)) {
        $storeContentMatches += @($contentScript.matches)
    }
    $storeManifestText = Get-Content -Path $storeManifestPath -Raw
    $forbiddenStorePatterns = @(
        "debugger",
        "localhost",
        "127.0.0.1",
        "trycloudflare",
        "ngrok",
        "workers.dev",
        "MVP"
    )

    foreach ($pattern in $forbiddenStorePatterns) {
        if ($storeManifestText -match [regex]::Escape($pattern)) {
            $errors.Add("Chrome Web Store manifest still contains forbidden release pattern: $pattern")
        }
    }

    if ($storePermissions -contains "debugger") {
        $errors.Add("Chrome Web Store manifest must not request debugger permission")
    }

    if ($storeHostPermissions.Count -gt 4) {
        $warnings.Add("Chrome Web Store manifest has more host permissions than expected: $($storeHostPermissions -join ', ')")
    }

    foreach ($matchPattern in $storeContentMatches) {
        if ($matchPattern -match "localhost|127\.0\.0\.1|trycloudflare|ngrok|workers\.dev") {
            $errors.Add("Chrome Web Store content script match contains development host: $matchPattern")
        }
    }
} else {
    $warnings.Add("Chrome Web Store manifest not found for validation: $storeManifestPath")
}

Write-Output "Preflight release check version: $version"

if ($warnings.Count -gt 0) {
    Write-Output ""
    Write-Output "Warnings:"
    foreach ($item in $warnings) {
        Write-Output "- $item"
    }
}

if ($errors.Count -gt 0) {
    Write-Output ""
    Write-Output "Errors:"
    foreach ($item in $errors) {
        Write-Output "- $item"
    }
    exit 1
}

Write-Output ""
Write-Output "Check passed. Ready to release."
