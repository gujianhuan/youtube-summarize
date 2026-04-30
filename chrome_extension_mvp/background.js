const DEFAULT_SUMMARIZER_URL = "https://youtube-summarize-0oms.onrender.com/";
const DEFAULT_BRIDGE_API_URL = "https://youtube-summarize-bridge.onrender.com";
const DEFAULT_BRIDGE_API_TOKEN = "";
const EXTENSION_CONFIG_KEY = "summarizerExtensionConfig";
const FLOW_STATUS_KEY = "summarizerFlowStatus";
const BRIDGE_HEALTH_TIMEOUT_MS = 15000;
const BRIDGE_UPLOAD_TIMEOUT_MS = 20000;
const BRIDGE_UPLOAD_RETRY_DELAY_MS = 1200;

function normalizeBaseUrl(value, fallbackValue) {
  const trimmed = String(value || "").trim();
  return (trimmed || fallbackValue).replace(/\/+$/, "") + "/";
}

function normalizeApiUrl(value, fallbackValue) {
  const trimmed = String(value || "").trim();
  return (trimmed || fallbackValue).replace(/\/+$/, "");
}

async function getExtensionConfig() {
  const stored = await chrome.storage.local.get(EXTENSION_CONFIG_KEY);
  const config = stored?.[EXTENSION_CONFIG_KEY] || {};
  return {
    summarizerUrl: normalizeBaseUrl(config.summarizerUrl, DEFAULT_SUMMARIZER_URL),
    bridgeApiUrl: normalizeApiUrl(config.bridgeApiUrl, DEFAULT_BRIDGE_API_URL),
    bridgeApiToken: String(config.bridgeApiToken || DEFAULT_BRIDGE_API_TOKEN).trim()
  };
}

async function buildBridgeUrl(payloadId, sourceUrl) {
  const { summarizerUrl } = await getExtensionConfig();
  const url = new URL(summarizerUrl);
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

function sleep(ms) {
  return new Promise((resolve) => globalThis.setTimeout(resolve, ms));
}

function normalizeWhitespace(text) {
  return String(text || "")
    .replace(/\u200b/g, "")
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function decodeHtmlEntities(text) {
  return String(text || "")
    .replace(/&#(\d+);/g, (_match, code) => String.fromCharCode(Number(code)))
    .replace(/&#x([0-9a-f]+);/gi, (_match, code) => String.fromCharCode(parseInt(code, 16)))
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, "\"")
    .replace(/&#39;/g, "'")
    .replace(/&nbsp;/g, " ");
}

function dedupeTranscriptLines(lines) {
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
}

function extractBalancedBlock(source, startIndex, openChar, closeChar) {
  let depth = 0;
  let inString = false;
  let escaped = false;
  for (let i = startIndex; i < source.length; i += 1) {
    const ch = source[i];
    if (inString) {
      if (escaped) {
        escaped = false;
      } else if (ch === "\\") {
        escaped = true;
      } else if (ch === "\"") {
        inString = false;
      }
      continue;
    }
    if (ch === "\"") {
      inString = true;
      continue;
    }
    if (ch === openChar) {
      depth += 1;
    } else if (ch === closeChar) {
      depth -= 1;
      if (depth === 0) {
        return source.slice(startIndex, i + 1);
      }
    }
  }
  return "";
}

function parseJsonObjectAfterMarker(source, marker) {
  const markerIndex = source.indexOf(marker);
  if (markerIndex === -1) {
    return null;
  }
  const braceIndex = source.indexOf("{", markerIndex);
  if (braceIndex === -1) {
    return null;
  }
  const rawJson = extractBalancedBlock(source, braceIndex, "{", "}");
  if (!rawJson) {
    return null;
  }
  try {
    return JSON.parse(rawJson);
  } catch (_error) {
    return null;
  }
}

function extractCaptionTracksFromSource(source) {
  if (!source || !source.includes("captionTracks")) {
    return [];
  }

  const markers = [
    "ytInitialPlayerResponse =",
    "var ytInitialPlayerResponse =",
    "window[\"ytInitialPlayerResponse\"] =",
    "ytInitialPlayerResponse=",
    "\"ytInitialPlayerResponse\":"
  ];

  for (const marker of markers) {
    const playerResponse = parseJsonObjectAfterMarker(source, marker);
    const tracks = playerResponse?.captions?.playerCaptionsTracklistRenderer?.captionTracks;
    if (Array.isArray(tracks) && tracks.length) {
      return tracks;
    }
  }

  const key = "\"captionTracks\":";
  let searchIndex = 0;
  while (searchIndex < source.length) {
    const markerIndex = source.indexOf(key, searchIndex);
    if (markerIndex === -1) {
      break;
    }
    const arrayStart = source.indexOf("[", markerIndex);
    if (arrayStart === -1) {
      break;
    }
    const rawArray = extractBalancedBlock(source, arrayStart, "[", "]");
    if (!rawArray) {
      searchIndex = markerIndex + key.length;
      continue;
    }
    try {
      const tracks = JSON.parse(rawArray);
      if (Array.isArray(tracks) && tracks.length) {
        return tracks;
      }
    } catch (_error) {
      // Continue searching later occurrences.
    }
    searchIndex = arrayStart + rawArray.length;
  }

  return [];
}

function parseYouTubeJsonTranscript(payload) {
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
}

function parseYouTubeXmlTranscript(xmlText) {
  const lines = [];
  const matches = String(xmlText || "").matchAll(/<text\b[^>]*>([\s\S]*?)<\/text>/g);
  for (const match of matches) {
    const cleaned = normalizeWhitespace(decodeHtmlEntities(match[1] || ""));
    if (cleaned) {
      lines.push(cleaned);
    }
  }
  return normalizeWhitespace(dedupeTranscriptLines(lines).join("\n"));
}

async function fetchYouTubeWatchHtml(url) {
  const response = await fetchWithTimeout(
    url,
    {
      method: "GET",
      credentials: "include",
      cache: "no-store",
      headers: {
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"
      }
    },
    20000
  );
  if (!response.ok) {
    throw new Error(`watch_page_http_${response.status}`);
  }
  return response.text();
}

async function fetchYouTubeCaptionTrack(track) {
  const baseUrl = String(track?.baseUrl || "").trim();
  if (!baseUrl) {
    return "";
  }

  const candidates = [];
  try {
    const jsonUrl = new URL(baseUrl);
    jsonUrl.searchParams.set("fmt", "json3");
    candidates.push(jsonUrl.toString());
  } catch (_error) {
    // Ignore malformed URL and try original value.
  }
  candidates.push(baseUrl);

  for (const candidate of candidates) {
    try {
      const response = await fetchWithTimeout(
        candidate,
        {
          method: "GET",
          credentials: "include",
          cache: "no-store"
        },
        20000
      );
      if (!response.ok) {
        continue;
      }
      const rawText = await response.text();
      const trimmed = rawText.trim();
      if (!trimmed) {
        continue;
      }
      if (trimmed.startsWith("{")) {
        const transcript = parseYouTubeJsonTranscript(JSON.parse(trimmed));
        if (transcript) {
          return transcript;
        }
      }
      const transcript = parseYouTubeXmlTranscript(trimmed);
      if (transcript) {
        return transcript;
      }
    } catch (_error) {
      // Try next candidate.
    }
  }

  return "";
}

async function extractYouTubeTranscriptByUrl(sourceUrl) {
  const html = await fetchYouTubeWatchHtml(sourceUrl);
  const tracks = extractCaptionTracksFromSource(html);
  if (!tracks.length) {
    return {
      ok: false,
      error: "background_no_caption_tracks",
      debug: {
        htmlContainsCaptionTracks: html.includes("captionTracks"),
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
    const transcript = await fetchYouTubeCaptionTrack(track);
    if (transcript) {
      return {
        ok: true,
        transcript,
        debug: {
          htmlContainsCaptionTracks: true,
          trackCount: tracks.length,
          languageCode: String(track?.languageCode || ""),
          kind: String(track?.kind || "")
        }
      };
    }
  }

  return {
    ok: false,
    error: "background_caption_fetch_failed",
    debug: {
      htmlContainsCaptionTracks: true,
      trackCount: tracks.length
    }
  };
}

async function fetchWithTimeout(url, options = {}, timeoutMs = 10000) {
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
}

async function wakeBridgeApi() {
  const { bridgeApiUrl } = await getExtensionConfig();
  try {
    const response = await fetchWithTimeout(
      `${bridgeApiUrl}/health`,
      {
        method: "GET",
        cache: "no-store"
      },
      BRIDGE_HEALTH_TIMEOUT_MS
    );
    return response.ok;
  } catch (_error) {
    return false;
  }
}

async function uploadBridgePayloadOnce(payload) {
  const { bridgeApiUrl, bridgeApiToken } = await getExtensionConfig();
  const headers = {
    "Content-Type": "application/json"
  };
  if (bridgeApiToken) {
    headers["X-Bridge-Token"] = bridgeApiToken;
  }

  let response;

  try {
    response = await fetchWithTimeout(
      `${bridgeApiUrl}/api/bridge/payload`,
      {
        method: "POST",
        headers,
        body: JSON.stringify(payload),
        cache: "no-store"
      },
      BRIDGE_UPLOAD_TIMEOUT_MS
    );
  } catch (error) {
    const name = String(error?.name || "");
    if (name === "AbortError") {
      throw new Error("bridge_api_timeout");
    }
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

async function uploadBridgePayload(payload) {
  const errors = [];

  await setFlowStatus("正在唤醒 bridge 服务...", false, "warming");
  await wakeBridgeApi();

  for (let attempt = 0; attempt < 2; attempt += 1) {
    try {
      if (attempt > 0) {
        await setFlowStatus("bridge 首次上传超时，正在自动重试...", false, "retrying");
      } else {
        await setFlowStatus("主站已打开，正在上传 transcript...", false, "uploading");
      }
      return await uploadBridgePayloadOnce(payload);
    } catch (error) {
      const message = String(error?.message || "");
      errors.push(message);
      const retryable = message === "bridge_api_timeout" || message.startsWith("bridge_api_request_failed:");
      if (!retryable || attempt >= 1) {
        throw new Error(errors.join(" | "));
      }
      await sleep(BRIDGE_UPLOAD_RETRY_DELAY_MS);
      await wakeBridgeApi();
    }
  }

  throw new Error(errors.join(" | ") || "bridge_api_upload_failed");
}

async function startSummarizeFlow(payload) {
  const sourceUrl = String(payload?.sourceUrl || "");
  await setFlowStatus("正在打开主站...", false, "opening");
  const targetTab = await chrome.tabs.create({ url: await buildBridgeUrl("", sourceUrl) });

  try {
    const result = await uploadBridgePayload(payload);
    const finalPayloadId = String(result?.payload_id || payload?.payloadId || "");
    if (targetTab.id && finalPayloadId) {
      await chrome.tabs.update(targetTab.id, { url: await buildBridgeUrl(finalPayloadId, sourceUrl) });
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
  if (!message?.action) {
    return undefined;
  }

  if (message.action === "startSummarizeFlow") {
    (async () => {
      try {
        await startSummarizeFlow(message.payload || {});
        sendResponse({ ok: true });
      } catch (error) {
        sendResponse({ ok: false, error: String(error?.message || error || "start_flow_failed") });
      }
    })();
    return true;
  }

  if (message.action === "extractYouTubeTranscriptByUrl") {
    (async () => {
      try {
        const sourceUrl = String(message.url || "");
        const result = await extractYouTubeTranscriptByUrl(sourceUrl);
        sendResponse(result);
      } catch (error) {
        sendResponse({
          ok: false,
          error: String(error?.message || error || "background_extract_failed")
        });
      }
    })();
    return true;
  }

  return undefined;
});
