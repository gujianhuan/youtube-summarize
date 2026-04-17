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

  setStatus("正在打开主站并自动填充字幕...");
  const targetTab = await chrome.tabs.create({ url: SUMMARIZER_URL });

  const injectPayload = async () => {
    if (!targetTab.id) {
      return { filled: false, submitted: false, debug: "missing_tab_id" };
    }
    try {
      const execResults = await chrome.scripting.executeScript({
        target: { tabId: targetTab.id },
        func: (payload) => {
          function sleep(ms) {
            return new Promise((resolve) => window.setTimeout(resolve, ms));
          }

          function isVisibleElement(node) {
            if (!node) {
              return false;
            }
            const rect = node.getBoundingClientRect();
            const style = window.getComputedStyle(node);
            return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none";
          }

          function getElementHint(node) {
            if (!node) {
              return "";
            }
            const parts = [
              node.getAttribute("aria-label") || "",
              node.getAttribute("placeholder") || "",
              node.getAttribute("name") || "",
              node.id || "",
              node.textContent || ""
            ];
            return parts.join(" ").toLowerCase();
          }

          function setNativeValue(element, value) {
            const proto = element instanceof HTMLTextAreaElement
              ? HTMLTextAreaElement.prototype
              : element instanceof HTMLInputElement
                ? HTMLInputElement.prototype
                : Object.getPrototypeOf(element);
            const descriptor = Object.getOwnPropertyDescriptor(proto, "value");
            if (descriptor && descriptor.set) {
              descriptor.set.call(element, value);
            } else {
              element.value = value;
            }
            element.dispatchEvent(new Event("focus", { bubbles: true }));
            element.dispatchEvent(new Event("input", { bubbles: true }));
            element.dispatchEvent(new Event("change", { bubbles: true }));
            element.dispatchEvent(new KeyboardEvent("keyup", { bubbles: true, key: "Enter" }));
            element.dispatchEvent(new Event("blur", { bubbles: true }));
          }

          function matchesTranscriptArea(node) {
            const hint = getElementHint(node);
            return (
              hint.includes("transcript") ||
              hint.includes("字幕文本") ||
              hint.includes("粘贴") ||
              hint.includes("把浏览器扩展提取到的字幕文本粘贴到这里")
            );
          }

          function matchesSourceInput(node) {
            const hint = getElementHint(node);
            return (
              hint.includes("来源链接") ||
              hint.includes("youtube") ||
              hint.includes("bilibili") ||
              hint.includes("watch?v=") ||
              hint.includes("/video/bv")
            );
          }

          async function run() {
            for (let i = 0; i < 20; i += 1) {
              const tabButtons = Array.from(document.querySelectorAll('button[role="tab"], [data-baseweb="tab"] button, button'))
                .filter(isVisibleElement);
              const pasteTab = tabButtons.find((node) => (node.textContent || "").includes("粘贴字幕"));
              if (pasteTab) {
                pasteTab.click();
                await sleep(900);
                break;
              }
              await sleep(500);
            }

            let lastDebug = "";
            for (let attempt = 0; attempt < 24; attempt += 1) {
              const textareas = Array.from(document.querySelectorAll("textarea")).filter(isVisibleElement);
              const transcriptArea = textareas.find(matchesTranscriptArea) || textareas[textareas.length - 1];

              const textInputs = Array.from(document.querySelectorAll('input[type="text"], input:not([type])')).filter(isVisibleElement);
              const sourceInput = textInputs.find(matchesSourceInput);

              lastDebug = `attempt=${attempt}; textareas=${textareas.length}; inputs=${textInputs.length}; transcriptHint=${transcriptArea ? getElementHint(transcriptArea).slice(0, 120) : "none"}; sourceHint=${sourceInput ? getElementHint(sourceInput).slice(0, 120) : "none"}`;

              if (transcriptArea) {
                if (sourceInput) {
                  setNativeValue(sourceInput, payload.sourceUrl || "");
                }
                setNativeValue(transcriptArea, payload.transcript || "");
                transcriptArea.focus();
                await sleep(1200);

                if ((transcriptArea.value || "").trim().length < Math.min(20, payload.transcript.length)) {
                  setNativeValue(transcriptArea, payload.transcript || "");
                  await sleep(1200);
                }

                if ((transcriptArea.value || "").trim().length < Math.min(20, payload.transcript.length)) {
                  lastDebug += `; transcriptValueLen=${(transcriptArea.value || "").trim().length}; sourceValueLen=${sourceInput ? (sourceInput.value || "").trim().length : 0}`;
                  await sleep(800);
                  continue;
                }

                for (let j = 0; j < 10; j += 1) {
                  const actionButtons = Array.from(document.querySelectorAll("button")).filter(isVisibleElement);
                  const summaryButton = actionButtons.find((node) => {
                    const text = (node.textContent || "").trim();
                    return text.includes("总结字幕文本") || text.includes("总结字幕");
                  });
                  if (summaryButton) {
                    summaryButton.click();
                    await sleep(1200);
                    return { filled: true, submitted: true, debug: `${lastDebug}; clicked=${(summaryButton.textContent || "").trim()}` };
                  }
                  await sleep(500);
                }
                return { filled: true, submitted: false, debug: `${lastDebug}; no_visible_summary_button` };
              }
              await sleep(900);
            }
            return { filled: false, submitted: false, debug: lastDebug || "no_visible_fields" };
          }

          return run();
        },
        args: [{ transcript, sourceUrl }]
      });
      return execResults?.[0]?.result || { filled: false, submitted: false, debug: "no_exec_result" };
    } catch (_error) {
      return { filled: false, submitted: false, debug: "execute_script_failed" };
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
      setStatus(`主站已自动填入字幕，但未自动触发总结。${injected.debug || ""}`, true);
    } else {
      setStatus(`主站已打开，但自动填充失败。${injected.debug || ""}`, true);
    }
  };

  chrome.tabs.onUpdated.addListener(listener);
});
