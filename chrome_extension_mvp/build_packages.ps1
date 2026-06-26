$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$manifestPath = Join-Path $root "manifest.json"

if (-not (Test-Path $manifestPath)) {
    throw "未找到 manifest.json: $manifestPath"
}

$manifest = Get-Content -Path $manifestPath -Raw | ConvertFrom-Json
$version = [string]$manifest.version
if ([string]::IsNullOrWhiteSpace($version)) {
    throw "manifest.json 中缺少 version"
}

$distDir = Join-Path $root "dist"
$chromeZip = Join-Path $distDir ("video_transcript_helper_chrome_v{0}.zip" -f $version)
$chromeDir = Join-Path $distDir ("chrome_unpacked_v{0}" -f $version)
$chromeStoreZip = Join-Path $distDir ("video_transcript_helper_chrome_store_v{0}.zip" -f $version)
$chromeStoreDir = Join-Path $distDir ("chrome_store_unpacked_v{0}" -f $version)
$releaseInfoPath = Join-Path $distDir ("release_info_v{0}.json" -f $version)

$excludeNames = @(
    "dist",
    "refresh_dev.ps1",
    "build_packages.ps1",
    "chrome_extension_mvp.zip"
)

function Write-Utf8TextFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [string]$Content
    )

    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Content, $utf8NoBom)
}

function New-ChromeWorkspace {
    param(
        [Parameter(Mandatory = $true)]
        [string]$DestinationDir,
        [switch]$StoreSafe
    )

    New-Item -ItemType Directory -Force -Path $DestinationDir | Out-Null
    if ($StoreSafe) {
        foreach ($itemName in @(
            "manifest.json",
            "popup.html",
            "popup.css",
            "popup.js",
            "background.js",
            "content.js",
            "icons"
        )) {
            $sourcePath = Join-Path $root $itemName
            if (Test-Path $sourcePath) {
                Copy-Item -Path $sourcePath -Destination $DestinationDir -Recurse -Force
            }
        }
    } else {
        Get-ChildItem -Path $root -Force | ForEach-Object {
            if ($excludeNames -contains $_.Name) {
                return
            }
            Copy-Item -Path $_.FullName -Destination $DestinationDir -Recurse -Force
        }
    }

    $variantManifestPath = Join-Path $DestinationDir "manifest.json"
    $variantManifest = Get-Content -Path $variantManifestPath -Raw | ConvertFrom-Json
    if ($null -ne $variantManifest.PSObject.Properties["browser_specific_settings"]) {
        $variantManifest.PSObject.Properties.Remove("browser_specific_settings")
    }

    if ($StoreSafe) {
        $variantManifest.name = "ClipBrief AI"
        $variantManifest.description = "Extract YouTube transcripts from the current video page and send them to ClipBrief AI for summary and source checks."

        $storePermissions = @(
            "activeTab",
            "scripting",
            "tabs",
            "clipboardWrite",
            "storage"
        )
        $storeHostPermissions = @(
            "https://www.youtube.com/*",
            "https://youtube.com/*",
            "https://youtube-summarize-0oms.onrender.com/*",
            "https://youtube-summarize-bridge.onrender.com/*"
        )
        $storeContentMatches = @(
            "https://www.youtube.com/*",
            "https://youtube.com/*",
            "https://youtube-summarize-0oms.onrender.com/*"
        )

        $variantManifest.permissions = $storePermissions
        $variantManifest.host_permissions = $storeHostPermissions
        if ($variantManifest.content_scripts -is [array] -and $variantManifest.content_scripts.Count -gt 0) {
            foreach ($contentScript in $variantManifest.content_scripts) {
                $contentScript.matches = $storeContentMatches
            }
        }

        $popupPath = Join-Path $DestinationDir "popup.js"
        if (Test-Path $popupPath) {
            $popupSource = Get-Content -Path $popupPath -Raw
            $popupSource = $popupSource -replace 'const LOCAL_MAIN_URL = ".*?";', 'const LOCAL_MAIN_URL = DEFAULT_MAIN_URL;'
            $popupSource = $popupSource -replace 'const LOCAL_BRIDGE_URL = ".*?";', 'const LOCAL_BRIDGE_URL = DEFAULT_BRIDGE_URL;'
            $popupSource = $popupSource -replace '(?s)const LOCAL_MAIN_URL_CANDIDATES = \[.*?\];', 'const LOCAL_MAIN_URL_CANDIDATES = [];'
            $popupSource = $popupSource -replace '(?s)const LOCAL_BRIDGE_URL_CANDIDATES = \[.*?\];', 'const LOCAL_BRIDGE_URL_CANDIDATES = [];'
            $popupSource = $popupSource -replace 'const DEBUG_SERVER_URL = ".*?";', 'const DEBUG_SERVER_URL = "";'
            $popupSource = $popupSource -replace 'mainUrlPlaceholder: "例如 .*?",', 'mainUrlPlaceholder: "例如 https://youtube-summarize-0oms.onrender.com/",'
            $popupSource = $popupSource -replace 'mainUrlPlaceholder: "e\.g\. .*?",', 'mainUrlPlaceholder: "e.g. https://youtube-summarize-0oms.onrender.com/",'
            $popupSource = $popupSource -replace 'configTitle: "服务配置",', 'configTitle: "服务配置",'
            $popupSource = $popupSource -replace 'configTitle: "Debug Config",', 'configTitle: "Service Settings",'
            $popupSource = $popupSource -replace 'useLocalMainBtn: "切到本地并保存",', 'useLocalMainBtn: "使用线上默认值",'
            $popupSource = $popupSource -replace 'useLocalMainBtn: "Use Local and Save",', 'useLocalMainBtn: "Use Defaults",'
            $popupSource = $popupSource -replace '(?s)function reportPopupDebug\(hypothesisId, msg, data = \{\}\) \{.*?\n\}\r?\n// #endregion', 'function reportPopupDebug(_hypothesisId, _msg, _data = {}) {
  // Disabled in the Chrome Web Store package.
}
// #endregion'
            $popupSource = $popupSource -replace '(?s)function debuggerAttach\(target, version = "1\.3"\) \{.*?\}\s*function debuggerDetach\(target\) \{.*?\}\s*function debuggerSendCommand\(target, method, params = \{\}\) \{.*?\}\s*', ''
            $popupSource = $popupSource -replace '(?s)async function extractYouTubeTranscriptViaDebuggerClick\(tabId\) \{.*?\n\}\r?\n\r?\nasync function ensureContentScript', 'async function extractYouTubeTranscriptViaDebuggerClick(tabId) {
  return { ok: false, error: "privileged_panel_click_disabled_for_store" };
}

async function ensureContentScript'
            Write-Utf8TextFile -Path $popupPath -Content $popupSource
        }

        $backgroundPath = Join-Path $DestinationDir "background.js"
        if (Test-Path $backgroundPath) {
            $backgroundSource = Get-Content -Path $backgroundPath -Raw
            $backgroundSource = $backgroundSource -replace '(?s)const LOCAL_SUMMARIZER_URL_CANDIDATES = \[.*?\];', 'const LOCAL_SUMMARIZER_URL_CANDIDATES = [];'
            $backgroundSource = $backgroundSource -replace '(?s)const LOCAL_BRIDGE_API_URL_CANDIDATES = \[.*?\];', 'const LOCAL_BRIDGE_API_URL_CANDIDATES = [];'
            $backgroundSource = $backgroundSource -replace 'const DEBUG_SERVER_URL = ".*?";', 'const DEBUG_SERVER_URL = "";'
            $backgroundSource = $backgroundSource -replace '(?s)function reportBackgroundDebug\(hypothesisId, msg, data = \{\}\) \{.*?\n\}\r?\n// #endregion', 'function reportBackgroundDebug(_hypothesisId, _msg, _data = {}) {
  // Disabled in the Chrome Web Store package.
}
// #endregion'
            $backgroundSource = $backgroundSource -replace '(?s)function isLoopbackUrl\(value\) \{.*?\n\}', 'function isLoopbackUrl(_value) {
  return false;
}'
            $backgroundSource = $backgroundSource -replace 'Try the next localhost candidate\.', 'Try the next configured candidate.'
            Write-Utf8TextFile -Path $backgroundPath -Content $backgroundSource
        }

        $contentPath = Join-Path $DestinationDir "content.js"
        if (Test-Path $contentPath) {
            $contentSource = Get-Content -Path $contentPath -Raw
            $contentSource = $contentSource -replace 'const DEBUG_SERVER_URL = ".*?";', 'const DEBUG_SERVER_URL = "";'
            $contentSource = $contentSource -replace '(?s)// #region debug-point B:content-report.*?// #endregion', '// #region debug-point B:content-report
  function reportContentDebug(_hypothesisId, _msg, _data = {}) {
    // Disabled in the Chrome Web Store package.
  }
  // #endregion'
            $contentSource = $contentSource -replace '(?s)function isLoopbackPageOrigin\(value\) \{.*?\r?\n\s*\}\r?\n(?=\s*function writePageFlowStorageResponse)', 'function isLoopbackPageOrigin(_value) {
    return false;
  }
'
            Write-Utf8TextFile -Path $contentPath -Content $contentSource
        }

        $popupHtmlPath = Join-Path $DestinationDir "popup.html"
        if (Test-Path $popupHtmlPath) {
            $popupHtml = Get-Content -Path $popupHtmlPath -Raw
            $popupHtml = $popupHtml -replace 'Debug Config', 'Service Settings'
            $popupHtml = $popupHtml -replace 'e\.g\. http://127\.0\.0\.1:8501/', 'e.g. https://youtube-summarize-0oms.onrender.com/'
            $popupHtml = $popupHtml -replace 'Use Local', 'Use Defaults'
            $popupHtml = $popupHtml -replace 'Open a YouTube video page, extract the transcript, then send it to ClipBrief AI\.', 'Extract YouTube transcripts, copy the text, or send them to ClipBrief AI.'
            Write-Utf8TextFile -Path $popupHtmlPath -Content $popupHtml
        }
    }

    $variantManifestJson = $variantManifest | ConvertTo-Json -Depth 20
    Write-Utf8TextFile -Path $variantManifestPath -Content $variantManifestJson
}

New-Item -ItemType Directory -Force -Path $distDir | Out-Null

foreach ($outputPath in @($chromeZip, $chromeStoreZip, $releaseInfoPath)) {
    if (Test-Path $outputPath) {
        Remove-Item $outputPath -Force
    }
}

foreach ($dirPath in @($chromeDir, $chromeStoreDir)) {
    if (Test-Path $dirPath) {
        Remove-Item $dirPath -Recurse -Force
    }
}

New-ChromeWorkspace -DestinationDir $chromeDir
Compress-Archive -Path (Join-Path $chromeDir "*") -DestinationPath $chromeZip -Force

New-ChromeWorkspace -DestinationDir $chromeStoreDir -StoreSafe
Compress-Archive -Path (Join-Path $chromeStoreDir "*") -DestinationPath $chromeStoreZip -Force

$releaseInfo = [ordered]@{
    version = $version
    generatedAt = (Get-Date).ToString("s")
    packages = [ordered]@{
        chrome_zip = $chromeZip
        chrome_store_zip = $chromeStoreZip
    }
    unpacked = [ordered]@{
        chrome = $chromeDir
        chrome_store = $chromeStoreDir
    }
    uploadTargets = [ordered]@{
        chrome = "Local Chrome testing"
        chrome_store = "Chrome Web Store"
    }
    scope = "chrome-only"
}

$releaseInfoJson = $releaseInfo | ConvertTo-Json -Depth 10
Write-Utf8TextFile -Path $releaseInfoPath -Content $releaseInfoJson

Write-Output "打包完成:"
Write-Output "Chrome: $chromeZip"
Write-Output "Chrome 解压目录: $chromeDir"
Write-Output "Chrome Web Store: $chromeStoreZip"
Write-Output "Chrome Web Store 解压目录: $chromeStoreDir"
Write-Output "发布信息: $releaseInfoPath"
