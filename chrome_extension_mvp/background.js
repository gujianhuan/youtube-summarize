const DEFAULT_SUMMARIZER_URL = "https://youtube-summarize-0oms.onrender.com/";
const DEFAULT_BRIDGE_API_URL = "https://youtube-summarize-bridge.onrender.com";
const DEFAULT_BRIDGE_API_TOKEN = "";
const EXTENSION_CONFIG_KEY = "summarizerExtensionConfig";
const FLOW_STATUS_KEY = "summarizerFlowStatus";
const BRIDGE_HEALTH_TIMEOUT_MS = 15000;
const BRIDGE_UPLOAD_TIMEOUT_MS = 20000;
const BRIDGE_UPLOAD_RETRY_DELAY_MS = 1200;
const TEMP_TAB_LOAD_TIMEOUT_MS = 20000;
const TEMP_TAB_READY_DELAY_MS = 1500;
const EXTENSION_TOOL_VERSION = "0.1.43";

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
  const source = String(xmlText || "");
  const patterns = [
    /<text\b[^>]*>([\s\S]*?)<\/text>/g,
    /<p\b[^>]*>([\s\S]*?)<\/p>/g,
    /<s\b[^>]*>([\s\S]*?)<\/s>/g
  ];

  for (const pattern of patterns) {
    for (const match of source.matchAll(pattern)) {
      const raw = String(match[1] || "").replace(/<[^>]+>/g, " ");
      const cleaned = normalizeWhitespace(decodeHtmlEntities(raw));
      if (cleaned) {
        lines.push(cleaned);
      }
    }
  }

  return normalizeWhitespace(dedupeTranscriptLines(lines).join("\n"));
}

function parseYouTubeVttTranscript(vttText) {
  const lines = [];
  const blocks = String(vttText || "")
    .replace(/\r/g, "")
    .split(/\n\s*\n/);

  for (const block of blocks) {
    const rawLines = block
      .split("\n")
      .map((line) => normalizeWhitespace(line))
      .filter(Boolean);

    if (!rawLines.length) {
      continue;
    }

    const contentLines = rawLines.filter((line) => {
      if (line === "WEBVTT") {
        return false;
      }
      if (/^\d+$/.test(line)) {
        return false;
      }
      if (/^\d{2}:\d{2}(?::\d{2})?\.\d{3}\s+-->\s+\d{2}:\d{2}(?::\d{2})?\.\d{3}/.test(line)) {
        return false;
      }
      return true;
    });

    const cleaned = normalizeWhitespace(decodeHtmlEntities(contentLines.join(" ")));
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
      for (const parser of [parseYouTubeXmlTranscript, parseYouTubeVttTranscript]) {
        const transcript = parser(trimmed);
        if (transcript) {
          return transcript;
        }
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

function buildPayloadId() {
  if (globalThis.crypto && typeof globalThis.crypto.randomUUID === "function") {
    return globalThis.crypto.randomUUID();
  }
  return `bridge_${Date.now()}_${Math.random().toString(16).slice(2)}`;
}

function buildRequestId() {
  if (globalThis.crypto && typeof globalThis.crypto.randomUUID === "function") {
    return globalThis.crypto.randomUUID();
  }
  return `req_${Date.now()}_${Math.random().toString(16).slice(2)}`;
}

function parseYouTubeVideoId(url) {
  try {
    const parsed = new URL(String(url || ""));
    if (parsed.hostname.includes("youtu.be")) {
      return parsed.pathname.replace(/^\/+/, "").trim();
    }
    const watchId = parsed.searchParams.get("v") || "";
    if (watchId) {
      return watchId;
    }
    const pathParts = parsed.pathname.split("/").filter(Boolean);
    if (pathParts.length >= 2 && ["shorts", "live", "embed"].includes(pathParts[0])) {
      return pathParts[1];
    }
    return "";
  } catch (_error) {
    return "";
  }
}

async function waitForTabComplete(tabId, timeoutMs = 5000) {
  if (!tabId) {
    throw new Error("tab_id_required");
  }

  return new Promise((resolve, reject) => {
    let settled = false;
    let timeoutId = null;

    const finish = (ok, reason) => {
      if (settled) return;
      settled = true;
      chrome.tabs.onUpdated.removeListener(handleUpdated);
      if (timeoutId !== null) globalThis.clearTimeout(timeoutId);
      if (ok) resolve();
      else reject(new Error(reason));
    };

    const handleUpdated = (updatedTabId, changeInfo) => {
      if (updatedTabId === tabId && (changeInfo.status === "complete" || changeInfo.status === "interactive")) {
        finish(true);
      }
    };

    chrome.tabs.onUpdated.addListener(handleUpdated);
    timeoutId = globalThis.setTimeout(() => finish(false, "temp_tab_load_timeout"), timeoutMs);

    chrome.tabs.get(tabId, (tab) => {
      if (chrome.runtime.lastError) {
        finish(false, "tab_not_found");
        return;
      }
      if (tab && (tab.status === "complete" || tab.status === "interactive")) {
        finish(true);
      }
    });
  });
}

async function ensureContentScriptOnTab(tabId) {
  if (!tabId) {
    return;
  }
  await chrome.scripting.executeScript({
    target: { tabId },
    files: ["content.js"]
  });
}

async function extractTranscriptViaContentScriptTab(tabId) {
  if (!tabId) {
    return null;
  }

  try {
    return await chrome.tabs.sendMessage(tabId, { action: "extractTranscript" });
  } catch (error) {
    const message = String(error?.message || "");
    if (!message.includes("Receiving end does not exist")) {
      return null;
    }
  }

  try {
    await ensureContentScriptOnTab(tabId);
    return await chrome.tabs.sendMessage(tabId, { action: "extractTranscript" });
  } catch (_error) {
    return null;
  }
}

async function findMatchingYouTubeTab(sourceUrl) {
  const trimmedSourceUrl = String(sourceUrl || "").trim();
  if (!trimmedSourceUrl || (!trimmedSourceUrl.includes("youtube.com") && !trimmedSourceUrl.includes("youtu.be"))) {
    return null;
  }

  const targetVideoId = parseYouTubeVideoId(trimmedSourceUrl);
  const tabs = await chrome.tabs.query({});
  const candidates = tabs.filter((tab) => {
    const tabUrl = String(tab?.url || "");
    if (!tabUrl || (!tabUrl.includes("youtube.com") && !tabUrl.includes("youtu.be"))) {
      return false;
    }
    if (targetVideoId) {
      return parseYouTubeVideoId(tabUrl) === targetVideoId;
    }
    return tabUrl === trimmedSourceUrl;
  });

  if (!candidates.length) {
    return null;
  }

  candidates.sort((a, b) => {
    const aScore = (a.active ? 2 : 0) + (a.status === "complete" ? 1 : 0);
    const bScore = (b.active ? 2 : 0) + (b.status === "complete" ? 1 : 0);
    return bScore - aScore;
  });

  return candidates[0] || null;
}

async function extractYouTubeTranscriptViaTemporaryTab(sourceUrl) {
  const sourceUrlText = String(sourceUrl || "").trim();
  if (!sourceUrlText) {
    return null;
  }

  let tempTab = null;
  try {
    tempTab = await chrome.tabs.create({
      url: sourceUrlText,
      active: false
    });
    if (!tempTab?.id) {
      return null;
    }
    await waitForTabComplete(tempTab.id);
    await sleep(TEMP_TAB_READY_DELAY_MS);
    return await extractTranscriptViaContentScriptTab(tempTab.id);
  } catch (_error) {
    return null;
  } finally {
    if (tempTab?.id) {
      try {
        await chrome.tabs.remove(tempTab.id);
      } catch (_error) {
        // Ignore cleanup failure for temp tab.
      }
    }
  }
}

async function extractYouTubeTranscriptViaTemporaryTabMainWorld(sourceUrl) {
  const sourceUrlText = String(sourceUrl || "").trim();
  if (!sourceUrlText) {
    return null;
  }

  let tempTab = null;
  try {
    tempTab = await chrome.tabs.create({
      url: sourceUrlText,
      active: false
    });
    if (!tempTab?.id) {
      return null;
    }
    await waitForTabComplete(tempTab.id);
    await sleep(TEMP_TAB_READY_DELAY_MS);
    return await extractYouTubeTranscriptViaMainWorldTab(tempTab.id);
  } catch (_error) {
    return null;
  } finally {
    if (tempTab?.id) {
      try {
        await chrome.tabs.remove(tempTab.id);
      } catch (_error) {
        // Ignore cleanup failure for temp tab.
      }
    }
  }
}

function normalizePluginExtractionResult(result, fallbackReason = "subtitle_panel_available") {
  if (!result || typeof result !== "object") {
    return null;
  }

  const detection = result.detection || {};
  const hasValidTranscript = result.ok && String(result.transcript || "").trim().length > 0;

  return {
    ...result,
    ok: hasValidTranscript,
    platform: String(result.platform || "youtube"),
    title: String(result.title || "").trim(),
    transcript: String(result.transcript || "").trim(),
    detection: {
      ...detection,
      hasText: hasValidTranscript,
      sourceType: String(detection.sourceType || (hasValidTranscript ? "transcript" : "none")),
      confidence: Number(detection.confidence || (hasValidTranscript ? 0.98 : 0)),
      reason: String(detection.reason || fallbackReason),
      canFallbackToLocal: false,
      extractionLogs: Array.isArray(detection.extractionLogs) ? detection.extractionLogs : []
    }
  };
}

async function extractYouTubeTranscriptViaMainWorldTab(tabId) {
  if (!tabId) {
    return null;
  }

  try {
    const [injectionResult] = await chrome.scripting.executeScript({
      target: { tabId },
      world: "MAIN",
      func: async () => {
        const normalizeWhitespace = (text) => String(text || "")
          .replace(/\u200b/g, "")
          .replace(/[ \t]+\n/g, "\n")
          .replace(/\n{3,}/g, "\n\n")
          .trim();

        const decodeHtmlEntities = (text) => String(text || "")
          .replace(/&#(\d+);/g, (_match, code) => String.fromCharCode(Number(code)))
          .replace(/&#x([0-9a-f]+);/gi, (_match, code) => String.fromCharCode(parseInt(code, 16)))
          .replace(/&amp;/g, "&")
          .replace(/&lt;/g, "<")
          .replace(/&gt;/g, ">")
          .replace(/&quot;/g, "\"")
          .replace(/&#39;/g, "'")
          .replace(/&nbsp;/g, " ");

        const dedupeTranscriptLines = (lines) => {
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
        };

        const parseYouTubeJsonTranscript = (payload) => {
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
        };

        const parseYouTubeXmlTranscript = (xmlText) => {
          const parser = new DOMParser();
          const xml = parser.parseFromString(String(xmlText || ""), "text/xml");
          const nodes = [
            ...Array.from(xml.getElementsByTagName("text")),
            ...Array.from(xml.getElementsByTagName("p")),
            ...Array.from(xml.getElementsByTagName("s"))
          ];
          const lines = nodes
            .map((node) => decodeHtmlEntities((node.textContent || "").replace(/\s+/g, " ")))
            .map((line) => normalizeWhitespace(line))
            .filter(Boolean);
          return normalizeWhitespace(dedupeTranscriptLines(lines).join("\n"));
        };

        const parseYouTubeVttTranscript = (vttText) => {
          const lines = [];
          const blocks = String(vttText || "")
            .replace(/\r/g, "")
            .split(/\n\s*\n/);

          for (const block of blocks) {
            const rawLines = block
              .split("\n")
              .map((line) => normalizeWhitespace(line))
              .filter(Boolean);

            if (!rawLines.length) {
              continue;
            }

            const contentLines = rawLines.filter((line) => {
              if (line === "WEBVTT") {
                return false;
              }
              if (/^\d+$/.test(line)) {
                return false;
              }
              if (/^\d{2}:\d{2}(?::\d{2})?\.\d{3}\s+-->\s+\d{2}:\d{2}(?::\d{2})?\.\d{3}/.test(line)) {
                return false;
              }
              return true;
            });

            const cleaned = normalizeWhitespace(decodeHtmlEntities(contentLines.join(" ")));
            if (cleaned) {
              lines.push(cleaned);
            }
          }

          return normalizeWhitespace(dedupeTranscriptLines(lines).join("\n"));
        };

        const parseMaybeJson = (value) => {
          if (!value) {
            return null;
          }
          if (typeof value === "string") {
            try {
              return JSON.parse(value);
            } catch (_error) {
              return null;
            }
          }
          return value;
        };

        const normalizeCaptionTracks = (value) => {
          if (Array.isArray(value)) {
            return value.filter((track) => track && typeof track === "object");
          }
          if (Array.isArray(value?.captionTracks)) {
            return value.captionTracks.filter((track) => track && typeof track === "object");
          }
          if (value && typeof value === "object" && value.baseUrl) {
            return [value];
          }
          return [];
        };

        const getCaptionTracks = () => {
          const candidates = [];
          const parseMaybeJson = (val) => {
            if (!val) return null;
            if (typeof val === "object") return val;
            try { return JSON.parse(val); } catch (e) { return null; }
          };

          candidates.push(globalThis.ytInitialPlayerResponse);
          candidates.push(parseMaybeJson(globalThis?.ytplayer?.config?.args?.player_response));
          candidates.push(parseMaybeJson(globalThis?.ytcfg?.data_?.PLAYER_VARS?.player_response));
          
          if (typeof globalThis?.ytcfg?.get === "function") {
            candidates.push(parseMaybeJson(globalThis.ytcfg.get("PLAYER_VARS")?.player_response));
            candidates.push(parseMaybeJson(globalThis.ytcfg.get("PLAYER_RESPONSE")));
            candidates.push(parseMaybeJson(globalThis.ytcfg.get("ytInitialPlayerResponse")));
          }

          const moviePlayer = document.getElementById("movie_player");
          if (moviePlayer && typeof moviePlayer.getPlayerResponse === "function") {
            candidates.push(moviePlayer.getPlayerResponse());
          }

          for (const resp of candidates) {
            const tracks = resp?.captions?.playerCaptionsTracklistRenderer?.captionTracks;
            if (Array.isArray(tracks) && tracks.length) return tracks;
          }

          // Fallback to searching all script tags if globals fail
          const scripts = Array.from(document.getElementsByTagName("script"));
          for (const s of scripts) {
      const text = s.textContent || "";
      if (text.includes("captionTracks") || text.includes("ytInitialPlayerResponse") || text.includes("ytInitialData")) {
        const patterns = [
          /ytInitialPlayerResponse\s*=\s*({.+?});/,
          /ytInitialData\s*=\s*({.+?});/,
          /window\["ytInitialPlayerResponse"\]\s*=\s*({.+?});/,
          /window\["ytInitialData"\]\s*=\s*({.+?});/
        ];

        for (const pattern of patterns) {
          const match = text.match(pattern);
          if (match) {
            try {
              const resp = JSON.parse(match[1]);
              const tracks = resp?.captions?.playerCaptionsTracklistRenderer?.captionTracks ||
                             resp?.engagementPanels?.find(p => p.engagementPanelSectionListRenderer?.targetId === "engagement-panel-transcript")
                               ?.engagementPanelSectionListRenderer?.content?.transcriptRenderer?.body?.transcriptBodyRenderer?.cueGroups
                               ?.map(g => g.transcriptCueGroupRenderer?.cues?.[0]?.transcriptCueRenderer)
                               ?.filter(Boolean);

              if (Array.isArray(tracks) && tracks.length) return tracks;
            } catch (e) {}
          }
        }
      }
    }

          return [];
        };

        const tracks = getCaptionTracks();
        if (!tracks.length) {
          return {
            ok: false,
            error: "main_world_no_caption_tracks",
            debug: {
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
          const baseUrl = String(track?.baseUrl || "").trim();
          if (!baseUrl) {
            continue;
          }
          const candidates = [];
          try {
            const jsonUrl = new URL(baseUrl);
            jsonUrl.searchParams.set("fmt", "json3");
            candidates.push(jsonUrl.toString());
          } catch (_error) {
            // Ignore malformed track URL and fallback to original.
          }
          candidates.push(baseUrl);

          for (const candidate of candidates) {
            try {
              const resp = await fetch(candidate, {
                method: "GET",
                credentials: "include",
                cache: "no-store"
              });
              if (!resp.ok) {
                continue;
              }
              const rawText = await resp.text();
              const trimmed = rawText.trim();
              if (!trimmed) {
                continue;
              }
              let transcript = "";
              if (trimmed.startsWith("{")) {
                transcript = parseYouTubeJsonTranscript(JSON.parse(trimmed));
              } else {
                transcript = parseYouTubeXmlTranscript(trimmed) || parseYouTubeVttTranscript(trimmed);
              }
              if (transcript) {
                return {
                  ok: true,
                  transcript,
                  debug: {
                    trackCount: tracks.length,
                    languageCode: String(track?.languageCode || ""),
                    kind: String(track?.kind || ""),
                    fetchUrlType: candidate.includes("fmt=json3") ? "json3" : "base"
                  }
                };
              }
            } catch (_error) {
              // Try next candidate/track.
            }
          }
        }

        return {
          ok: false,
          error: "main_world_caption_fetch_failed",
          debug: {
            trackCount: tracks.length
          }
        };
      }
    });
    return injectionResult?.result || null;
  } catch (_error) {
    return null;
  }
}

async function extractYouTubeTranscriptForPageFlow(sourceUrl) {
  const sourceUrlText = String(sourceUrl || "").trim();
  const allExtractionLogs = [];
  const addLogs = (res, stageName) => {
    const logs = res?.detection?.extractionLogs;
    if (Array.isArray(logs)) {
      allExtractionLogs.push(...logs);
    }
    if (res?.debug && typeof res.debug === "object") {
      try {
        allExtractionLogs.push(`[Background] ${stageName} debug: ${JSON.stringify(res.debug)}`);
      } catch (_error) {
        // Ignore debug serialization issues.
      }
    }
    if (res?.error) {
      allExtractionLogs.push(`[Background] ${stageName} failed: ${res.error}`);
    }
  };

  const matchedTab = await findMatchingYouTubeTab(sourceUrlText);
  const attempts = [];
  let contentResult = null;
  let tempTabResult = null;

  if (matchedTab?.id) {
    attempts.push({
      stage: "matched_tab_found",
      ok: true,
      tabId: matchedTab.id,
      tabUrl: String(matchedTab.url || "")
    });

    try {
      // 对已匹配的标签页，我们尝试等待其就绪，但即便超时也继续尝试提取
      await waitForTabComplete(matchedTab.id, 5000);
      attempts.push({
        stage: "matched_tab_wait_complete",
        ok: true
      });
    } catch (error) {
      attempts.push({
        stage: "matched_tab_wait_complete",
        ok: false,
        error: String(error?.message || "matched_tab_load_timeout_ignored")
      });
    }

    const rawContentResult = await extractTranscriptViaContentScriptTab(matchedTab.id);
    addLogs(rawContentResult, "matched_tab_content_script");
    contentResult = normalizePluginExtractionResult(
      rawContentResult,
      "content_script_extract"
    );
    attempts.push({
      stage: "matched_tab_content_script",
      ok: Boolean(contentResult?.ok),
      error: contentResult?.ok ? "" : String(rawContentResult?.error || "content_script_extract_failed"),
      reason: String(rawContentResult?.detection?.reason || "")
    });
    if (contentResult?.ok) {
      return {
        ...contentResult,
        detection: {
          ...contentResult.detection,
          extractionLogs: allExtractionLogs
        }
      };
    }

    const mainWorldResult = await extractYouTubeTranscriptViaMainWorldTab(matchedTab.id);
    addLogs(mainWorldResult, "matched_tab_main_world");
    attempts.push({
      stage: "matched_tab_main_world",
      ok: Boolean(mainWorldResult?.ok && String(mainWorldResult.transcript || "").trim()),
      error: String(mainWorldResult?.error || "main_world_extract_failed")
    });
    if (mainWorldResult?.ok && String(mainWorldResult.transcript || "").trim()) {
      return {
        ...mainWorldResult,
        platform: "youtube",
        title: String(matchedTab.title || "").trim(),
        detection: {
          hasText: true,
          sourceType: "transcript",
          confidence: 0.99,
          reason: "main_world_caption_fetch",
          canFallbackToLocal: false,
          extractionLogs: allExtractionLogs
        }
      };
    }
  } else {
    attempts.push({
      stage: "matched_tab_found",
      ok: false,
      error: "no_matching_tab"
    });
  }

  const tempTabRawResult = await extractYouTubeTranscriptViaTemporaryTab(sourceUrlText);
  addLogs(tempTabRawResult, "temp_tab_content_script");
  const normalizedTempTabResult = normalizePluginExtractionResult(
    tempTabRawResult,
    "temp_tab_content_script_extract"
  );
  attempts.push({
    stage: "temp_tab_content_script",
    ok: Boolean(normalizedTempTabResult?.ok),
    error: normalizedTempTabResult?.ok ? "" : String(tempTabRawResult?.error || "temp_tab_content_script_extract_failed"),
    reason: String(tempTabRawResult?.detection?.reason || "")
  });
  if (normalizedTempTabResult?.ok) {
    return {
      ...normalizedTempTabResult,
      detection: {
        ...normalizedTempTabResult.detection,
        extractionLogs: allExtractionLogs
      }
    };
  }

  const tempTabMainWorldResult = await extractYouTubeTranscriptViaTemporaryTabMainWorld(sourceUrlText);
  addLogs(tempTabMainWorldResult, "temp_tab_main_world");
  attempts.push({
    stage: "temp_tab_main_world",
    ok: Boolean(tempTabMainWorldResult?.ok && String(tempTabMainWorldResult.transcript || "").trim()),
    error: String(tempTabMainWorldResult?.error || "temp_tab_main_world_extract_failed")
  });
  if (tempTabMainWorldResult?.ok && String(tempTabMainWorldResult.transcript || "").trim()) {
    return {
      ...tempTabMainWorldResult,
      platform: "youtube",
      detection: {
        hasText: true,
        sourceType: "transcript",
        confidence: 0.99,
        reason: "temp_tab_main_world_caption_fetch",
        canFallbackToLocal: false,
        extractionLogs: allExtractionLogs
      }
    };
  }

  const backgroundResult = await extractYouTubeTranscriptByUrl(sourceUrlText);
  addLogs(backgroundResult, "background_extract");
  attempts.push({
    stage: "background_extract",
    ok: Boolean(backgroundResult?.ok && String(backgroundResult.transcript || "").trim()),
    error: String(backgroundResult?.error || "background_extract_failed")
  });
  if (backgroundResult?.ok && String(backgroundResult.transcript || "").trim()) {
    return {
      ...backgroundResult,
      platform: "youtube",
      detection: {
        hasText: true,
        sourceType: "transcript",
        confidence: 0.99,
        reason: "background_caption_fetch",
        canFallbackToLocal: false,
        extractionLogs: allExtractionLogs
      }
    };
  }

  const finalResult = normalizedTempTabResult || contentResult || tempTabRawResult || backgroundResult || {};
  return {
    ...finalResult,
    ok: false,
    error: String(finalResult?.error || "extension_extract_failed"),
    helperMessage: "插件已依次尝试匹配标签页、页面提取、临时页提取与后台直连，但仍未拿到文本。",
    detection: {
      hasText: false,
      extractionLogs: allExtractionLogs
    },
    debug: {
      sourceUrl: sourceUrlText,
      matchedTabUrl: String(matchedTab?.url || ""),
      attempts,
      detection: {
        extractionLogs: allExtractionLogs
      }
    }
  };
}

function buildTranscriptEnvelope(payloadId, response, transcript, sourceUrl, title) {
  const videoId = parseYouTubeVideoId(sourceUrl);
  const detection = response?.detection || {};
  return {
    schemaVersion: "1.0",
    requestId: buildRequestId(),
    source: {
      kind: "extension",
      sourceType: detection.sourceType && detection.sourceType !== "none" ? detection.sourceType : "subtitle",
      toolVersion: EXTENSION_TOOL_VERSION
    },
    video: {
      platform: String(response?.platform || "youtube"),
      videoId,
      url: sourceUrl,
      title
    },
    transcript: {
      language: "",
      text: transcript,
      segments: [],
      charCount: transcript.length
    },
    diagnostics: {
      textSourceReason: detection.reason || "unknown",
      fallbackUsed: false,
      extensionState: "text_ready",
      notes: payloadId ? [`payload:${payloadId}`] : []
    },
    createdAt: new Date().toISOString()
  };
}

async function startSummarizeFlowFromPage(payload) {
  const sourceUrl = String(payload?.sourceUrl || "").trim();
  const attempts = [
    {
      stage: "background_received_page_flow_request",
      ok: true,
      sourceUrl
    }
  ];
  if (!sourceUrl) {
    return {
      ok: false,
      error: "source_url_required",
      debug: { attempts }
    };
  }
  attempts.push({
    stage: "background_start_extraction",
    ok: true
  });
  const extraction = await extractYouTubeTranscriptForPageFlow(sourceUrl);
  if (!extraction?.ok || !String(extraction.transcript || "").trim()) {
    attempts.push({
      stage: "background_extraction_failed",
      ok: false,
      error: String(extraction?.error || "extension_extract_failed")
    });
    return {
      ...(typeof extraction === "object" && extraction ? extraction : {}),
      ok: false,
      error: String(extraction?.error || "extension_extract_failed"),
      debug: {
        ...((extraction?.debug && typeof extraction.debug === "object") ? extraction.debug : {}),
        attempts: [
          ...attempts,
          ...((((extraction && extraction.debug) || {}).attempts) instanceof Array ? extraction.debug.attempts : [])
        ]
      }
    };
  }
  const transcript = String(extraction.transcript || "").trim();
  attempts.push({
    stage: "background_extraction_succeeded",
    ok: true,
    reason: String(extraction?.detection?.reason || "")
  });
  const payloadId = buildPayloadId();
  const envelope = buildTranscriptEnvelope(payloadId, extraction, transcript, sourceUrl, extraction.title || "");
  const bridgePayload = {
    payloadId,
    sourceUrl,
    title: extraction.title || "",
    transcript,
    envelope,
    bridgeVersion: 2,
    sourceKind: "extension",
    sourceType: extraction?.detection?.sourceType || "subtitle",
    textSourceReason: extraction?.detection?.reason || "extension_extract_by_url",
    fallbackUsed: false
  };
  attempts.push({
    stage: "background_upload_bridge_payload",
    ok: true,
    payloadId
  });
  try {
    await uploadBridgePayload(bridgePayload);
  } catch (error) {
    attempts.push({
      stage: "background_upload_bridge_payload_failed",
      ok: false,
      error: String(error?.message || error || "bridge_upload_failed")
    });
    return {
      ok: false,
      error: String(error?.message || error || "bridge_upload_failed"),
      helperMessage: "插件已抓到文本，但上传 bridge payload 失败。",
      debug: {
        attempts: [
          ...attempts,
          ...((((extraction && extraction.debug) || {}).attempts) instanceof Array ? extraction.debug.attempts : [])
        ]
      }
    };
  }
  attempts.push({
    stage: "background_upload_bridge_payload_succeeded",
    ok: true,
    payloadId
  });
  return {
    ok: true,
    payloadId,
    debug: {
      attempts: [
        ...attempts,
        ...((((extraction && extraction.debug) || {}).attempts) instanceof Array ? extraction.debug.attempts : [])
      ]
    }
  };
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

  if (message.action === "startSummarizeFlowFromPage") {
    (async () => {
      try {
        const result = await startSummarizeFlowFromPage(message.payload || {});
        sendResponse(result);
      } catch (error) {
        sendResponse({ ok: false, error: String(error?.message || error || "page_flow_failed") });
      }
    })();
    return true;
  }

  return undefined;
});
