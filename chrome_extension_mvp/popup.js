const statusEl = document.getElementById("status");
const titleInput = document.getElementById("titleInput");
const urlInput = document.getElementById("urlInput");
const transcriptOutput = document.getElementById("transcriptOutput");
const extractBtn = document.getElementById("extractBtn");
const copyBtn = document.getElementById("copyBtn");
const openBtn = document.getElementById("openBtn");

const SUMMARIZER_URL = "https://youtube-summarize-0oms.onrender.com/";
const BRIDGE_STORAGE_PREFIX = "yt_summary_bridge:";
const BRIDGE_WRITE_RETRY_COUNT = 25;
const BRIDGE_WRITE_RETRY_DELAY_MS = 700;

function setStatus(text, isError = false) {
  statusEl.textContent = text;
  statusEl.style.color = isError ? "#dc2626" : "#4b5563";
}

function sleep(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function buildPayloadId() {
  if (globalThis.crypto && typeof globalThis.crypto.randomUUID === "function") {
    return globalThis.crypto.randomUUID();
  }
  return `bridge_${Date.now()}_${Math.random().toString(16).slice(2)}`;
}

function buildBridgeStorageKey(payloadId) {
  return `${BRIDGE_STORAGE_PREFIX}${payloadId}`;
}

function buildBridgeUrl(payloadId, sourceUrl) {
  const url = new URL(SUMMARIZER_URL);
  url.searchParams.set("ext_payload_id", payloadId);
  url.searchParams.set("ext_autosubmit", "1");
  if (sourceUrl) {
    url.searchParams.set("ext_source_url", sourceUrl);
  }
  return url.toString();
}

/**
 * 将 transcript 写入主站同域 storage，避免继续依赖脆弱的 DOM 自动填表。
 */
async function writeBridgePayload(tabId, payloadId, payload) {
  if (!tabId) {
    throw new Error("missing_tab_id");
  }

  const storageKey = buildBridgeStorageKey(payloadId);
  const payloadJson = JSON.stringify(payload);
  let lastError = "";

  for (let attempt = 0; attempt < BRIDGE_WRITE_RETRY_COUNT; attempt += 1) {
    try {
      const execResults = await chrome.scripting.executeScript({
        target: { tabId },
        func: ({ key, value }) => {
          try {
            window.localStorage.setItem(key, value);
            window.sessionStorage.setItem(key, value);
            return { ok: true };
          } catch (error) {
            return {
              ok: false,
              error: String(error?.message || error || "storage_write_failed")
            };
          }
        },
        args: [{ key: storageKey, value: payloadJson }]
      });
      const result = execResults?.[0]?.result;
      if (result?.ok) {
        return;
      }
      lastError = String(result?.error || "bridge_write_failed");
    } catch (error) {
      lastError = String(error?.message || error || "bridge_write_failed");
    }

    await sleep(BRIDGE_WRITE_RETRY_DELAY_MS);
  }

  throw new Error(lastError || "bridge_write_failed");
}

/**
 * 等待目标页初步可用，降低页面尚未初始化时写 storage 失败的概率。
 */
async function waitForBridgeReady(tabId) {
  if (!tabId) {
    throw new Error("missing_tab_id");
  }

  for (let attempt = 0; attempt < 20; attempt += 1) {
    try {
      const execResults = await chrome.scripting.executeScript({
        target: { tabId },
        func: () => {
          try {
            const readyState = document.readyState;
            const hasBody = Boolean(document.body);
            const canUseStorage = typeof window.localStorage !== "undefined" && typeof window.sessionStorage !== "undefined";
            return {
              ok: hasBody && canUseStorage && (readyState === "interactive" || readyState === "complete"),
              readyState,
              hasBody,
              canUseStorage
            };
          } catch (error) {
            return {
              ok: false,
              error: String(error?.message || error || "bridge_probe_failed")
            };
          }
        }
      });
      const result = execResults?.[0]?.result;
      if (result?.ok) {
        return;
      }
    } catch (_error) {
      // Continue retrying until the page becomes scriptable.
    }
    await sleep(400);
  }

  throw new Error("bridge_target_not_ready");
}

async function getActiveTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab;
}

async function sendExtractMessage(tabId) {
  return chrome.tabs.sendMessage(tabId, { action: "extractTranscript" });
}

async function ensureContentScript(tabId) {
  await chrome.scripting.executeScript({
    target: { tabId },
    files: ["content.js"]
  });
}

async function extractTranscript() {
  const tab = await getActiveTab();
  if (!tab || !tab.id) {
    setStatus("未找到当前页面。", true);
    return;
  }
  setStatus("正在向页面请求字幕...");
  let response = null;
  try {
    response = await sendExtractMessage(tab.id);
  } catch (error) {
    const message = String(error?.message || "");
    if (message.includes("Receiving end does not exist")) {
      try {
        setStatus("当前页面未注入扩展脚本，正在自动补注入后重试...");
        await ensureContentScript(tab.id);
        response = await sendExtractMessage(tab.id);
      } catch (retryError) {
        setStatus(`提取失败: ${retryError.message}`, true);
        return;
      }
    } else {
      setStatus(`提取失败: ${message || "未知错误"}`, true);
      return;
    }
  }
  if (!response) {
    return;
  }
  if (!response.ok) {
    const helperText = response.helperMessage ? ` ${response.helperMessage}` : "";
    setStatus((response.error || "未提取到字幕。") + helperText, true);
    titleInput.value = response.title || "";
    urlInput.value = response.url || tab.url || "";
    transcriptOutput.value = response.transcript || "";
    copyBtn.disabled = !transcriptOutput.value.trim();
    return;
  }
  titleInput.value = response.title || "";
  urlInput.value = response.url || tab.url || "";
  transcriptOutput.value = response.transcript || "";
  copyBtn.disabled = !response.transcript.trim();
  const helperText = response.helperMessage ? ` ${response.helperMessage}` : "";
  setStatus(`提取完成：${response.platform}，约 ${response.transcript.length} 字符。${helperText}`);
  return response;
}

extractBtn.addEventListener("click", extractTranscript);

copyBtn.addEventListener("click", async () => {
  const text = transcriptOutput.value.trim();
  if (!text) {
    setStatus("没有可复制的字幕文本。", true);
    return;
  }
  await navigator.clipboard.writeText(text);
  setStatus("已复制字幕文本，请回到主站粘贴总结。");
});

openBtn.addEventListener("click", async () => {
  let transcript = transcriptOutput.value.trim();
  let sourceUrl = urlInput.value.trim();
  if (!transcript) {
    const response = await extractTranscript();
    if (!response || !response.ok) {
      setStatus("未能自动提取字幕，无法发送到主站。", true);
      return;
    }
    transcript = (response.transcript || "").trim();
    sourceUrl = (response.url || "").trim();
  }
  if (!transcript) {
    setStatus("没有可发送的字幕文本。", true);
    return;
  }

  try {
    await navigator.clipboard.writeText(transcript);
  } catch (_error) {
    // Clipboard is best-effort fallback.
  }

  const payloadId = buildPayloadId();
  const payload = {
    payloadId,
    transcript,
    sourceUrl,
    title: titleInput.value.trim(),
    createdAt: new Date().toISOString(),
    bridgeVersion: 1
  };

  setStatus("正在打开主站并通过 bridge 发送 transcript...");
  const targetTab = await chrome.tabs.create({ url: buildBridgeUrl(payloadId, sourceUrl) });

  try {
    await waitForBridgeReady(targetTab.id);
    await writeBridgePayload(targetTab.id, payloadId, payload);
    setStatus("已发送到主站 bridge，主站将自动接收并开始总结。");
  } catch (error) {
    setStatus(`bridge 发送失败，字幕已复制到剪贴板，可手动粘贴。${error?.message ? ` ${error.message}` : ""}`, true);
  }
});
