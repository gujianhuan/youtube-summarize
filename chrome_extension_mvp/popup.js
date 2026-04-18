const statusEl = document.getElementById("status");
const titleInput = document.getElementById("titleInput");
const urlInput = document.getElementById("urlInput");
const transcriptOutput = document.getElementById("transcriptOutput");
const extractBtn = document.getElementById("extractBtn");
const copyBtn = document.getElementById("copyBtn");
const openBtn = document.getElementById("openBtn");

const SUMMARIZER_URL = "https://youtube-summarize-0oms.onrender.com/";
const BRIDGE_API_URL = "https://youtube-summarize-bridge.onrender.com";
const BRIDGE_API_TOKEN = "";

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
 * 将 transcript 发送到独立 bridge API，由主站再按 payload_id 拉取。
 */
async function uploadBridgePayload(payload) {
  const headers = {
    "Content-Type": "application/json"
  };
  if (BRIDGE_API_TOKEN) {
    headers["X-Bridge-Token"] = BRIDGE_API_TOKEN;
  }

  let response;
  try {
    response = await fetch(`${BRIDGE_API_URL}/api/bridge/payload`, {
      method: "POST",
      headers,
      body: JSON.stringify(payload)
    });
  } catch (error) {
    throw new Error(`bridge_api_request_failed:${error?.message || "network_error"}`);
  }

  let result = null;
  try {
    result = await response.json();
  } catch (_error) {
    throw new Error(`bridge_api_invalid_json:http_${response.status}`);
  }

  if (!response.ok || !result?.ok) {
    throw new Error(String(result?.error || `http_${response.status}`));
  }

  return result;
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

  try {
    setStatus("正在上传 transcript 到 Bridge API...");
    const result = await uploadBridgePayload(payload);
    const finalPayloadId = String(result?.payload_id || payloadId);
    await chrome.tabs.create({ url: buildBridgeUrl(finalPayloadId, sourceUrl) });
    setStatus("已上传到 Bridge API，主站将自动拉取并开始总结。");
  } catch (error) {
    await chrome.tabs.create({ url: buildBridgeUrl(payloadId, sourceUrl) });
    setStatus(`Bridge API 上传失败，字幕已复制到剪贴板，可手动粘贴。${error?.message ? ` ${error.message}` : ""}`, true);
  }
});
