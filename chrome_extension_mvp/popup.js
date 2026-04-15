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

async function extractTranscript() {
  const tab = await getActiveTab();
  if (!tab || !tab.id) {
    setStatus("未找到当前页面。", true);
    return;
  }
  setStatus("正在向页面请求字幕...");
  const response = await chrome.tabs.sendMessage(tab.id, { action: "extractTranscript" }).catch((error) => {
    setStatus(`提取失败: ${error.message}`, true);
    return null;
  });
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
  await chrome.tabs.create({ url: SUMMARIZER_URL });
});
