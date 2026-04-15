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

  setStatus("正在打开主站并自动填充字幕...");
  const targetTab = await chrome.tabs.create({ url: SUMMARIZER_URL });

  const injectPayload = async () => {
    if (!targetTab.id) {
      return { filled: false, submitted: false };
    }
    try {
      const execResults = await chrome.scripting.executeScript({
        target: { tabId: targetTab.id },
        func: (payload) => {
          function sleep(ms) {
            return new Promise((resolve) => window.setTimeout(resolve, ms));
          }

          function setNativeValue(element, value) {
            const prototype = Object.getPrototypeOf(element);
            const descriptor = Object.getOwnPropertyDescriptor(prototype, "value");
            if (descriptor && descriptor.set) {
              descriptor.set.call(element, value);
            } else {
              element.value = value;
            }
            element.dispatchEvent(new Event("input", { bubbles: true }));
            element.dispatchEvent(new Event("change", { bubbles: true }));
          }

          async function run() {
            for (let i = 0; i < 20; i += 1) {
              const tabButtons = Array.from(document.querySelectorAll('button[role="tab"], [data-baseweb="tab"] button, button'));
              const pasteTab = tabButtons.find((node) => (node.textContent || "").includes("粘贴字幕"));
              if (pasteTab) {
                pasteTab.click();
                break;
              }
              await sleep(500);
            }

            for (let i = 0; i < 30; i += 1) {
              const textareas = Array.from(document.querySelectorAll('textarea'));
              const transcriptArea = textareas.find((node) => {
                const label = node.getAttribute("aria-label") || node.getAttribute("placeholder") || "";
                return label.includes("transcript") || label.includes("字幕文本") || label.includes("粘贴");
              }) || textareas[0];

              const textInputs = Array.from(document.querySelectorAll('input[type="text"], input:not([type])'));
              const sourceInput = textInputs.find((node) => {
                const label = node.getAttribute("aria-label") || node.getAttribute("placeholder") || "";
                return label.includes("来源链接") || label.includes("youtube") || label.includes("bilibili");
              });

              if (transcriptArea) {
                if (sourceInput) {
                  setNativeValue(sourceInput, payload.sourceUrl || "");
                }
                setNativeValue(transcriptArea, payload.transcript || "");
                transcriptArea.focus();
                await sleep(700);

                for (let j = 0; j < 20; j += 1) {
                  const actionButtons = Array.from(document.querySelectorAll("button"));
                  const summaryButton = actionButtons.find((node) => {
                    const text = (node.textContent || "").trim();
                    return text.includes("总结字幕文本");
                  });
                  if (summaryButton) {
                    summaryButton.click();
                    return { filled: true, submitted: true };
                  }
                  await sleep(400);
                }
                return { filled: true, submitted: false };
              }
              await sleep(500);
            }
            return { filled: false, submitted: false };
          }

          return run();
        },
        args: [{ transcript, sourceUrl }]
      });
      return execResults?.[0]?.result || { filled: false, submitted: false };
    } catch (_error) {
      return { filled: false, submitted: false };
    }
  };

  const listener = async (tabId, changeInfo) => {
    if (tabId !== targetTab.id || changeInfo.status !== "complete") {
      return;
    }
    chrome.tabs.onUpdated.removeListener(listener);
    const injected = await injectPayload();
    if (injected.submitted) {
      setStatus("已自动打开主站并触发总结，请稍候查看结果。");
    } else if (injected.filled) {
      setStatus("主站已自动填入字幕，但未自动触发总结。请在主站手动点一次总结。", true);
    } else {
      setStatus("主站已打开，但自动填充失败。请手动粘贴。", true);
    }
  };

  chrome.tabs.onUpdated.addListener(listener);
});
