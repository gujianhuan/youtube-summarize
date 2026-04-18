const SUMMARIZER_URL = "https://youtube-summarize-0oms.onrender.com/";
const BRIDGE_API_URL = "https://youtube-summarize-bridge.onrender.com";
const BRIDGE_API_TOKEN = "";
const FLOW_STATUS_KEY = "summarizerFlowStatus";

function buildBridgeUrl(payloadId, sourceUrl) {
  const url = new URL(SUMMARIZER_URL);
  if (payloadId) {
    url.searchParams.set("ext_payload_id", payloadId);
    url.searchParams.set("ext_autosubmit", "1");
  }
  if (sourceUrl) {
    url.searchParams.set("ext_source_url", sourceUrl);
  }
  return url.toString();
}

async function setFlowStatus(message, isError = false, stage = "info") {
  const payload = {
    message,
    isError,
    stage,
    updatedAt: new Date().toISOString()
  };
  await chrome.storage.local.set({ [FLOW_STATUS_KEY]: payload });
  try {
    await chrome.runtime.sendMessage({ action: "summarizeFlowStatus", payload });
  } catch (_error) {
    // Popup may already be closed; storage persists the latest status for inspection.
  }
}

async function uploadBridgePayload(payload) {
  const headers = {
    "Content-Type": "application/json"
  };
  if (BRIDGE_API_TOKEN) {
    headers["X-Bridge-Token"] = BRIDGE_API_TOKEN;
  }

  const controller = new AbortController();
  const timeoutId = globalThis.setTimeout(() => controller.abort(), 8000);
  let response;

  try {
    response = await fetch(`${BRIDGE_API_URL}/api/bridge/payload`, {
      method: "POST",
      headers,
      body: JSON.stringify(payload),
      signal: controller.signal
    });
  } catch (error) {
    const name = String(error?.name || "");
    if (name === "AbortError") {
      throw new Error("bridge_api_timeout");
    }
    throw new Error(`bridge_api_request_failed:${error?.message || "network_error"}`);
  } finally {
    globalThis.clearTimeout(timeoutId);
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

async function startSummarizeFlow(payload) {
  const sourceUrl = String(payload?.sourceUrl || "");
  await setFlowStatus("正在打开主站...", false, "opening");
  const targetTab = await chrome.tabs.create({ url: buildBridgeUrl("", sourceUrl) });

  try {
    await setFlowStatus("主站已打开，正在上传 transcript...", false, "uploading");
    const result = await uploadBridgePayload(payload);
    const finalPayloadId = String(result?.payload_id || payload?.payloadId || "");
    if (targetTab.id && finalPayloadId) {
      await chrome.tabs.update(targetTab.id, { url: buildBridgeUrl(finalPayloadId, sourceUrl) });
    }
    await setFlowStatus("已发送 transcript，主站正在自动拉取并开始总结。", false, "done");
  } catch (error) {
    const message = String(error?.message || "");
    await setFlowStatus(
      `主站已打开并带上来源链接；bridge 上传失败，字幕已复制到剪贴板，可手动粘贴。${message ? ` ${message}` : ""}`,
      true,
      "error"
    );
  }
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.action !== "startSummarizeFlow") {
    return undefined;
  }

  (async () => {
    try {
      await startSummarizeFlow(message.payload || {});
      sendResponse({ ok: true });
    } catch (error) {
      sendResponse({ ok: false, error: String(error?.message || error || "start_flow_failed") });
    }
  })();

  return true;
});
