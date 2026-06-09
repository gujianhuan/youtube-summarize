const sourceUrlInput = document.getElementById("sourceUrlInput");
const sourceUrlHint = document.getElementById("sourceUrlHint");
const copySourceUrlBtn = document.getElementById("copySourceUrlBtn");
const contextNotice = document.getElementById("contextNotice");
const guideTitleEl = document.getElementById("guideTitle");
const guideSubtextEl = document.getElementById("guideSubtext");
const needTitleEl = document.getElementById("needTitle");
const needListEl = document.getElementById("needList");
const stepsTitleEl = document.getElementById("stepsTitle");
const stepsListEl = document.getElementById("stepsList");
const sourceSectionTitleEl = document.getElementById("sourceSectionTitle");
const versionTitleEl = document.getElementById("versionTitle");
const versionListEl = document.getElementById("versionList");
const warningTitleEl = document.getElementById("warningTitle");
const warningListEl = document.getElementById("warningList");
const extraTitleEl = document.getElementById("extraTitle");
const extraListEl = document.getElementById("extraList");

const GUIDE_LOCALE = resolveGuideLocale();
const GUIDE_MESSAGES = {
  zh: {
    title: "本地转写助手引导",
    subtext: "当前视频没有可直接提取的公开文本时，才需要使用本地转写助手做兜底转写。",
    needTitle: "什么时候需要它",
    needList: [
      "视频没有公开字幕，也没有可提取的 transcript。",
      "扩展已经明确提示“建议使用本地转写助手”。",
      "你需要先本地转写，再回主站继续总结。"
    ],
    stepsTitle: "你现在要做什么",
    stepsList: [
      "复制当前视频链接。",
      "打开本地转写助手。",
      "把视频链接粘贴进去。",
      "点击开始转写。",
      "转写完成后自动回到主站继续总结。"
    ],
    sourceSectionTitle: "当前视频链接",
    sourcePlaceholder: "这里会显示从扩展带过来的视频链接",
    sourceHintMissing: "如果这里没有链接，请回到视频页面后重新点击扩展里的“查看本地工具说明”。",
    sourceHintReady: "先复制这个链接，再粘贴到本地转写助手里。",
    sourceHintEmpty: "当前没有带入视频链接，请回到视频页面后重新从扩展打开本页。",
    copyButton: "复制视频链接",
    copyMissing: "当前没有可复制的视频链接，请回到扩展重新打开本页。",
    copySuccess: "视频链接已复制，现在可以直接粘贴到本地转写助手。",
    copyFailed: "自动复制失败，请手动选中文本后复制。",
    copyUnhandled: "复制失败，请手动复制当前链接。",
    versionTitle: "版本选择建议",
    versionList: [
      "<strong>在线安装版</strong>：首包更小，首次运行需要联网下载完整运行包。",
      "<strong>便携瘦身版</strong>：包更大，但适合离线分发和测试。",
      "<strong>开发命令行版</strong>：只适合开发者调试，不适合普通用户。"
    ],
    warningTitle: "注意",
    warningList: [
      "如果扩展提示的是“提取失败”，不要急着装本地工具，先重试或手动展开 transcript 面板。",
      "本地工具只处理“确实没有可提取文本”的视频，不应该拿来掩盖扩展故障。",
      "如果视频需要登录验证，可能还需要读取浏览器 cookies。"
    ],
    extraTitle: "补充说明",
    extraList: [
      "在线安装版更适合直接发给朋友，首包更小，但第一次运行必须联网。",
      "便携瘦身版适合离线分发，但包体更大。",
      "如果你只是想继续总结，不需要手动复制 transcript，本地工具完成后会自动回到主站。"
    ],
    noticeNoText: "扩展判断当前视频没有可直接提取的公开文本，所以才建议你改用本地转写助手。",
    noticeExtractFailed: "这次更像是提取失败，不是确认无文本。建议先回视频页重试，或手动展开 transcript/字幕面板后再试一次。"
  },
  en: {
    title: "Local Transcription Helper Guide",
    subtext: "Use the local transcription helper only when the current video has no directly extractable public text.",
    needTitle: "When You Need It",
    needList: [
      "The video has no public captions and no extractable transcript.",
      "The extension explicitly recommends the local transcription helper.",
      "You want local transcription first, then continue summarizing on the main site."
    ],
    stepsTitle: "What To Do Now",
    stepsList: [
      "Copy the current video URL.",
      "Open the local transcription helper.",
      "Paste the video URL into it.",
      "Start transcription.",
      "After transcription completes, return to the main site and continue summarizing."
    ],
    sourceSectionTitle: "Current Video URL",
    sourcePlaceholder: "The video URL passed from the extension will appear here",
    sourceHintMissing: "If no link appears here, go back to the video page and open this guide again from the extension.",
    sourceHintReady: "Copy this link first, then paste it into the local transcription helper.",
    sourceHintEmpty: "No video URL was passed in. Return to the video page and reopen this guide from the extension.",
    copyButton: "Copy Video URL",
    copyMissing: "There is no video URL to copy. Reopen this page from the extension.",
    copySuccess: "Video URL copied. You can now paste it into the local transcription helper.",
    copyFailed: "Automatic copy failed. Please select the text and copy it manually.",
    copyUnhandled: "Copy failed. Please copy the current link manually.",
    versionTitle: "Version Suggestions",
    versionList: [
      "<strong>Online installer</strong>: smaller initial package, but downloads the full runtime on first launch.",
      "<strong>Portable slim build</strong>: larger package, but better for offline sharing and testing.",
      "<strong>Developer CLI build</strong>: only for development and debugging, not for regular users."
    ],
    warningTitle: "Notes",
    warningList: [
      "If the extension says extraction failed, do not jump to the local tool immediately. Retry first or manually open the transcript panel.",
      "The local tool is only for videos that truly have no extractable text. It should not hide extension failures.",
      "If the video requires login, browser cookies may also be needed."
    ],
    extraTitle: "Extra Notes",
    extraList: [
      "The online installer is easier to share because the package is smaller, but the first launch requires network access.",
      "The portable slim build is better for offline distribution, but the package is larger.",
      "If you only want to continue summarizing, you usually do not need to copy the transcript manually. The local tool can take you back to the main site after it finishes."
    ],
    noticeNoText: "The extension determined that this video has no directly extractable public text, which is why it recommends the local transcription helper.",
    noticeExtractFailed: "This looks more like an extraction failure than confirmed missing text. Go back to the video page, retry, or manually open the transcript/caption panel and try again."
  }
};

function resolveGuideLocale() {
  const candidate = String(navigator.language || "").trim().toLowerCase();
  return candidate.startsWith("zh") ? "zh" : "en";
}

function tg(key) {
  return GUIDE_MESSAGES[GUIDE_LOCALE]?.[key] || GUIDE_MESSAGES.zh[key] || "";
}

function renderList(container, items) {
  container.innerHTML = "";
  for (const item of items) {
    const li = document.createElement("li");
    li.innerHTML = item;
    container.appendChild(li);
  }
}

function applyGuideTranslations() {
  document.documentElement.lang = GUIDE_LOCALE === "zh" ? "zh-CN" : "en";
  document.title = tg("title");
  guideTitleEl.textContent = tg("title");
  guideSubtextEl.textContent = tg("subtext");
  needTitleEl.textContent = tg("needTitle");
  renderList(needListEl, tg("needList"));
  stepsTitleEl.textContent = tg("stepsTitle");
  renderList(stepsListEl, tg("stepsList"));
  sourceSectionTitleEl.textContent = tg("sourceSectionTitle");
  sourceUrlInput.placeholder = tg("sourcePlaceholder");
  sourceUrlHint.textContent = tg("sourceHintMissing");
  copySourceUrlBtn.textContent = tg("copyButton");
  versionTitleEl.textContent = tg("versionTitle");
  renderList(versionListEl, tg("versionList"));
  warningTitleEl.textContent = tg("warningTitle");
  renderList(warningListEl, tg("warningList"));
  extraTitleEl.textContent = tg("extraTitle");
  renderList(extraListEl, tg("extraList"));
}

/**
 * Safely reads a query parameter from the current guide page URL.
 * Invalid URLs or missing parameters resolve to an empty string.
 *
 * @param {string} name Query parameter name.
 * @returns {string}
 */
function readQueryParam(name) {
  try {
    const currentUrl = new URL(window.location.href);
    return String(currentUrl.searchParams.get(name) || "").trim();
  } catch (_error) {
    return "";
  }
}

/**
 * Shows a compact banner that explains why the guide page was opened.
 *
 * @param {string} reason Detection reason passed from popup.
 * @returns {void}
 */
function renderContextNotice(reason) {
  if (reason === "no_text_source_found") {
    contextNotice.textContent = tg("noticeNoText");
    contextNotice.classList.remove("context-notice-hidden");
    return;
  }

  if (reason === "extract_failed") {
    contextNotice.textContent = tg("noticeExtractFailed");
    contextNotice.classList.remove("context-notice-hidden");
    return;
  }

  contextNotice.classList.add("context-notice-hidden");
}

/**
 * Updates the link area with the incoming source URL.
 *
 * @param {string} sourceUrl Current video URL.
 * @returns {void}
 */
function renderSourceUrl(sourceUrl) {
  sourceUrlInput.value = sourceUrl;
  copySourceUrlBtn.disabled = !sourceUrl;
  sourceUrlHint.textContent = sourceUrl
    ? tg("sourceHintReady")
    : tg("sourceHintEmpty");
}

/**
 * Copies the current source URL for the local helper flow.
 *
 * @returns {Promise<void>}
 */
async function handleCopySourceUrl() {
  const sourceUrl = sourceUrlInput.value.trim();
  if (!sourceUrl) {
    sourceUrlHint.textContent = tg("copyMissing");
    return;
  }

  try {
    await navigator.clipboard.writeText(sourceUrl);
    sourceUrlHint.textContent = tg("copySuccess");
  } catch (_error) {
    sourceUrlInput.focus();
    sourceUrlInput.select();
    sourceUrlHint.textContent = tg("copyFailed");
  }
}

function initGuidePage() {
  const sourceUrl = readQueryParam("sourceUrl");
  const reason = readQueryParam("reason");
  renderContextNotice(reason);
  renderSourceUrl(sourceUrl);
}

copySourceUrlBtn.addEventListener("click", () => {
  handleCopySourceUrl().catch(() => {
    sourceUrlHint.textContent = tg("copyUnhandled");
  });
});

applyGuideTranslations();
initGuidePage();
