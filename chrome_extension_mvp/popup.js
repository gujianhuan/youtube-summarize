const statusEl = document.getElementById("status");
const titleInput = document.getElementById("titleInput");
const urlInput = document.getElementById("urlInput");
const transcriptOutput = document.getElementById("transcriptOutput");
const extractBtn = document.getElementById("extractBtn");
const copyBtn = document.getElementById("copyBtn");
const openBtn = document.getElementById("openBtn");

const SUMMARIZER_URL = "https://youtube-summarize-0oms.onrender.com/";

function setStatus(text, isError = false) {
  statusEl.textContent = text;
  statusEl.style.color = isError ? "#dc2626" : "#4b5563";
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

  const params = new URLSearchParams({
    ext_payload_id: String(Date.now()),
    ext_autosubmit: "1",
    ext_source_url: sourceUrl,
    ext_transcript: transcript
  });
  const targetUrl = `${SUMMARIZER_URL}?${params.toString()}`;
  setStatus("正在打开主站并自动带入 transcript...");
  await chrome.tabs.create({ url: targetUrl });
  setStatus("已打开主站，主站将自动接收 transcript 并开始总结。");
});
