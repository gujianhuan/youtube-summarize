const sourceUrlInput = document.getElementById("sourceUrlInput");
const sourceUrlHint = document.getElementById("sourceUrlHint");
const copySourceUrlBtn = document.getElementById("copySourceUrlBtn");
const contextNotice = document.getElementById("contextNotice");

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
    contextNotice.textContent = "扩展判断当前视频没有可直接提取的公开文本，所以才建议你改用本地转写助手。";
    contextNotice.classList.remove("context-notice-hidden");
    return;
  }

  if (reason === "extract_failed") {
    contextNotice.textContent = "这次更像是提取失败，不是确认无文本。建议先回视频页重试，或手动展开 transcript/字幕面板后再试一次。";
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
    ? "先复制这个链接，再粘贴到本地转写助手里。"
    : "当前没有带入视频链接，请回到视频页面后重新从扩展打开本页。";
}

/**
 * Copies the current source URL for the local helper flow.
 *
 * @returns {Promise<void>}
 */
async function handleCopySourceUrl() {
  const sourceUrl = sourceUrlInput.value.trim();
  if (!sourceUrl) {
    sourceUrlHint.textContent = "当前没有可复制的视频链接，请回到扩展重新打开本页。";
    return;
  }

  try {
    await navigator.clipboard.writeText(sourceUrl);
    sourceUrlHint.textContent = "视频链接已复制，现在可以直接粘贴到本地转写助手。";
  } catch (_error) {
    sourceUrlInput.focus();
    sourceUrlInput.select();
    sourceUrlHint.textContent = "自动复制失败，请手动选中文本后复制。";
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
    sourceUrlHint.textContent = "复制失败，请手动复制当前链接。";
  });
});

initGuidePage();
