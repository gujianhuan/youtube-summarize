const extensionApi = globalThis.browser || globalThis.chrome;

const statusEl = document.getElementById("status");
const popupTitleEl = document.getElementById("popupTitle");
const titleInput = document.getElementById("titleInput");
const urlInput = document.getElementById("urlInput");
const transcriptOutput = document.getElementById("transcriptOutput");
const extractBtn = document.getElementById("extractBtn");
const copyBtn = document.getElementById("copyBtn");
const openBtn = document.getElementById("openBtn");
const helperPanel = document.getElementById("helperPanel");
const helperTitleEl = document.getElementById("helperTitle");
const helperDescEl = document.getElementById("helperDesc");
const helperGuideBtn = document.getElementById("helperGuideBtn");
const copyLinkBtn = document.getElementById("copyLinkBtn");
const mainUrlInput = document.getElementById("mainUrlInput");
const bridgeUrlInput = document.getElementById("bridgeUrlInput");
const useLocalMainBtn = document.getElementById("useLocalMainBtn");
const saveConfigBtn = document.getElementById("saveConfigBtn");
const resetConfigBtn = document.getElementById("resetConfigBtn");
const configTitleEl = document.getElementById("configTitle");
const mainUrlLabelEl = document.getElementById("mainUrlLabel");
const bridgeUrlLabelEl = document.getElementById("bridgeUrlLabel");
const titleLabelEl = document.getElementById("titleLabel");
const urlLabelEl = document.getElementById("urlLabel");
const transcriptLabelEl = document.getElementById("transcriptLabel");
const popupHintEl = document.getElementById("popupHint");
const progressPanel = document.getElementById("progressPanel");
const progressTitleEl = document.getElementById("progressTitle");
const progressPercentEl = document.getElementById("progressPercent");
const progressFillEl = document.getElementById("progressFill");
const progressStepsEl = document.getElementById("progressSteps");

const FLOW_STATUS_KEY = "summarizerFlowStatus";
const EXTENSION_CONFIG_KEY = "summarizerExtensionConfig";
const LAST_TRANSCRIPT_KEY = "summarizerLastTranscript";
const EXTENSION_VERSION = extensionApi?.runtime?.getManifest?.().version || "1.1";
const EXTENSION_TOOL_VERSION = `browser-extension-mvp-${EXTENSION_VERSION}`;
const DEFAULT_MAIN_URL = "https://youtube-summarize-0oms.onrender.com/";
const DEFAULT_BRIDGE_URL = "https://youtube-summarize-bridge.onrender.com";
const LOCAL_MAIN_URL = "http://127.0.0.1:8501/";
const LOCAL_BRIDGE_URL = "http://127.0.0.1:8765";
const LOCAL_MAIN_URL_CANDIDATES = [
  "http://127.0.0.1:8501/",
  "http://127.0.0.1:8502/",
  "http://localhost:8501/",
  "http://localhost:8502/"
];
const LOCAL_BRIDGE_URL_CANDIDATES = [
  "http://127.0.0.1:8765",
  "http://localhost:8765"
];
let lastExtractResponse = null;
let autoStartTriggered = false;
let lastProgressStage = "idle";
const DEBUG_SERVER_URL = "http://127.0.0.1:7777/event";
const DEBUG_SESSION_ID = "youtube-plugin-extract";
const popupQuery = new URLSearchParams(globalThis.location?.search || "");
const popupTargetTabId = Number.parseInt(String(popupQuery.get("target_tab_id") || "").trim(), 10);
const popupTargetSourceUrl = String(popupQuery.get("target_source_url") || "").trim();
const popupTargetTitle = String(popupQuery.get("target_title") || "").trim();
const POPUP_LOCALE = resolvePopupLocale();

const POPUP_MESSAGES = {
  zh: {
    popupTitle: `ClipBrief AI v${EXTENSION_VERSION}`,
    popupStatusIdle: "待命：打开 YouTube 视频后会自动提取并发送到主站。",
    extractBtn: "提取字幕",
    copyBtn: "复制文本",
    openBtn: "一键总结",
    configTitle: "服务配置",
    mainUrlLabel: "主站地址",
    mainUrlPlaceholder: "例如 http://127.0.0.1:8501/",
    bridgeUrlLabel: "Bridge 地址",
    bridgeUrlPlaceholder: "例如 https://youtube-summarize-bridge.onrender.com",
    useLocalMainBtn: "切到本地并保存",
    saveConfigBtn: "保存配置",
    resetConfigBtn: "恢复默认",
    helperTitleDefault: "可切换到主站继续抓取",
    helperGuideBtn: "继续到主站",
    copyLinkBtn: "复制视频链接",
    titleLabel: "标题",
    urlLabel: "来源链接",
    transcriptLabel: "提取结果",
    transcriptPlaceholder: "这里会显示提取到的字幕文本",
    popupHint: "打开 YouTube 视频页后点击插件。插件会从当前页面提取 transcript，并发送到线上主站总结。",
    configSaved: "服务配置已保存。",
    configReset: "已恢复默认线上配置。",
    helperNoCaptionTitle: "该视频没有开放平台字幕轨道",
    helperNoCaptionDesc: "这个视频大概率只有画面硬字幕，或作者没有对外开放 YouTube 字幕轨道，所以扩展暂时拿不到 transcript。你可以继续交给主站，由服务端抓取并进入总结流程。",
    helperNoTextTitle: "当前页面没有直接可提取文本",
    helperNoTextDesc: "当前页面没有可直接提取的公开文本。你看到的可能只是画面硬字幕，不是平台可抓取字幕。你可以继续交给主站抓取并总结。",
    helperExtractFailedTitle: "当前更像是提取失败，不是无文本",
    helperExtractFailedDesc: "扩展检测到页面可能存在文本来源，但这次提取没有成功。请优先重试，或先手动展开 transcript/字幕面板，再重新提取。",
    helperUnsupportedTitle: "当前页面暂不支持",
    helperUnsupportedDesc: "请在 YouTube 或 Bilibili 的视频详情页使用这个扩展。这个状态不应该引导你去安装本地工具。",
    extractSuccess: "提取完成：{platform}，约 {count} 字符。{helper}",
    pageNotFound: "未找到当前页面。",
    extractingYoutubeMainWorld: "正在直接从当前 YouTube 页面读取播放器字幕...",
    extractingYoutubeBackground: "正在优先读取 YouTube 字幕轨道；必要时再尝试 transcript 面板...",
    directFetchFallbackWithError: "直连未成功，正在回退到页面提取... {mainError} / {backgroundError}",
    directFetchFallback: "直连未成功，正在回退到页面提取...",
    noMainWorldSupport: "当前浏览器不支持主上下文注入，正在通过页面桥接提取 YouTube 字幕...",
    extractingFromPage: "正在向页面请求字幕...",
    injectingContentScript: "当前页面尚未注入扩展脚本，正在自动补注入后重试...",
    extractFailed: "提取失败: {message}",
    pageFallbackMainWorld: "页面提取失败，正在尝试 YouTube 直连兜底...",
    pageFallbackBackground: "页面桥接提取失败，正在尝试扩展后台直连兜底...",
    noTranscriptExtracted: "未提取到字幕。",
    copyEmpty: "没有可复制的字幕文本。",
    copySuccess: "已复制字幕文本，可回到主站继续总结。",
    copyLinkEmpty: "当前没有可复制的视频链接。",
    copyLinkSuccess: "已复制视频链接，可粘贴到主站继续抓取与总结。",
    probingLocal: "正在探测本地主站和 Bridge...",
    localSwitched: "已切到本地联调地址并保存（{details}）。",
    localNotDetected: "未探测到运行中的本地服务，已先写入本地默认地址，请启动后再试。",
    switchLocalFailed: "切换本地联调失败: {message}",
    saveConfigFailed: "保存配置失败: {message}",
    resetConfigFailed: "恢复默认配置失败: {message}",
    autoSwitchToMain: "插件未直接拿到页面文本，正在使用同一字幕抓取服务继续获取。",
    serverFallbackReady: "插件未直接拿到页面文本，正在调用同一字幕抓取服务继续获取。",
    localHelperRequired: "当前页面没有直接可提取文本，建议切换到主站继续抓取。",
    autoExtractFailed: "未能自动提取字幕，无法发送到主站。",
    noTranscriptToSend: "没有可发送的字幕文本。",
    startSummarizeFlow: "任务已交给后台，正在打开主站并发送 transcript...",
    startSummarizeFlowFailed: "后台任务启动失败。{message}",
  },
  en: {
    popupTitle: `ClipBrief AI v${EXTENSION_VERSION}`,
    popupStatusIdle: "Ready: open a YouTube video to extract and send it to the main site automatically.",
    extractBtn: "Extract",
    copyBtn: "Copy",
    openBtn: "Summarize",
    configTitle: "Debug Config",
    mainUrlLabel: "Main Site URL",
    mainUrlPlaceholder: "e.g. http://127.0.0.1:8501/",
    bridgeUrlLabel: "Bridge URL",
    bridgeUrlPlaceholder: "e.g. https://youtube-summarize-bridge.onrender.com",
    useLocalMainBtn: "Use Local and Save",
    saveConfigBtn: "Save Config",
    resetConfigBtn: "Reset Defaults",
    helperTitleDefault: "Continue on the main site",
    helperGuideBtn: "Open Main Site",
    copyLinkBtn: "Copy Video Link",
    titleLabel: "Title",
    urlLabel: "Source URL",
    transcriptLabel: "Transcript",
    transcriptPlaceholder: "Extracted transcript text will appear here",
    popupHint: "Open a YouTube video and click the extension. It extracts the transcript from the current page and sends it to the online summarizer.",
    configSaved: "Debug configuration saved.",
    configReset: "Default online configuration restored.",
    helperNoCaptionTitle: "No platform caption track is available",
    helperNoCaptionDesc: "This video likely only contains burned-in subtitles, or the creator did not expose YouTube caption tracks publicly. You can continue on the main site so the server can keep fetching and summarizing.",
    helperNoTextTitle: "No directly extractable text on this page",
    helperNoTextDesc: "No publicly extractable text was found on this page. What you see may only be burned-in subtitles, not platform captions. Continue on the main site to let the server keep fetching and summarizing.",
    helperExtractFailedTitle: "This looks like an extraction failure, not missing text",
    helperExtractFailedDesc: "The extension detected a possible text source, but extraction failed this time. Retry first, or manually open the transcript/caption panel and try again.",
    helperUnsupportedTitle: "This page is not supported",
    helperUnsupportedDesc: "Use this extension on YouTube or Bilibili video detail pages. This state should not send you to the local helper.",
    extractSuccess: "Extraction complete: {platform}, about {count} characters. {helper}",
    pageNotFound: "The current page was not found.",
    extractingYoutubeMainWorld: "Reading captions directly from the current YouTube page...",
    extractingYoutubeBackground: "Reading YouTube caption tracks first; transcript panel is used only as fallback...",
    directFetchFallbackWithError: "Direct extraction did not succeed, falling back to page extraction... {mainError} / {backgroundError}",
    directFetchFallback: "Direct extraction did not succeed, falling back to page extraction...",
    noMainWorldSupport: "This browser does not support main-world injection, falling back to page bridge extraction...",
    extractingFromPage: "Requesting transcript from the page...",
    injectingContentScript: "The extension script is not injected into this page yet, injecting and retrying...",
    extractFailed: "Extraction failed: {message}",
    pageFallbackMainWorld: "Page extraction failed, trying the YouTube direct fallback...",
    pageFallbackBackground: "Page bridge extraction failed, trying the extension background fallback...",
    noTranscriptExtracted: "No transcript was extracted.",
    copyEmpty: "There is no transcript text to copy.",
    copySuccess: "Transcript copied. Continue on the main site to summarize it.",
    copyLinkEmpty: "There is no video link to copy.",
    copyLinkSuccess: "Video link copied. Paste it into the main site to continue fetching and summarizing.",
    probingLocal: "Checking the local main site and Bridge...",
    localSwitched: "Switched to local debug endpoints and saved ({details}).",
    localNotDetected: "No running local service was detected. Default local endpoints were written first; start the services and try again.",
    switchLocalFailed: "Failed to switch local debug endpoints: {message}",
    saveConfigFailed: "Failed to save config: {message}",
    resetConfigFailed: "Failed to reset config: {message}",
    autoSwitchToMain: "The extension did not get page text directly, so it is continuing with the same transcript fetch service.",
    serverFallbackReady: "The extension did not get page text directly and is continuing with the same transcript fetch service.",
    localHelperRequired: "This page has no directly extractable text. Continue on the main site instead.",
    autoExtractFailed: "Automatic transcript extraction failed, so nothing was sent to the main site.",
    noTranscriptToSend: "There is no transcript text to send.",
    startSummarizeFlow: "The task has been handed to the background worker. Opening the main site and sending the transcript...",
    startSummarizeFlowFailed: "Failed to start the background task.{message}",
  }
};

function resolvePopupLocale() {
  const candidate = String(
    extensionApi?.i18n?.getUILanguage?.() ||
    globalThis.navigator?.language ||
    ""
  ).trim().toLowerCase();
  return candidate.startsWith("zh") ? "zh" : "en";
}

function tp(key, vars = {}) {
  const template = POPUP_MESSAGES[POPUP_LOCALE]?.[key] || POPUP_MESSAGES.zh[key] || key;
  return template.replace(/\{(\w+)\}/g, (_match, name) => String(vars[name] ?? ""));
}

function applyPopupTranslations() {
  document.documentElement.lang = POPUP_LOCALE === "zh" ? "zh-CN" : "en";
  document.title = tp("popupTitle");
  popupTitleEl.textContent = tp("popupTitle");
  if (!statusEl.textContent.trim()) {
    statusEl.textContent = tp("popupStatusIdle");
  }
  extractBtn.textContent = tp("extractBtn");
  copyBtn.textContent = tp("copyBtn");
  openBtn.textContent = tp("openBtn");
  configTitleEl.textContent = tp("configTitle");
  mainUrlLabelEl.textContent = tp("mainUrlLabel");
  mainUrlInput.placeholder = tp("mainUrlPlaceholder");
  bridgeUrlLabelEl.textContent = tp("bridgeUrlLabel");
  bridgeUrlInput.placeholder = tp("bridgeUrlPlaceholder");
  useLocalMainBtn.textContent = tp("useLocalMainBtn");
  saveConfigBtn.textContent = tp("saveConfigBtn");
  resetConfigBtn.textContent = tp("resetConfigBtn");
  helperGuideBtn.textContent = tp("helperGuideBtn");
  copyLinkBtn.textContent = tp("copyLinkBtn");
  titleLabelEl.textContent = tp("titleLabel");
  urlLabelEl.textContent = tp("urlLabel");
  transcriptLabelEl.textContent = tp("transcriptLabel");
  transcriptOutput.placeholder = tp("transcriptPlaceholder");
  popupHintEl.textContent = tp("popupHint");
  helperTitleEl.textContent = tp("helperTitleDefault");
}

function getRuntimeLastError() {
  return globalThis.chrome?.runtime?.lastError || extensionApi?.runtime?.lastError || null;
}

function callExtensionApi(apiFunction, context, ...args) {
  return new Promise((resolve, reject) => {
    let settled = false;
    const done = (error, result) => {
      if (settled) {
        return;
      }
      settled = true;
      if (error) {
        reject(error instanceof Error ? error : new Error(String(error)));
        return;
      }
      resolve(result);
    };

    if (globalThis.browser) {
      try {
        const maybePromise = apiFunction.apply(context, args);
        if (maybePromise && typeof maybePromise.then === "function") {
          maybePromise.then(
            (result) => done(null, result),
            (error) => done(error, null),
          );
          return;
        }
      } catch (_error) {
        // Fall through to callback-style invocation for Chromium APIs.
      }
    }

    try {
      apiFunction.apply(context, [
        ...args,
        (result) => {
          const runtimeError = getRuntimeLastError();
          if (runtimeError) {
            done(new Error(runtimeError.message || String(runtimeError)));
            return;
          }
          done(null, result);
        }
      ]);
    } catch (error) {
      done(error, null);
    }
  });
}

function storageLocalGet(key) {
  return callExtensionApi(extensionApi.storage.local.get, extensionApi.storage.local, key);
}

function storageLocalSet(value) {
  return callExtensionApi(extensionApi.storage.local.set, extensionApi.storage.local, value);
}

function getTab(tabId) {
  return callExtensionApi(extensionApi.tabs.get, extensionApi.tabs, tabId);
}

function updateTab(tabId, updateProperties) {
  return callExtensionApi(extensionApi.tabs.update, extensionApi.tabs, tabId, updateProperties);
}

async function queryTabs(queryInfo) {
  const tabs = await callExtensionApi(extensionApi.tabs.query, extensionApi.tabs, queryInfo);
  return Array.isArray(tabs) ? tabs : [];
}

function sendTabMessage(tabId, message) {
  return callExtensionApi(extensionApi.tabs.sendMessage, extensionApi.tabs, tabId, message);
}

function executeScript(injection) {
  if (extensionApi.scripting?.executeScript) {
    return callExtensionApi(extensionApi.scripting.executeScript, extensionApi.scripting, injection);
  }
  if (
    extensionApi.tabs?.executeScript &&
    injection?.target?.tabId &&
    Array.isArray(injection.files) &&
    injection.files.length === 1
  ) {
    return callExtensionApi(
      extensionApi.tabs.executeScript,
      extensionApi.tabs,
      injection.target.tabId,
      { file: injection.files[0] }
    );
  }
  return Promise.reject(new Error("execute_script_unsupported"));
}

function withTimeout(promise, timeoutMs, timeoutErrorMessage) {
  return new Promise((resolve, reject) => {
    const timeoutId = globalThis.setTimeout(() => {
      reject(new Error(timeoutErrorMessage || "operation_timeout"));
    }, timeoutMs);
    Promise.resolve(promise).then(
      (result) => {
        globalThis.clearTimeout(timeoutId);
        resolve(result);
      },
      (error) => {
        globalThis.clearTimeout(timeoutId);
        reject(error);
      },
    );
  });
}

function sleep(ms) {
  return new Promise((resolve) => globalThis.setTimeout(resolve, ms));
}

function supportsMainWorldExecution() {
  return Boolean(extensionApi.scripting?.executeScript);
}

function createTab(createProperties) {
  return callExtensionApi(extensionApi.tabs.create, extensionApi.tabs, createProperties);
}

function sendRuntimeMessage(message) {
  return callExtensionApi(extensionApi.runtime.sendMessage, extensionApi.runtime, message);
}

/**
 * 鍚屾鎻愬彇缁撴灉鐩稿叧鎸夐挳鐘舵€侊紝閬垮厤澶辫触鎬佺户缁Е鍙戞€荤粨娴佺▼銆?
 *
 * 鍙湁鍦ㄦ湰娆℃彁鍙栨垚鍔熶笖瀛樺湪鍙敤鏂囨湰鏃讹紝鎵嶅厑璁哥偣鍑烩€滀竴閿€荤粨鈥濄€?
 */
function syncActionButtons() {
  const transcript = transcriptOutput.value.trim();
  const hasTranscript = Boolean(transcript);
  const hasSuccessfulExtraction = Boolean(lastExtractResponse?.ok && hasTranscript);
  const hasSourceUrl = Boolean(String(urlInput.value || "").trim());

  copyBtn.disabled = !hasTranscript;
  openBtn.disabled = !(hasSuccessfulExtraction || hasSourceUrl);
}

function setStatus(text, isError = false) {
  statusEl.textContent = text;
  statusEl.style.color = isError ? "#dc2626" : "#4b5563";
}

function stageToProgress(stage, isError = false) {
  const normalized = String(stage || "idle").trim();
  if (isError || normalized === "error") {
    return { percent: 100, active: "done", title: "任务失败，请重试" };
  }
  if (["extracting", "background_start_extraction", "extract_fast"].includes(normalized)) {
    return { percent: 24, active: "extract", title: "快速读取字幕轨道" };
  }
  if (normalized === "extract_enhanced") {
    return { percent: 42, active: "extract", title: "读取页面字幕数据" };
  }
  if (normalized === "extract_panel") {
    return { percent: 52, active: "extract", title: "尝试 transcript 面板" };
  }
  if (normalized === "extract_background_continue") {
    return { percent: 68, active: "extract", title: "后台继续尝试字幕读取" };
  }
  if (["warming", "retrying", "uploading", "background_upload_bridge_payload"].includes(normalized)) {
    return { percent: 58, active: "upload", title: "正在发送 transcript 到主站" };
  }
  if (["opening", "background_open_main_site"].includes(normalized)) {
    return { percent: 82, active: "open", title: "正在打开主站" };
  }
  if (normalized === "deduped") {
    return { percent: 12, active: "extract", title: "同一视频已有后台任务在运行" };
  }
  if (normalized === "done") {
    return { percent: 100, active: "done", title: "主站已打开，正在自动总结" };
  }
  return { percent: 12, active: "extract", title: "后台任务已启动" };
}

function updateProgress(stage, message = "", isError = false) {
  if (!progressPanel || !progressFillEl || !progressPercentEl || !progressStepsEl) {
    return;
  }
  const normalized = String(stage || "idle").trim();
  lastProgressStage = normalized;
  if (!normalized || normalized === "idle") {
    progressPanel.classList.add("progress-panel-idle");
    return;
  }
  const progress = stageToProgress(normalized, isError);
  progressPanel.classList.remove("progress-panel-idle");
  progressTitleEl.textContent = message || progress.title;
  progressPercentEl.textContent = `${progress.percent}%`;
  progressFillEl.style.width = `${progress.percent}%`;
  const order = ["extract", "upload", "open", "done"];
  const activeIndex = order.indexOf(progress.active);
  for (const item of Array.from(progressStepsEl.querySelectorAll("li"))) {
    const step = String(item.getAttribute("data-step") || "");
    const stepIndex = order.indexOf(step);
    item.classList.toggle("active", step === progress.active && !isError);
    item.classList.toggle("done", stepIndex >= 0 && activeIndex >= 0 && stepIndex < activeIndex);
  }
}

// #region debug-point A:popup-report
function reportPopupDebug(hypothesisId, msg, data = {}) {
  fetch(DEBUG_SERVER_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      sessionId: DEBUG_SESSION_ID,
      runId: `post-fix-${EXTENSION_VERSION}`,
      hypothesisId,
      location: "popup.js",
      msg: `[DEBUG] ${msg}`,
      data,
      ts: Date.now()
    })
  }).catch(() => {});
}
// #endregion

function normalizeMainUrl(value) {
  const trimmed = String(value || "").trim();
  return (trimmed || DEFAULT_MAIN_URL).replace(/\/+$/, "") + "/";
}

function normalizeBridgeUrl(value) {
  const trimmed = String(value || "").trim();
  return (trimmed || DEFAULT_BRIDGE_URL).replace(/\/+$/, "");
}

async function fetchWithTimeout(url, options = {}, timeoutMs = 2500) {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, {
      ...options,
      cache: "no-store",
      signal: controller.signal
    });
  } finally {
    window.clearTimeout(timeoutId);
  }
}

async function pickFirstReachableUrl(candidates, pathSuffix = "") {
  for (const candidate of candidates) {
    const baseUrl = String(candidate || "").trim();
    if (!baseUrl) {
      continue;
    }
    const url = pathSuffix ? `${baseUrl.replace(/\/+$/, "")}${pathSuffix}` : baseUrl;
    try {
      const response = await fetchWithTimeout(url, { method: "GET" }, 2500);
      if (response.ok) {
        return baseUrl;
      }
    } catch (_error) {
      // Try the next candidate.
    }
  }
  return "";
}

async function resolveLocalDevelopmentConfig() {
  const detectedMainUrl = await pickFirstReachableUrl(LOCAL_MAIN_URL_CANDIDATES);
  const detectedBridgeUrl = await pickFirstReachableUrl(LOCAL_BRIDGE_URL_CANDIDATES, "/health");
  return {
    summarizerUrl: normalizeMainUrl(detectedMainUrl || LOCAL_MAIN_URL),
    bridgeApiUrl: normalizeBridgeUrl(detectedBridgeUrl || LOCAL_BRIDGE_URL),
    bridgeApiToken: "",
    detectedMainUrl: normalizeMainUrl(detectedMainUrl || ""),
    detectedBridgeUrl: normalizeBridgeUrl(detectedBridgeUrl || "")
  };
}

async function loadExtensionConfig() {
  const result = await storageLocalGet(EXTENSION_CONFIG_KEY);
  const config = result?.[EXTENSION_CONFIG_KEY] || {};
  mainUrlInput.value = normalizeMainUrl(config.summarizerUrl || DEFAULT_MAIN_URL);
  bridgeUrlInput.value = normalizeBridgeUrl(config.bridgeApiUrl || DEFAULT_BRIDGE_URL);
}

async function saveExtensionConfig() {
  const normalizedBridgeUrl = normalizeBridgeUrl(bridgeUrlInput.value);
  const config = {
    summarizerUrl: normalizeMainUrl(mainUrlInput.value),
    bridgeApiUrl: normalizedBridgeUrl,
    bridgeApiToken: "",
    fetchWorkerUrl: "",
    fetchWorkerToken: ""
  };
  await storageLocalSet({ [EXTENSION_CONFIG_KEY]: config });
  mainUrlInput.value = config.summarizerUrl;
  bridgeUrlInput.value = config.bridgeApiUrl;
  setStatus(tp("configSaved"));
}

async function resetExtensionConfig() {
  await storageLocalSet({
    [EXTENSION_CONFIG_KEY]: {
      summarizerUrl: DEFAULT_MAIN_URL,
      bridgeApiUrl: DEFAULT_BRIDGE_URL,
      bridgeApiToken: "",
      fetchWorkerUrl: "",
      fetchWorkerToken: ""
    }
  });
  await loadExtensionConfig();
  setStatus(tp("configReset"));
}

function hideHelperPanel() {
  helperPanel.classList.add("helper-panel-hidden");
  helperTitleEl.textContent = tp("helperTitleDefault");
  helperDescEl.textContent = "";
}

function showHelperPanel(title, description, allowGuide = true) {
  helperTitleEl.textContent = title;
  helperDescEl.textContent = description;
  helperGuideBtn.style.display = allowGuide ? "block" : "none";
  helperPanel.classList.remove("helper-panel-hidden");
}

function updateHelperPanelFromResponse(response) {
  const detection = response?.detection || {};
  const reason = String(detection.reason || "");
  const canFallback = Boolean(detection.canFallbackToLocal);

  if (canFallback && reason === "no_platform_caption_tracks") {
    showHelperPanel(
      tp("helperNoCaptionTitle"),
      tp("helperNoCaptionDesc"),
      true,
    );
    return;
  }

  if (canFallback && reason === "no_text_source_found") {
    showHelperPanel(
      tp("helperNoTextTitle"),
      tp("helperNoTextDesc"),
      true,
    );
    return;
  }

  if (reason === "extract_failed") {
    showHelperPanel(
      tp("helperExtractFailedTitle"),
      tp("helperExtractFailedDesc"),
      false,
    );
    return;
  }

  if (reason === "page_not_supported") {
    showHelperPanel(
      tp("helperUnsupportedTitle"),
      tp("helperUnsupportedDesc"),
      false,
    );
    return;
  }

  hideHelperPanel();
}

function buildPayloadId() {
  if (globalThis.crypto && typeof globalThis.crypto.randomUUID === "function") {
    return globalThis.crypto.randomUUID();
  }
  return `bridge_${Date.now()}_${Math.random().toString(16).slice(2)}`;
}

function buildRequestId() {
  if (globalThis.crypto && typeof globalThis.crypto.randomUUID === "function") {
    return globalThis.crypto.randomUUID();
  }
  return `req_${Date.now()}_${Math.random().toString(16).slice(2)}`;
}

function buildTranscriptEnvelope(payloadId, response, transcript, sourceUrl, title) {
  const videoId = parseYouTubeVideoId(sourceUrl);
  const detection = response?.detection || {};
  return {
    schemaVersion: "1.0",
    requestId: buildRequestId(),
    source: {
      kind: "extension",
      sourceType: detection.sourceType && detection.sourceType !== "none" ? detection.sourceType : "subtitle",
      toolVersion: EXTENSION_TOOL_VERSION
    },
    video: {
      platform: String(response?.platform || "youtube"),
      videoId,
      url: sourceUrl,
      title
    },
    transcript: {
      language: "",
      text: transcript,
      segments: [],
      charCount: transcript.length
    },
    diagnostics: {
      textSourceReason: detection.reason || "unknown",
      fallbackUsed: false,
      extensionState: "text_ready",
      notes: payloadId ? [`payload:${payloadId}`] : []
    },
    createdAt: new Date().toISOString()
  };
}

function parseYouTubeVideoId(url) {
  try {
    const parsed = new URL(String(url || ""));
    if (parsed.hostname.includes("youtu.be")) {
      return parsed.pathname.replace(/^\/+/, "").trim();
    }
    const watchId = parsed.searchParams.get("v") || "";
    if (watchId) {
      return watchId;
    }
    const pathParts = parsed.pathname.split("/").filter(Boolean);
    if (pathParts.length >= 2 && ["shorts", "live", "embed"].includes(pathParts[0])) {
      return pathParts[1];
    }
    return "";
  } catch (_error) {
    return "";
  }
}

function buildMainSiteFallbackUrl(sourceUrl, route = "server_direct") {
  const mainUrl = DEFAULT_MAIN_URL;
  const target = new URL(mainUrl);
  const cleanedSourceUrl = String(sourceUrl || "").trim();
  if (cleanedSourceUrl) {
    target.searchParams.set("ext_source_url", cleanedSourceUrl);
  }
  target.searchParams.set("ext_autosubmit", "1");
  target.searchParams.set("ext_route", String(route || "server_direct").trim() || "server_direct");
  return target.toString();
}

async function loadLastFlowStatus() {
  try {
    const result = await storageLocalGet(FLOW_STATUS_KEY);
    const status = result?.[FLOW_STATUS_KEY];
    if (!status?.message) {
      return;
    }
    if (String(status.stage || "") === "done") {
      setStatus("主站已打开，正在自动总结；你可以关闭弹窗。");
      updateProgress("done", "主站已打开，正在自动总结");
      return;
    }
    setStatus(status.message, Boolean(status.isError));
    updateProgress(String(status.stage || "info"), String(status.message || ""), Boolean(status.isError));
  } catch (_error) {
    // Ignore storage read failures in popup.
  }
}

async function loadLastTranscriptForCurrentVideo() {
  try {
    if (transcriptOutput.value.trim()) {
      return;
    }
    const result = await storageLocalGet(LAST_TRANSCRIPT_KEY);
    const cached = result?.[LAST_TRANSCRIPT_KEY];
    const transcript = String(cached?.transcript || "").trim();
    if (!transcript) {
      return;
    }
    const cachedVideoId = parseYouTubeVideoId(cached.sourceUrl || "");
    const currentVideoId = parseYouTubeVideoId(urlInput.value || popupTargetSourceUrl || "");
    if (cachedVideoId && currentVideoId && cachedVideoId !== currentVideoId) {
      return;
    }
    titleInput.value = String(cached.title || titleInput.value || "");
    urlInput.value = String(cached.sourceUrl || urlInput.value || "");
    transcriptOutput.value = transcript;
    lastExtractResponse = {
      ok: true,
      platform: cached.platform || "youtube",
      title: titleInput.value,
      url: urlInput.value,
      transcript,
      detection: cached.detection || null,
      payloadId: cached.payloadId || ""
    };
    setStatus(`已获取字幕：约 ${transcript.length} 字符，正在发送到主站。`);
    updateProgress("uploading", "已获取字幕，正在发送到主站");
    syncActionButtons();
  } catch (_error) {
    // Cached transcript is only a convenience for popup reopen.
  }
}

async function getPreferredTab() {
  const targetVideoId = parseYouTubeVideoId(popupTargetSourceUrl);
  if (Number.isInteger(popupTargetTabId) && popupTargetTabId > 0) {
    try {
      const tab = await getTab(popupTargetTabId);
      if (tab?.id) {
        const tabUrl = String(tab.url || "");
        if (targetVideoId && parseYouTubeVideoId(tabUrl) !== targetVideoId) {
          reportPopupDebug("A", "popup rejected query target tab with mismatched video id", {
            popupTargetSourceUrl,
            popupTargetTabId,
            tabUrl
          });
        } else {
        // #region debug-point A:preferred-target-tab
        reportPopupDebug("A", "popup resolved target tab from query", {
          popupTargetTabId,
          tabId: tab.id,
          url: String(tab.url || ""),
          title: String(tab.title || "")
        });
        // #endregion
        return tab;
        }
      }
    } catch (_error) {
      // Fall back to the currently active tab when the injected target tab no longer exists.
    }
  }
  if (popupTargetSourceUrl) {
    const tabs = await queryTabs({});
    const matchedTab = tabs.find((tab) => {
      const tabUrl = String(tab?.url || "").trim();
      if (!tabUrl) {
        return false;
      }
      if (targetVideoId) {
        return parseYouTubeVideoId(tabUrl) === targetVideoId;
      }
      return tabUrl === popupTargetSourceUrl;
    });
    if (matchedTab?.id) {
      // #region debug-point A:preferred-matched-tab
      reportPopupDebug("A", "popup matched target tab by source url", {
        popupTargetSourceUrl,
        matchedTabId: matchedTab.id,
        matchedTabUrl: String(matchedTab.url || "")
      });
      // #endregion
      return matchedTab;
    }
  }
  return null;
}

async function getActiveTab() {
  const preferredTab = await getPreferredTab();
  if (preferredTab) {
    return preferredTab;
  }
  const currentWindowTabs = await queryTabs({ active: true, currentWindow: true });
  if (currentWindowTabs[0]?.id) {
    // #region debug-point A:current-window-tab
    reportPopupDebug("A", "popup fell back to currentWindow active tab", {
      tabId: currentWindowTabs[0].id,
      url: String(currentWindowTabs[0].url || ""),
      title: String(currentWindowTabs[0].title || "")
    });
    // #endregion
    return currentWindowTabs[0];
  }
  const focusedTabs = await queryTabs({ active: true, lastFocusedWindow: true });
  if (focusedTabs[0]?.id) {
    // #region debug-point A:last-focused-tab
    reportPopupDebug("A", "popup fell back to lastFocusedWindow active tab", {
      tabId: focusedTabs[0].id,
      url: String(focusedTabs[0].url || ""),
      title: String(focusedTabs[0].title || "")
    });
    // #endregion
    return focusedTabs[0];
  }
  reportPopupDebug("A", "popup did not find an active tab in the current or focused window", {});
  return null;
}

function hydratePopupContextFromQuery() {
  if (popupTargetSourceUrl && !urlInput.value.trim()) {
    urlInput.value = popupTargetSourceUrl;
  }
  if (popupTargetTitle && !titleInput.value.trim()) {
    titleInput.value = popupTargetTitle;
  }
}

async function hydratePopupContextFromActiveTab() {
  const tab = await getActiveTab();
  if (!tab) {
    return null;
  }
  const existingVideoId = parseYouTubeVideoId(urlInput.value.trim());
  const tabVideoId = parseYouTubeVideoId(tab.url || "");
  if (existingVideoId && tabVideoId && existingVideoId !== tabVideoId) {
    reportPopupDebug("A", "popup skipped active tab hydration due to video mismatch", {
      existingUrl: urlInput.value.trim(),
      tabUrl: String(tab.url || ""),
      existingVideoId,
      tabVideoId
    });
    return tab;
  }
  if (!urlInput.value.trim()) {
    urlInput.value = String(tab.url || "").trim();
  }
  if (!titleInput.value.trim()) {
    titleInput.value = String(tab.title || "").trim();
  }
  return tab;
}

function isYouTubeWatchUrl(value) {
  const text = String(value || "").trim();
  if (!text) {
    return false;
  }
  try {
    const parsed = new URL(text);
    const host = String(parsed.hostname || "").toLowerCase();
    return host.includes("youtube.com") || host.includes("youtu.be");
  } catch (_error) {
    return text.includes("youtube.com") || text.includes("youtu.be");
  }
}

async function autoStartBackgroundSummarizeFlow() {
  if (autoStartTriggered) {
    return;
  }
  const sourceUrl = String(urlInput.value || popupTargetSourceUrl || "").trim();
  if (!isYouTubeWatchUrl(sourceUrl)) {
    return;
  }
  autoStartTriggered = true;
  try {
    setStatus("已启动后台自动总结；弹窗关闭后任务会继续。主站打开后这里将回到待命。");
    updateProgress("extract_fast", "快速读取当前页面字幕轨道");
    const startResult = await sendRuntimeMessage({
      action: "startBackgroundSummarizeFlowFromPage",
      payload: {
        sourceUrl,
        requestOrigin: String(globalThis.location?.origin || ""),
        requestPageUrl: String(globalThis.location?.href || ""),
        preferLocal: false,
        openMainSite: true
      }
    });
    if (startResult?.deduped) {
      setStatus("同一视频已有后台任务在运行，本次不会重复打开主站；若 90 秒后仍无结果，请再次点击插件。");
      updateProgress("deduped", "同一视频已有后台任务在运行");
      return;
    }
    setStatus("后台任务已启动，弹窗关闭后仍会继续。");
  } catch (error) {
    autoStartTriggered = false;
    setStatus(tp("startSummarizeFlowFailed", { message: ` ${error?.message || error || "unknown_error"}` }), true);
    updateProgress("error", "后台任务启动失败", true);
  }
}

async function sendExtractMessage(tabId) {
  return sendTabMessage(tabId, { action: "extractTranscript" });
}

async function extractYouTubeTranscriptViaPopupDomPanel(tabId) {
  if (!tabId || !extensionApi.scripting?.executeScript) {
    return { ok: false, error: "popup_dom_panel_unsupported" };
  }
  try {
    const injection = executeScript({
      target: { tabId, frameIds: [0] },
      func: async () => {
        const sleep = (ms) => new Promise((resolve) => globalThis.setTimeout(resolve, ms));
        const normalize = (text) => String(text || "")
          .replace(/\u200b/g, "")
          .replace(/[ \t]+\n/g, "\n")
          .replace(/\n{3,}/g, "\n\n")
          .trim();
        const visible = (node) => {
          if (!node) return false;
          const rect = node.getBoundingClientRect();
          const style = globalThis.getComputedStyle(node);
          return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none";
        };
        const qsa = (selector) => Array.from(document.querySelectorAll(selector));
        const searchable = (node) => normalize([
          node?.textContent,
          node?.innerText,
          node?.getAttribute?.("aria-label"),
          node?.getAttribute?.("title"),
          node?.getAttribute?.("data-tooltip-text")
        ].filter(Boolean).join(" | ")).toLowerCase();
        const cleanLine = (line) => {
          let text = normalize(line)
            .replace(/^(?:\d{1,2}:)?\d{1,2}:\d{2}\s*/i, "")
            .replace(/^(?:\d+\s*(?:hours?|hour|hrs?|hr|\u5c0f\u65f6)\s*)?(?:\d+\s*(?:minutes?|minute|mins?|min|\u5206\u949f)\s*)?(?:\d+\s*(?:seconds?|second|secs?|sec|\u79d2\u949f|\u79d2))?\s*/i, "");
          text = normalize(text);
          if (!text || /^(\d{1,2}:)?\d{1,2}:\d{2}$/.test(text) || /^\d+$/.test(text)) return "";
          const lower = text.toLowerCase();
          const skip = ["转写文稿", "转写文本", "内容转写", "内容转文字", "內容轉文字", "文字稿", "字幕", "show transcript", "open transcript", "search in video", "在视频中搜索"];
          if (skip.some((item) => lower === item || lower.includes(item))) return "";
          return text;
        };
        const dedupe = (lines) => {
          const result = [];
          const seen = new Set();
          for (const line of lines.map(cleanLine).filter(Boolean)) {
            if (seen.has(line)) continue;
            seen.add(line);
            result.push(line);
          }
          return result;
        };
        const extractTranscript = () => {
          const segmentNodes = qsa("transcript-segment-view-model, ytd-transcript-segment-renderer, ytd-transcript-segment-renderer .segment-text, ytd-transcript-segment-renderer .cue");
          const lines = [];
          for (const node of segmentNodes) {
            if (!String(node.tagName || "").toLowerCase().includes("transcript-segment-view-model") && !visible(node)) continue;
            const rawLines = normalize(node.innerText || node.textContent || "").split("\n").map(normalize).filter(Boolean);
            const content = normalize(rawLines.map(cleanLine).filter(Boolean).join(" "));
            if (content) lines.push(content);
          }
          let transcript = normalize(dedupe(lines).join("\n"));
          if (transcript.length >= 40) return transcript;

          const panel = document.querySelector("ytd-transcript-search-panel-renderer, ytd-engagement-panel-section-list-renderer[target-id*='transcript'], ytd-engagement-panel-section-list-renderer[target-id='PAmodern_transcript_view']");
          if (!panel) return "";
          transcript = normalize(dedupe(normalize(panel.innerText || panel.textContent || "").split("\n").map(normalize).filter(Boolean)).join("\n"));
          return transcript.length >= 40 ? transcript : "";
        };
        const findClickable = (patterns) => {
          const nodes = qsa("button, [role='button'], [role='menuitem'], tp-yt-paper-button, tp-yt-paper-item, ytd-menu-service-item-renderer, ytd-menu-navigation-item-renderer, yt-list-item-view-model, yt-button-view-model, yt-button-shape button, ytd-button-renderer");
          for (const node of nodes) {
            const text = searchable(node);
            if (!text || !patterns.some((pattern) => text.includes(pattern))) continue;
            const nested = node.querySelector?.("button, [role='button'], [role='menuitem'], tp-yt-paper-button");
            if (nested && visible(nested)) return nested;
            if (visible(node)) return node;
          }
          return null;
        };
        const clickNode = async (node) => {
          if (!node) return false;
          const nested = node.querySelector?.("button, [role='button'], [role='menuitem'], tp-yt-paper-button");
          if (nested && visible(nested)) node = nested;
          try { node.scrollIntoView({ block: "center", inline: "center", behavior: "instant" }); } catch (_error) {}
          try { node.focus({ preventScroll: true }); } catch (_error) {}
          for (const type of ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]) {
            try {
              node.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, composed: true, view: globalThis }));
            } catch (_error) {}
          }
          try { node.click(); } catch (_error) {}
          await sleep(700);
          return true;
        };
        const waitTranscript = async () => {
          for (let i = 0; i < 18; i += 1) {
            const transcript = extractTranscript();
            if (transcript) return transcript;
            await sleep(500);
          }
          return "";
        };
        const trace = [];
        const existing = extractTranscript();
        if (existing) return { ok: true, transcript: existing, debug: { source: "popup_dom_existing", trace } };
        if (await clickNode(findClickable(["show more", "...more", "…more", "more", "更多", "展开", "展開"]))) {
          trace.push("clicked_description_more");
        } else {
          trace.push("description_more_not_found");
        }
        const transcriptButton = findClickable([
          "show transcript",
          "open transcript",
          "transcript",
          "显示文字稿",
          "显示字幕",
          "字幕",
          "文字稿",
          "转写文稿",
          "转写文本",
          "内容转写",
          "内容转文字",
          "內容轉文字",
          "轉錄稿",
          "逐字稿"
        ]);
        if (await clickNode(transcriptButton)) {
          trace.push("clicked_transcript_button");
          const transcript = await waitTranscript();
          if (transcript) return { ok: true, transcript, debug: { source: "popup_dom_panel", trace } };
        } else {
          trace.push("transcript_button_not_found");
        }
        return {
          ok: false,
          error: "popup_dom_panel_not_found",
          debug: {
            trace,
            segmentCount: qsa("transcript-segment-view-model, ytd-transcript-segment-renderer").length,
            bodyHasContentText: normalize(document.body?.innerText || "").includes("内容转文字")
          }
        };
      }
    });
    const [result] = await withTimeout(injection, 18000, "popup_dom_panel_timeout");
    const payload = result?.result || null;
    if (payload?.ok && String(payload.transcript || "").trim()) {
      return {
        ok: true,
        platform: "youtube",
        transcript: String(payload.transcript || "").trim(),
        detection: {
          hasText: true,
          sourceType: "transcript",
          confidence: 0.99,
          reason: "popup_dom_panel",
          canFallbackToLocal: false,
          extractionLogs: [`[Popup] ${String(payload?.debug?.source || "popup_dom_panel")}`]
        },
        debug: payload.debug || {}
      };
    }
    return { ok: false, error: String(payload?.error || "popup_dom_panel_empty"), debug: payload?.debug || {} };
  } catch (error) {
    return { ok: false, error: String(error?.message || error || "popup_dom_panel_failed") };
  }
}

async function runYouTubePopupDomStep(tabId, step) {
  const [result] = await withTimeout(
    executeScript({
      target: { tabId, frameIds: [0] },
      world: "MAIN",
      func: async (stepName) => {
        const normalize = (text) => String(text || "")
          .replace(/\u200b/g, "")
          .replace(/[ \t]+\n/g, "\n")
          .replace(/\n{3,}/g, "\n\n")
          .trim();
        const visible = (node) => {
          if (!node) return false;
          const rect = node.getBoundingClientRect();
          const style = globalThis.getComputedStyle(node);
          return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none";
        };
        const searchable = (node) => normalize([
          node?.textContent,
          node?.innerText,
          node?.getAttribute?.("aria-label"),
          node?.getAttribute?.("title"),
          node?.getAttribute?.("data-tooltip-text")
        ].filter(Boolean).join(" | ")).toLowerCase();
        const cleanLine = (line) => {
          let text = normalize(line)
            .replace(/^(?:\d{1,2}:)?\d{1,2}:\d{2}\s*/i, "")
            .replace(/^(?:\d+\s*(?:hours?|hour|hrs?|hr|\u5c0f\u65f6)\s*)?(?:\d+\s*(?:minutes?|minute|mins?|min|\u5206\u949f)\s*)?(?:\d+\s*(?:seconds?|second|secs?|sec|\u79d2\u949f|\u79d2))?\s*/i, "");
          text = normalize(text);
          if (!text || /^(\d{1,2}:)?\d{1,2}:\d{2}$/.test(text) || /^\d+$/.test(text)) return "";
          const lower = text.toLowerCase();
          const skip = ["转写文稿", "转写文本", "内容转写", "内容转文字", "內容轉文字", "文字稿", "字幕", "show transcript", "open transcript", "search in video", "在视频中搜索"];
          if (skip.some((item) => lower === item || lower.includes(item))) return "";
          return text;
        };
        const dedupe = (lines) => {
          const resultLines = [];
          const seen = new Set();
          for (const line of lines.map(cleanLine).filter(Boolean)) {
            if (seen.has(line)) continue;
            seen.add(line);
            resultLines.push(line);
          }
          return resultLines;
        };
        const extractTranscript = () => {
          const nodes = Array.from(document.querySelectorAll("transcript-segment-view-model, ytd-transcript-segment-renderer, ytd-transcript-segment-renderer .segment-text, ytd-transcript-segment-renderer .cue"));
          const lines = [];
          for (const node of nodes) {
            if (!String(node.tagName || "").toLowerCase().includes("transcript-segment-view-model") && !visible(node)) continue;
            const rawLines = normalize(node.innerText || node.textContent || "").split("\n").map(normalize).filter(Boolean);
            const content = normalize(rawLines.map(cleanLine).filter(Boolean).join(" "));
            if (content) lines.push(content);
          }
          let transcript = normalize(dedupe(lines).join("\n"));
          if (transcript.length >= 40) return transcript;

          const panel = document.querySelector("ytd-transcript-search-panel-renderer, ytd-engagement-panel-section-list-renderer[target-id*='transcript'], ytd-engagement-panel-section-list-renderer[target-id='PAmodern_transcript_view']");
          if (!panel) return "";
          transcript = normalize(dedupe(normalize(panel.innerText || panel.textContent || "").split("\n").map(normalize).filter(Boolean)).join("\n"));
          return transcript.length >= 40 ? transcript : "";
        };
        const extractTextFromRuns = (value) => {
          if (!value) return "";
          if (typeof value === "string") return normalize(value);
          if (Array.isArray(value)) return normalize(value.map(extractTextFromRuns).filter(Boolean).join(""));
          if (Array.isArray(value.runs)) return normalize(value.runs.map(extractTextFromRuns).filter(Boolean).join(""));
          if (typeof value.text === "string") return normalize(value.text);
          if (typeof value.simpleText === "string") return normalize(value.simpleText);
          return "";
        };
        const findValuesByKey = (root, key, output = []) => {
          if (!root || typeof root !== "object") return output;
          if (Object.prototype.hasOwnProperty.call(root, key)) output.push(root[key]);
          for (const value of Object.values(root)) {
            if (value && typeof value === "object") findValuesByKey(value, key, output);
          }
          return output;
        };
        const parseYoutubeiTranscript = (data) => {
          const renderers = findValuesByKey(data, "transcriptSegmentListRenderer");
          const lines = [];
          for (const renderer of renderers) {
            const segments = Array.isArray(renderer?.initialSegments) ? renderer.initialSegments : [];
            for (const segment of segments) {
              const item = segment?.transcriptSegmentRenderer || segment;
              const text = extractTextFromRuns(item?.snippet || item?.cue || item?.content || item?.text || item);
              const cleaned = cleanLine(text);
              if (cleaned) lines.push(cleaned);
            }
          }
          return normalize(dedupe(lines).join("\n"));
        };
        const getTranscriptParamsFromButton = () => {
          const nodes = Array.from(document.querySelectorAll("ytd-button-renderer"));
          for (const node of nodes) {
            const text = searchable(node);
            if (!text || !["内容转文字", "內容轉文字", "转写文稿", "transcript"].some((pattern) => text.includes(pattern))) continue;
            const commands = node?.data?.command?.commandExecutorCommand?.commands || [];
            for (const command of commands) {
              const params = command?.showEngagementPanelEndpoint?.globalConfiguration?.params;
              if (params) return params;
            }
          }
          return "";
        };
        const getYoutubeVideoId = () => {
          try {
            return new URL(location.href).searchParams.get("v") || "";
          } catch (_error) {
            return "";
          }
        };
        const getTranscriptParamsFromInitialData = () => {
          const endpoints = findValuesByKey(globalThis.ytInitialData || {}, "getTranscriptEndpoint");
          for (const endpoint of endpoints) {
            if (endpoint?.params) return String(endpoint.params);
          }
          return "";
        };
        const fetchYoutubeiTranscript = async () => {
          const ytcfg = globalThis.ytcfg;
          const apiKey = String(ytcfg?.get?.("INNERTUBE_API_KEY") || ytcfg?.data_?.INNERTUBE_API_KEY || "");
          const visitorData = String(ytcfg?.get?.("VISITOR_DATA") || ytcfg?.data_?.VISITOR_DATA || "");
          const loggedIn = Boolean(ytcfg?.get?.("LOGGED_IN") || ytcfg?.data_?.LOGGED_IN);
          const baseContext = ytcfg?.get?.("INNERTUBE_CONTEXT") || ytcfg?.data_?.INNERTUBE_CONTEXT || {
            client: {
              clientName: "WEB",
              clientVersion: ytcfg?.get?.("INNERTUBE_CLIENT_VERSION") || ytcfg?.data_?.INNERTUBE_CLIENT_VERSION || "2.20240601.00.00"
            }
          };
          const cloneContext = (overrideClientName = "") => {
            const context = JSON.parse(JSON.stringify(baseContext || {}));
            context.client = context.client && typeof context.client === "object" ? context.client : {};
            context.client.clientName = overrideClientName || context.client.clientName || "WEB";
            context.client.clientVersion = context.client.clientVersion || ytcfg?.get?.("INNERTUBE_CLIENT_VERSION") || ytcfg?.data_?.INNERTUBE_CLIENT_VERSION || "";
            context.client.clientScreen = context.client.clientScreen || "WATCH";
            context.request = context.request && typeof context.request === "object" ? context.request : {};
            context.request.useSsl = true;
            return context;
          };
          const fetchInnertube = async (endpointName, context, body) => {
          const client = context?.client || {};
            const clientNameMap = { WEB: "1", MWEB: "2", ANDROID: "3", IOS: "5", TVHTML5: "7" };
            const url = new URL("/youtubei/v1/" + endpointName, location.origin);
          if (apiKey) url.searchParams.set("key", apiKey);
          url.searchParams.set("prettyPrint", "false");
          const resp = await fetch(url.toString(), {
            method: "POST",
              credentials: "same-origin",
              cache: "no-store",
            headers: {
              "Content-Type": "application/json",
                "X-YouTube-Client-Name": clientNameMap[String(client.clientName || "WEB").toUpperCase()] || "1",
                "X-YouTube-Client-Version": String(client.clientVersion || ""),
                "X-Youtube-Bootstrap-Logged-In": loggedIn ? "true" : "false",
                ...(visitorData ? { "X-Goog-Visitor-Id": visitorData } : {})
            },
              body: JSON.stringify(body)
          });
            const rawText = await resp.text();
            let data = null;
            try { data = JSON.parse(rawText); } catch (_error) {}
            return { ok: resp.ok, status: resp.status, data, bodyPreview: normalize(rawText).slice(0, 120) };
          };
          const paramsCandidates = [];
          const pushParams = (params, source) => {
            const value = String(params || "").trim();
            if (value && !paramsCandidates.some((item) => item.params === value)) paramsCandidates.push({ params: value, source });
          };
          pushParams(getTranscriptParamsFromInitialData(), "ytInitialData");
          const context = cloneContext("WEB");
          if (!paramsCandidates.length) {
            const videoId = getYoutubeVideoId();
            if (videoId) {
              const nextResp = await fetchInnertube("next", context, {
                context,
                videoId,
                contentCheckOk: true,
                racyCheckOk: true
              });
              if (nextResp.ok) {
                const endpoints = findValuesByKey(nextResp.data, "getTranscriptEndpoint");
                for (const endpoint of endpoints) pushParams(endpoint?.params, "youtubei_next");
              }
            }
          }
          pushParams(getTranscriptParamsFromButton(), "panel_button");
          if (!paramsCandidates.length) return { ok: false, error: "youtubei_params_not_found" };
          let lastError = "";
          for (const candidate of paramsCandidates) {
            if (candidate.source === "panel_button") {
              const browseResp = await fetchInnertube("browse", context, { context, params: candidate.params });
              if (browseResp.ok) {
                const browseTranscript = parseYoutubeiTranscript(browseResp.data);
                if (browseTranscript) return { ok: true, transcript: browseTranscript, params: candidate.params, source: "youtubei_browse_panel" };
                lastError = `youtubei_browse_empty:${browseResp.bodyPreview || ""}`;
              } else {
                lastError = `youtubei_browse_http_${browseResp.status}:${browseResp.bodyPreview || ""}`;
              }
            }
            const resp = await fetchInnertube("get_transcript", context, { context, params: candidate.params });
            if (!resp.ok) {
              lastError = `youtubei_http_${resp.status}:${candidate.source}:${resp.bodyPreview || ""}`;
              continue;
            }
            const transcript = parseYoutubeiTranscript(resp.data);
            if (transcript) return { ok: true, transcript, params: candidate.params, source: candidate.source };
            lastError = `youtubei_empty_transcript:${candidate.source}`;
          }
          return { ok: false, error: lastError || "youtubei_empty_transcript" };
        };
        const clickNode = (node) => {
          if (!node) return false;
          if (node?.data?.command) {
            const command = node.data.command;
            const commandHosts = [
              document.querySelector("ytd-watch-flexy"),
              document.querySelector("ytd-app"),
              node
            ].filter(Boolean);
            for (const host of commandHosts) {
              if (typeof host.resolveCommand !== "function") continue;
              try {
                host.resolveCommand(command, {}, false);
                return true;
              } catch (_error) {
                // Try the next command host.
              }
            }
            try {
              node.dispatchEvent(new CustomEvent("yt-action", {
                bubbles: true,
                composed: true,
                detail: {
                  actionName: "yt-service-request",
                  args: [command]
                }
              }));
              return true;
            } catch (_error) {
              // Fall through to component tap/click.
            }
          }
          if (typeof node.onTap === "function") {
            try {
              node.onTap({ type: "tap", target: node, currentTarget: node });
              return true;
            } catch (_error) {
              // Fall through to DOM event dispatch.
            }
          }
          const nested = node.querySelector?.("button, [role='button'], [role='menuitem'], tp-yt-paper-button");
          if (nested && visible(nested)) node = nested;
          try { node.scrollIntoView({ block: "center", inline: "center", behavior: "instant" }); } catch (_error) {}
          try { node.focus({ preventScroll: true }); } catch (_error) {}
          for (const type of ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]) {
            try {
              node.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, composed: true, view: globalThis }));
            } catch (_error) {}
          }
          try { node.click(); } catch (_error) {}
          return true;
        };
        const findClickable = (patterns) => {
          const nodes = Array.from(document.querySelectorAll("button, [role='button'], [role='menuitem'], tp-yt-paper-button, tp-yt-paper-item, ytd-menu-service-item-renderer, ytd-menu-navigation-item-renderer, yt-list-item-view-model, yt-button-view-model, yt-button-shape button, ytd-button-renderer"));
          for (const node of nodes) {
            const text = searchable(node);
            if (!text || !patterns.some((pattern) => text.includes(pattern))) continue;
            if (node?.data?.command && typeof node.onTap === "function" && visible(node)) return node;
            const nested = node.querySelector?.("button, [role='button'], [role='menuitem'], tp-yt-paper-button");
            if (nested && visible(nested)) return nested;
            if (visible(node)) return node;
          }
          return null;
        };
        if (stepName === "extract") {
          const transcript = extractTranscript();
          return {
            ok: Boolean(transcript),
            transcript,
            segmentCount: document.querySelectorAll("transcript-segment-view-model, ytd-transcript-segment-renderer").length
          };
        }
        if (stepName === "fetch_youtubei") {
          return fetchYoutubeiTranscript();
        }
        if (stepName === "click_more") {
          return {
            ok: clickNode(findClickable(["show more", "...more", "…more", "more", "更多", "展开", "展開"])),
            bodyHasContentText: normalize(document.body?.innerText || "").includes("内容转文字")
          };
        }
        if (stepName === "click_transcript") {
          return {
            ok: clickNode(findClickable([
              "show transcript",
              "open transcript",
              "transcript",
              "显示文字稿",
              "显示字幕",
              "字幕",
              "文字稿",
              "转写文稿",
              "转写文本",
              "内容转写",
              "内容转文字",
              "內容轉文字",
              "轉錄稿",
              "逐字稿"
            ])),
            bodyHasContentText: normalize(document.body?.innerText || "").includes("内容转文字")
          };
        }
        return { ok: false, error: "unknown_step" };
      },
      args: [step]
    }),
    5000,
    `popup_dom_step_timeout:${step}`
  );
  return result?.result || { ok: false, error: "popup_dom_step_empty" };
}

async function extractYouTubeTranscriptViaPopupDomPanelStepped(tabId) {
  if (!tabId || !extensionApi.scripting?.executeScript) {
    return { ok: false, error: "popup_dom_panel_unsupported" };
  }
  const trace = [];
  try {
    let extractResult = await runYouTubePopupDomStep(tabId, "extract");
    trace.push(`initial_extract:${Boolean(extractResult?.ok)}:segments=${extractResult?.segmentCount ?? ""}`);
    if (extractResult?.ok && extractResult.transcript) {
      return {
        ok: true,
        platform: "youtube",
        transcript: String(extractResult.transcript || "").trim(),
        detection: {
          hasText: true,
          sourceType: "transcript",
          confidence: 0.99,
          reason: "popup_dom_panel",
          canFallbackToLocal: false,
          extractionLogs: trace
        },
        debug: { source: "popup_dom_existing", trace }
      };
    }

    const youtubeiResult = await runYouTubePopupDomStep(tabId, "fetch_youtubei");
    trace.push(`fetch_youtubei:${Boolean(youtubeiResult?.ok)}:${String(youtubeiResult?.error || "")}`);
    if (youtubeiResult?.ok && youtubeiResult.transcript) {
      return {
        ok: true,
        platform: "youtube",
        transcript: String(youtubeiResult.transcript || "").trim(),
        detection: {
          hasText: true,
          sourceType: "transcript",
          confidence: 0.99,
          reason: "popup_youtubei_get_transcript",
          canFallbackToLocal: false,
          extractionLogs: trace
        },
        debug: { source: "popup_youtubei_get_transcript", trace }
      };
    }

    const moreResult = await runYouTubePopupDomStep(tabId, "click_more");
    trace.push(`click_more:${Boolean(moreResult?.ok)}:bodyHasContentText=${Boolean(moreResult?.bodyHasContentText)}`);
    await sleep(1000);

    const transcriptClickResult = await runYouTubePopupDomStep(tabId, "click_transcript");
    trace.push(`click_transcript:${Boolean(transcriptClickResult?.ok)}:bodyHasContentText=${Boolean(transcriptClickResult?.bodyHasContentText)}`);

    for (let i = 0; i < 20; i += 1) {
      await sleep(500);
      extractResult = await runYouTubePopupDomStep(tabId, "extract");
      if (extractResult?.ok && extractResult.transcript) {
        trace.push(`extract_after_click:${i + 1}:segments=${extractResult?.segmentCount ?? ""}`);
        return {
          ok: true,
          platform: "youtube",
          transcript: String(extractResult.transcript || "").trim(),
          detection: {
            hasText: true,
            sourceType: "transcript",
            confidence: 0.99,
            reason: "popup_dom_panel",
            canFallbackToLocal: false,
            extractionLogs: trace
          },
          debug: { source: "popup_dom_panel_stepped", trace }
        };
      }
    }
    return { ok: false, error: "popup_dom_panel_not_found", debug: { trace } };
  } catch (error) {
    return { ok: false, error: String(error?.message || error || "popup_dom_panel_failed"), debug: { trace } };
  }
}

async function ensureContentScript(tabId) {
  await executeScript({
    target: { tabId },
    files: ["content.js"]
  });
}

/**
 * 鍦?YouTube 椤甸潰鐨勫師鐢熶笂涓嬫枃涓洿鎺ヨ鍙栨挱鏀惧櫒瀛楀箷杞ㄩ亾骞舵姄鍙?transcript銆?
 *
 * 杩欐牱鍙互缁曞紑 content script 闅旂鐜鍜屽悗鍙版姄鍙栧樊寮傦紝浼樺厛鍒╃敤椤甸潰宸叉嬁鍒扮殑鐪熷疄鎾斁鍣ㄦ暟鎹€?
 */
async function extractYouTubeTranscriptViaMainWorld(tabId) {
  try {
    const [injectionResult] = await executeScript({
      target: { tabId },
      world: "MAIN",
      func: async () => {
        const normalizeWhitespace = (text) => String(text || "")
          .replace(/\u200b/g, "")
          .replace(/[ \t]+\n/g, "\n")
          .replace(/\n{3,}/g, "\n\n")
          .trim();

        const fetchWithTimeout = async (url, options = {}, timeoutMs = 15000) => {
          const controller = new AbortController();
          const timeoutId = globalThis.setTimeout(() => controller.abort(), timeoutMs);
          try {
            return await fetch(url, {
              ...options,
              signal: controller.signal
            });
          } finally {
            globalThis.clearTimeout(timeoutId);
          }
        };

        const decodeHtmlEntities = (text) => String(text || "")
          .replace(/&#(\d+);/g, (_match, code) => String.fromCharCode(Number(code)))
          .replace(/&#x([0-9a-f]+);/gi, (_match, code) => String.fromCharCode(parseInt(code, 16)))
          .replace(/&amp;/g, "&")
          .replace(/&lt;/g, "<")
          .replace(/&gt;/g, ">")
          .replace(/&quot;/g, "\"")
          .replace(/&#39;/g, "'")
          .replace(/&nbsp;/g, " ");

        const dedupeTranscriptLines = (lines) => {
          const result = [];
          const seen = new Set();
          for (const rawLine of Array.isArray(lines) ? lines : []) {
            const line = normalizeWhitespace(rawLine);
            if (!line || seen.has(line)) {
              continue;
            }
            seen.add(line);
            result.push(line);
          }
          return result;
        };

        const parseYouTubeJsonTranscript = (payload) => {
          const events = Array.isArray(payload?.events) ? payload.events : [];
          const lines = [];
          for (const event of events) {
            const segs = Array.isArray(event?.segs) ? event.segs : [];
            const line = segs.map((seg) => decodeHtmlEntities(seg?.utf8 || "")).join("");
            const cleaned = normalizeWhitespace(line);
            if (cleaned) {
              lines.push(cleaned);
            }
          }
          return normalizeWhitespace(dedupeTranscriptLines(lines).join("\n"));
        };

        const parseYouTubeXmlTranscript = (xmlText) => {
          const parser = new DOMParser();
          const xml = parser.parseFromString(String(xmlText || ""), "text/xml");
          const nodes = Array.from(xml.getElementsByTagName("text"));
          const lines = nodes
            .map((node) => decodeHtmlEntities(node.textContent || ""))
            .map((line) => normalizeWhitespace(line))
            .filter(Boolean);
          return normalizeWhitespace(dedupeTranscriptLines(lines).join("\n"));
        };

        const parseMaybeJson = (value) => {
          if (!value) {
            return null;
          }
          if (typeof value === "string") {
            try {
              return JSON.parse(value);
            } catch (_error) {
              return null;
            }
          }
          return value;
        };

        const normalizeCaptionTracks = (value) => {
          if (Array.isArray(value)) {
            return value.filter((track) => track && typeof track === "object");
          }
          if (Array.isArray(value?.captionTracks)) {
            return value.captionTracks.filter((track) => track && typeof track === "object");
          }
          if (value && typeof value === "object" && value.baseUrl) {
            return [value];
          }
          return [];
        };

        const getCaptionTracks = () => {
          const candidates = [];
          candidates.push(globalThis.ytInitialPlayerResponse || null);
          candidates.push(parseMaybeJson(globalThis?.ytplayer?.config?.args?.player_response));
          candidates.push(parseMaybeJson(globalThis?.ytcfg?.data_?.PLAYER_VARS?.player_response));
          if (typeof globalThis?.ytcfg?.get === "function") {
            candidates.push(parseMaybeJson(globalThis.ytcfg.get("PLAYER_VARS")?.player_response));
            candidates.push(parseMaybeJson(globalThis.ytcfg.get("PLAYER_RESPONSE")));
          }
          const moviePlayer = document.getElementById("movie_player");
          if (moviePlayer && typeof moviePlayer.getPlayerResponse === "function") {
            candidates.push(moviePlayer.getPlayerResponse());
          }
          for (const playerResponse of candidates) {
            const tracks = playerResponse?.captions?.playerCaptionsTracklistRenderer?.captionTracks;
            if (Array.isArray(tracks) && tracks.length) {
              return tracks;
            }
          }
          if (moviePlayer && typeof moviePlayer.getOption === "function") {
            const optionCandidates = [
              moviePlayer.getOption("captions", "tracklist"),
              moviePlayer.getOption("captions", "playerCaptionsTracklistRenderer"),
              moviePlayer.getOption("captions", "track")
            ];
            for (const candidate of optionCandidates) {
              const tracks = normalizeCaptionTracks(candidate);
              if (tracks.length) {
                return tracks;
              }
            }
          }
          return [];
        };

        const tracks = getCaptionTracks();
        if (!tracks.length) {
          return {
            ok: false,
            error: "main_world_no_caption_tracks",
            debug: {
              trackCount: 0
            }
          };
        }

        const sortedTracks = [...tracks].sort((a, b) => {
          const aPenalty = a?.kind === "asr" ? 1 : 0;
          const bPenalty = b?.kind === "asr" ? 1 : 0;
          return aPenalty - bPenalty;
        });

        for (const track of sortedTracks) {
          const baseUrl = String(track?.baseUrl || "").trim();
          if (!baseUrl) {
            continue;
          }
          const candidates = [];
          try {
            const jsonUrl = new URL(baseUrl);
            jsonUrl.searchParams.set("fmt", "json3");
            candidates.push(jsonUrl.toString());
          } catch (_error) {
            // Ignore malformed track URL and fallback to original.
          }
          candidates.push(baseUrl);

          for (const candidate of candidates) {
            try {
              const resp = await fetchWithTimeout(candidate, {
                method: "GET",
                credentials: "include",
                cache: "no-store"
              });
              if (!resp.ok) {
                continue;
              }
              const rawText = await resp.text();
              const trimmed = rawText.trim();
              if (!trimmed) {
                continue;
              }
              let transcript = "";
              if (trimmed.startsWith("{")) {
                transcript = parseYouTubeJsonTranscript(JSON.parse(trimmed));
              } else {
                transcript = parseYouTubeXmlTranscript(trimmed);
              }
              if (transcript) {
                return {
                  ok: true,
                  transcript,
                  debug: {
                    trackCount: tracks.length,
                    languageCode: String(track?.languageCode || ""),
                    kind: String(track?.kind || ""),
                    fetchUrlType: candidate.includes("fmt=json3") ? "json3" : "base"
                  }
                };
              }
            } catch (_error) {
              // Try next candidate/track.
            }
          }
        }

        return {
          ok: false,
          error: "main_world_caption_fetch_failed",
          debug: {
            trackCount: tracks.length
          }
        };
      }
    });
    return injectionResult?.result || null;
  } catch (_error) {
    return null;
  }
}

async function extractYouTubeTranscriptViaBackground(sourceUrl, options = {}) {
  if (!sourceUrl || (!sourceUrl.includes("youtube.com") && !sourceUrl.includes("youtu.be"))) {
    return null;
  }
  try {
    return await withTimeout(
      sendRuntimeMessage({
        action: "extractYouTubeTranscriptByUrl",
        url: sourceUrl,
        options
      }),
      180000,
      "background_extract_timeout"
    );
  } catch (_error) {
    return { ok: false, error: String(_error?.message || _error || "background_extract_failed") };
  }
}

function buildYouTubeBackgroundSuccessResponse(baseResponse, fallbackResult, tab) {
  const sourceUrl = baseResponse?.url || tab?.url || "";
  const detection = fallbackResult?.detection || {};
  const reason = String(detection.reason || "");
  const helperMessageByReason = {
    main_world_caption_fetch: "已通过当前页面播放器数据直接提取 YouTube 字幕。",
    temp_tab_main_world_caption_fetch: "已通过临时标签页的播放器数据补强提取 YouTube 字幕。",
    temp_tab_content_script_extract: "已通过临时标签页页面结构补强提取 YouTube 字幕。",
    content_script_extract: "已通过当前页面结构补强提取 YouTube 字幕。",
    background_caption_fetch: "已通过扩展后台字幕轨道链路提取 YouTube 字幕。",
    main_world_cuegroups_fallback: "已通过当前页面内嵌 transcript 数据提取 YouTube 字幕。",
    temp_tab_main_world_extract: "已通过临时标签页播放器数据补强提取 YouTube 字幕。",
    server_caption_fetch: "已通过服务端字幕兜底提取 YouTube 字幕。"
  };
  return {
    ...(baseResponse || {}),
    ok: true,
    platform: "youtube",
    title: baseResponse?.title || tab?.title || "",
    url: sourceUrl,
    transcript: fallbackResult.transcript,
    helperMessage: helperMessageByReason[reason] || "已通过扩展字幕轨道补强链路提取 YouTube 字幕。",
    detection: {
      hasText: true,
      sourceType: String(detection.sourceType || "transcript"),
      confidence: Number(detection.confidence || 0.99),
      reason: reason || "background_caption_fetch",
      canFallbackToLocal: false,
      extractionLogs: Array.isArray(detection.extractionLogs) ? detection.extractionLogs : []
    },
    debug: fallbackResult.debug || {}
  };
}

function applyExtractSuccess(response, sourceUrl) {
  titleInput.value = response.title || "";
  urlInput.value = response.url || sourceUrl || "";
  transcriptOutput.value = response.transcript || "";
  const helperText = response.helperMessage ? ` ${response.helperMessage}` : "";
  setStatus(tp("extractSuccess", {
    platform: response.platform,
    count: response.transcript.length,
    helper: helperText,
  }).trim());
  lastExtractResponse = response;
  syncActionButtons();
  updateHelperPanelFromResponse(response);
  return response;
}

async function extractTranscript() {
  const tab = await getActiveTab();
  if (!tab || !tab.id) {
    lastExtractResponse = null;
    syncActionButtons();
    setStatus(tp("pageNotFound"), true);
    return;
  }
  openBtn.disabled = true;
  const activeUrl = String(tab.url || "");
  const requestedVideoId = parseYouTubeVideoId(urlInput.value.trim() || popupTargetSourceUrl);
  const activeVideoId = parseYouTubeVideoId(activeUrl);
  const canUseMainWorld = supportsMainWorldExecution();
  // #region debug-point A:extract-start
  reportPopupDebug("A", "popup extract started", {
    tabId: tab.id,
    activeUrl,
    canUseMainWorld,
    popupTargetTabId,
    popupTargetSourceUrl
  });
  // #endregion

  if (requestedVideoId && activeVideoId && requestedVideoId !== activeVideoId) {
    lastExtractResponse = null;
    syncActionButtons();
    setStatus(`当前标签页视频不匹配，已停止提取，避免读取错误视频。目标: ${requestedVideoId}，当前: ${activeVideoId}`, true);
    reportPopupDebug("A", "popup blocked mismatched active video", {
      requestedVideoId,
      activeVideoId,
      activeUrl,
      popupTargetSourceUrl,
      urlInputValue: urlInput.value.trim()
    });
    return {
      ok: false,
      platform: "youtube",
      title: String(tab.title || ""),
      url: popupTargetSourceUrl || urlInput.value.trim() || activeUrl,
      transcript: "",
      error: "target_video_mismatch",
      helperMessage: "当前标签页不是本次请求的视频，已停止，避免读取错误 transcript。",
      detection: {
        hasText: false,
        sourceType: "unknown",
        confidence: 0,
        reason: "target_video_mismatch",
        canFallbackToLocal: false
      }
    };
  }

  if (activeUrl.includes("youtube.com") || activeUrl.includes("youtu.be")) {
    {
      reportPopupDebug("A", "popup entering youtube fast path", {
        activeUrl,
        extensionVersion: EXTENSION_VERSION,
        tabId: tab.id
      });
      setStatus(tp("extractingYoutubeBackground"));
      try {
        await updateTab(tab.id, { active: true });
        await sleep(1000);
      } catch (_error) {
        // The action popup case already runs against the active YouTube tab.
      }
      if (canUseMainWorld) {
        const mainWorldDirect = await extractYouTubeTranscriptViaMainWorld(tab.id);
        reportPopupDebug("A", "popup youtube main-world direct result", {
          activeUrl,
          extensionVersion: EXTENSION_VERSION,
          ok: Boolean(mainWorldDirect?.ok),
          error: String(mainWorldDirect?.error || ""),
          transcriptLen: String(mainWorldDirect?.transcript || "").trim().length,
          debug: mainWorldDirect?.debug || null
        });
        if (mainWorldDirect?.ok && mainWorldDirect.transcript) {
          const mainWorldResponse = buildYouTubeBackgroundSuccessResponse({
            title: tab.title || "",
            url: activeUrl
          }, mainWorldDirect, tab);
          mainWorldResponse.helperMessage = "已通过当前页面播放器字幕轨道读取文本。";
          mainWorldResponse.detection.reason = "main_world_caption_fetch";
          return applyExtractSuccess(mainWorldResponse, activeUrl);
        }
      }
      let directResult = await extractYouTubeTranscriptViaBackground(activeUrl, {
        allowTemporaryTabs: false,
        allowMatchedTabContentScript: false
      });
      reportPopupDebug("A", "popup youtube background caption-track result", {
        activeUrl,
        extensionVersion: EXTENSION_VERSION,
        ok: Boolean(directResult?.ok),
        error: String(directResult?.error || ""),
        transcriptLen: String(directResult?.transcript || "").trim().length
      });
      if (directResult?.ok && directResult.transcript) {
        const directResponse = buildYouTubeBackgroundSuccessResponse({
          title: tab.title || "",
          url: activeUrl
        }, directResult, tab);
        return applyExtractSuccess(directResponse, activeUrl);
      }
      const popupDomResult = await extractYouTubeTranscriptViaPopupDomPanelStepped(tab.id);
      reportPopupDebug("A", "popup youtube dom panel result", {
        activeUrl,
        extensionVersion: EXTENSION_VERSION,
        ok: Boolean(popupDomResult?.ok),
        error: String(popupDomResult?.error || ""),
        transcriptLen: String(popupDomResult?.transcript || "").trim().length,
        debug: popupDomResult?.debug || null
      });
      if (popupDomResult?.ok && popupDomResult.transcript) {
        const popupDomResponse = buildYouTubeBackgroundSuccessResponse({
          title: tab.title || "",
          url: activeUrl
        }, popupDomResult, tab);
        popupDomResponse.helperMessage = "已通过当前页面 transcript 面板读取文本。";
        popupDomResponse.detection.reason = "popup_dom_panel";
        return applyExtractSuccess(popupDomResponse, activeUrl);
      }
      directResult = await extractYouTubeTranscriptViaBackground(activeUrl, {
        allowTemporaryTabs: false,
        allowMatchedTabContentScript: true
      });
      reportPopupDebug("A", "popup youtube fast path background result", {
        activeUrl,
        extensionVersion: EXTENSION_VERSION,
        ok: Boolean(directResult?.ok),
        error: String(directResult?.error || ""),
        transcriptLen: String(directResult?.transcript || "").trim().length
      });
      if (directResult?.ok && directResult.transcript) {
        const directResponse = buildYouTubeBackgroundSuccessResponse({
          title: tab.title || "",
          url: activeUrl
        }, directResult, tab);
        return applyExtractSuccess(directResponse, activeUrl);
      }
      const youtubeFallbackResponse = {
        ok: false,
        platform: "youtube",
        title: String(tab.title || ""),
        url: activeUrl,
        transcript: "",
        error: String(directResult?.error || "youtube_extract_unavailable"),
        helperMessage: "当前页面提取没有成功；插件已继续尝试调用同一字幕抓取服务。",
        detection: directResult?.detection && typeof directResult.detection === "object"
          ? {
              ...directResult.detection,
              hasText: false,
              sourceType: String(directResult.detection.sourceType || "unknown"),
              reason: String(directResult.detection.reason || directResult?.error || "youtube_extract_unavailable"),
              canFallbackToLocal: false
            }
          : {
              hasText: false,
              sourceType: "unknown",
              confidence: 0.5,
              reason: String(directResult?.error || "youtube_extract_unavailable"),
              canFallbackToLocal: false
            },
        debug: {
          popupDom: popupDomResult && typeof popupDomResult === "object" ? popupDomResult : null,
          background: directResult?.debug && typeof directResult.debug === "object" ? directResult.debug : {}
        }
      };
      reportPopupDebug("A", "popup youtube fast path switching to server fallback", {
        activeUrl,
        extensionVersion: EXTENSION_VERSION,
        backgroundError: String(directResult?.error || ""),
        transcriptLen: String(directResult?.transcript || "").trim().length
      });
      titleInput.value = youtubeFallbackResponse.title;
      urlInput.value = youtubeFallbackResponse.url;
      transcriptOutput.value = "";
      lastExtractResponse = youtubeFallbackResponse;
      syncActionButtons();
      updateHelperPanelFromResponse(youtubeFallbackResponse);
      setStatus(`${tp("serverFallbackReady")} ${youtubeFallbackResponse.helperMessage}`.trim(), true);
      return youtubeFallbackResponse;
    }
  } else {
    setStatus(tp("extractingFromPage"));
  }

  let response = null;
  try {
    response = await sendExtractMessage(tab.id);
  } catch (error) {
    const message = String(error?.message || "");
    // #region debug-point A:extract-send-error
    reportPopupDebug("A", "popup sendExtractMessage failed", {
      tabId: tab.id,
      activeUrl,
      message
    });
    // #endregion
    if (message.includes("Receiving end does not exist")) {
      try {
        setStatus(tp("injectingContentScript"));
        await ensureContentScript(tab.id);
        response = await sendExtractMessage(tab.id);
      } catch (retryError) {
        lastExtractResponse = null;
        syncActionButtons();
        setStatus(tp("extractFailed", { message: retryError.message }), true);
        return;
      }
    } else {
      lastExtractResponse = null;
      syncActionButtons();
      setStatus(tp("extractFailed", { message: message || "unknown_error" }), true);
      return;
    }
  }
  if (!response) {
    lastExtractResponse = null;
    syncActionButtons();
    return;
  }
  // #region debug-point D:page-response
  reportPopupDebug("D", "popup received page extraction response", {
    tabId: tab.id,
    activeUrl,
    ok: Boolean(response?.ok),
    error: String(response?.error || ""),
    transcriptLen: String(response?.transcript || "").trim().length,
    helperMessage: String(response?.helperMessage || ""),
    detection: response?.detection || null
  });
  // #endregion
  if (!response.ok) {
    const sourceUrl = response.url || tab.url || "";
    if (sourceUrl.includes("youtube.com")) {
      let mainWorldFallback = null;
      if (canUseMainWorld) {
        setStatus(tp("pageFallbackMainWorld"));
        mainWorldFallback = await extractYouTubeTranscriptViaMainWorld(tab.id);
        if (mainWorldFallback?.ok && mainWorldFallback.transcript) {
          const mainWorldResponse = buildYouTubeBackgroundSuccessResponse(response, mainWorldFallback, tab);
          mainWorldResponse.helperMessage = "已通过当前页面播放器数据直接提取 YouTube 字幕。";
          mainWorldResponse.detection.reason = "main_world_caption_fetch";
          return applyExtractSuccess(mainWorldResponse, sourceUrl);
        }
      } else {
        setStatus(tp("pageFallbackBackground"));
      }
      const fallbackResult = await extractYouTubeTranscriptViaBackground(sourceUrl, {
        allowTemporaryTabs: false
      });
      // #region debug-point D:background-fallback
      reportPopupDebug("D", "popup background fallback completed", {
        sourceUrl,
        mainWorldError: String(mainWorldFallback?.error || ""),
        backgroundOk: Boolean(fallbackResult?.ok),
        backgroundError: String(fallbackResult?.error || ""),
        backgroundTranscriptLen: String(fallbackResult?.transcript || "").trim().length
      });
      // #endregion
      if (fallbackResult?.ok && fallbackResult.transcript) {
        const backgroundResponse = buildYouTubeBackgroundSuccessResponse(response, fallbackResult, tab);
        return applyExtractSuccess(backgroundResponse, sourceUrl);
      }
      if (
        mainWorldFallback?.error === "main_world_no_caption_tracks" &&
        fallbackResult?.error === "background_no_caption_tracks"
      ) {
        response.detection = {
          ...(response.detection || {}),
          hasText: false,
          sourceType: "none",
          confidence: 0.98,
          reason: "no_platform_caption_tracks",
          canFallbackToLocal: true
        };
        response.helperMessage = "已确认当前视频没有可直接读取的 YouTube 平台字幕轨道；如果画面里能看到字幕，那更像是视频内嵌硬字幕。";
      }
      response.error = `${response.error || "页面提取失败。"} 直连也失败：${mainWorldFallback?.error || "main_world_failed"} / ${fallbackResult?.error || "background_failed"}`;
    }

    const helperText = response.helperMessage ? ` ${response.helperMessage}` : "";
    setStatus((response.error || tp("noTranscriptExtracted")) + helperText, true);
    titleInput.value = response.title || "";
    urlInput.value = response.url || tab.url || "";
    transcriptOutput.value = response.transcript || "";
    lastExtractResponse = response;
    syncActionButtons();
    updateHelperPanelFromResponse(response);
    return;
  }
  return applyExtractSuccess(response, tab.url || "");
}

extensionApi.runtime.onMessage.addListener((message) => {
  if (message?.action !== "summarizeFlowStatus") {
    return;
  }
  const payload = message.payload || {};
  if (String(payload.stage || "") === "done") {
    setStatus("主站已打开，正在自动总结；你可以关闭弹窗。");
    updateProgress("done", "主站已打开，正在自动总结");
    return;
  }
  if (payload.message) {
    setStatus(String(payload.message), Boolean(payload.isError));
    updateProgress(String(payload.stage || "info"), String(payload.message || ""), Boolean(payload.isError));
  }
});

applyPopupTranslations();
setStatus(tp("popupStatusIdle"));
updateProgress("idle");
void (async () => {
  await loadLastFlowStatus();
  await loadExtensionConfig();
  hydratePopupContextFromQuery();
  await hydratePopupContextFromActiveTab();
  await loadLastTranscriptForCurrentVideo();
  await autoStartBackgroundSummarizeFlow();
  syncActionButtons();
})();

globalThis.setInterval(() => {
  void loadLastTranscriptForCurrentVideo();
}, 2000);

extractBtn.addEventListener("click", extractTranscript);

copyBtn.addEventListener("click", async () => {
  const text = transcriptOutput.value.trim();
  if (!text) {
    setStatus(tp("copyEmpty"), true);
    return;
  }
  await navigator.clipboard.writeText(text);
  setStatus(tp("copySuccess"));
});

helperGuideBtn.addEventListener("click", async () => {
  const sourceUrl = String(lastExtractResponse?.url || urlInput.value.trim() || "").trim();
  await createTab({ url: buildMainSiteFallbackUrl(sourceUrl, "server_direct") });
});

copyLinkBtn.addEventListener("click", async () => {
  const currentUrl = urlInput.value.trim();
  if (!currentUrl) {
    setStatus(tp("copyLinkEmpty"), true);
    return;
  }
  await navigator.clipboard.writeText(currentUrl);
  setStatus(tp("copyLinkSuccess"));
});

useLocalMainBtn.addEventListener("click", async () => {
  try {
    setStatus(tp("probingLocal"));
    const localConfig = await resolveLocalDevelopmentConfig();
    mainUrlInput.value = localConfig.summarizerUrl;
    bridgeUrlInput.value = localConfig.bridgeApiUrl;
    await saveExtensionConfig();
    const detailParts = [];
    if (localConfig.detectedMainUrl) {
      detailParts.push(`主站 ${new URL(localConfig.detectedMainUrl).host}`);
    }
    if (localConfig.detectedBridgeUrl) {
      detailParts.push(`Bridge ${new URL(localConfig.detectedBridgeUrl).host}`);
    }
    if (detailParts.length) {
      setStatus(tp("localSwitched", { details: detailParts.join("，") }));
    } else {
      setStatus(tp("localNotDetected"));
    }
  } catch (error) {
    setStatus(tp("switchLocalFailed", { message: error?.message || error || "unknown_error" }), true);
  }
});

saveConfigBtn.addEventListener("click", async () => {
  try {
    await saveExtensionConfig();
  } catch (error) {
      setStatus(tp("saveConfigFailed", { message: error?.message || error || "unknown_error" }), true);
  }
});

resetConfigBtn.addEventListener("click", async () => {
  try {
    await resetExtensionConfig();
  } catch (error) {
      setStatus(tp("resetConfigFailed", { message: error?.message || error || "unknown_error" }), true);
  }
});

openBtn.addEventListener("click", async () => {
  let transcript = transcriptOutput.value.trim();
  let sourceUrl = urlInput.value.trim();
  let response = lastExtractResponse;
  if (!transcript) {
    response = await extractTranscript();
    if (!response || !response.ok) {
      const fallbackSourceUrl = String(response?.url || sourceUrl || urlInput.value || "").trim();
      if (fallbackSourceUrl) {
        await createTab({ url: buildMainSiteFallbackUrl(fallbackSourceUrl, "server_direct") });
        setStatus(tp("autoSwitchToMain"));
        return;
      }
      setStatus(tp("autoExtractFailed"), true);
      return;
    }
    transcript = (response.transcript || "").trim();
    sourceUrl = (response.url || "").trim();
  }
  if (!transcript) {
    setStatus(tp("noTranscriptToSend"), true);
    return;
  }

  try {
    await navigator.clipboard.writeText(transcript);
  } catch (_error) {
    // Clipboard is best-effort fallback.
  }

  const payloadId = buildPayloadId();
  const envelope = buildTranscriptEnvelope(payloadId, response, transcript, sourceUrl, titleInput.value.trim());
  const payload = {
    payloadId,
    transcript,
    sourceUrl,
    title: titleInput.value.trim(),
    createdAt: new Date().toISOString(),
    bridgeVersion: 2,
    envelope
  };

  try {
    setStatus(tp("startSummarizeFlow"));
    await sendRuntimeMessage({
      action: "startSummarizeFlow",
      payload
    });
  } catch (error) {
    const message = String(error?.message || "");
    setStatus(tp("startSummarizeFlowFailed", { message: message ? ` ${message}` : "" }), true);
  }
});

