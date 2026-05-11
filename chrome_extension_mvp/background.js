const DEFAULT_SUMMARIZER_URL = "https://youtube-summarize-0oms.onrender.com/";
const DEFAULT_BRIDGE_API_URL = "https://youtube-summarize-bridge.onrender.com";
const DEFAULT_BRIDGE_API_TOKEN = "";
const EXTENSION_CONFIG_KEY = "summarizerExtensionConfig";
const FLOW_STATUS_KEY = "summarizerFlowStatus";
const BRIDGE_HEALTH_TIMEOUT_MS = 15000;
const BRIDGE_UPLOAD_TIMEOUT_MS = 20000;
const BRIDGE_UPLOAD_RETRY_DELAY_MS = 1200;
const TEMP_TAB_LOAD_TIMEOUT_MS = 30000;
const TEMP_TAB_READY_DELAY_MS = 5000;
const YOUTUBE_EXTRACTION_RETRY_ATTEMPTS = 5;
const YOUTUBE_EXTRACTION_RETRY_DELAY_MS = 1500;
const EXTENSION_TOOL_VERSION = "0.1.53";

// Release v0.1.53: Surface extension toolVersion in page-flow debug so stale Chrome extensions are easier to detect.

const CLIENT_NAME_TO_ID = {
  WEB: "1",
  MWEB: "2",
  ANDROID: "3",
  IOS: "5",
  TVHTML5: "7"
};

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

function describeCaptionTrack(track) {
  if (!track || typeof track !== "object") {
    return "unknown_track";
  }
  const parts = [
    `lang=${String(track.languageCode || "") || "unknown"}`,
    `kind=${String(track.kind || "") || "none"}`,
    `name=${extractTextFromRuns(track.name || "") || ""}`
  ].filter(Boolean);
  return parts.join(", ");
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

function parseMaybeJson(value) {
  if (!value) {
    return null;
  }
  if (typeof value === "object") {
    return value;
  }
  try {
    return JSON.parse(value);
  } catch (_error) {
    return null;
  }
}

function findValuesByKey(root, targetKey, results = [], seen = new Set()) {
  if (!root || typeof root !== "object" || seen.has(root) || results.length >= 20) {
    return results;
  }
  seen.add(root);
  if (Array.isArray(root)) {
    for (const item of root) {
      findValuesByKey(item, targetKey, results, seen);
      if (results.length >= 20) {
        break;
      }
    }
    return results;
  }
  for (const [key, value] of Object.entries(root)) {
    if (key === targetKey) {
      results.push(value);
      if (results.length >= 20) {
        break;
      }
    }
    findValuesByKey(value, targetKey, results, seen);
    if (results.length >= 20) {
      break;
    }
  }
  return results;
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
  // Use combined regex to maintain original order
  const pattern = /<(text|p|s)\b[^>]*>([\s\S]*?)<\/\1>/g;

  for (const match of source.matchAll(pattern)) {
    const raw = String(match[2] || "").replace(/<[^>]+>/g, " ");
    const cleaned = normalizeWhitespace(decodeHtmlEntities(raw));
    if (cleaned) {
      lines.push(cleaned);
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

function extractTextFromRuns(value) {
  if (!value) {
    return "";
  }
  if (typeof value === "string") {
    return normalizeWhitespace(decodeHtmlEntities(value));
  }
  if (Array.isArray(value)) {
    return normalizeWhitespace(value.map((item) => extractTextFromRuns(item)).filter(Boolean).join(""));
  }
  if (typeof value === "object") {
    if (typeof value.text === "string") {
      return normalizeWhitespace(decodeHtmlEntities(value.text));
    }
    if (typeof value.utf8 === "string") {
      return normalizeWhitespace(decodeHtmlEntities(value.utf8));
    }
    if (typeof value.simpleText === "string") {
      return normalizeWhitespace(decodeHtmlEntities(value.simpleText));
    }
    if (Array.isArray(value.runs)) {
      return normalizeWhitespace(value.runs.map((item) => extractTextFromRuns(item)).filter(Boolean).join(""));
    }
    for (const key of ["cue", "snippet", "content", "headline", "title"]) {
      const nestedText = extractTextFromRuns(value[key]);
      if (nestedText) {
        return nestedText;
      }
    }
  }
  return "";
}

function isLikelyTranscriptTimestamp(text) {
  return /^(?:\d{1,2}:)?\d{1,2}:\d{2}$/.test(String(text || "").trim());
}

function extractTranscriptFromCueGroups(cueGroups) {
  const lines = [];
  for (const group of Array.isArray(cueGroups) ? cueGroups : []) {
    const cues = Array.isArray(group?.transcriptCueGroupRenderer?.cues)
      ? group.transcriptCueGroupRenderer.cues
      : [];
    for (const cue of cues) {
      const renderer = cue?.transcriptCueRenderer || cue || {};
      const line = extractTextFromRuns(
        renderer.cue ||
        renderer.snippet ||
        renderer.content ||
        renderer.cueSimpleText ||
        renderer.text ||
        renderer
      );
      if (!line || isLikelyTranscriptTimestamp(line)) {
        continue;
      }
      lines.push(line);
    }
  }
  return normalizeWhitespace(dedupeTranscriptLines(lines).join("\n"));
}

function collectCueGroups(root, results = [], seen = new Set()) {
  if (!root || typeof root !== "object" || seen.has(root) || results.length >= 5) {
    return results;
  }
  seen.add(root);
  if (Array.isArray(root)) {
    for (const item of root) {
      collectCueGroups(item, results, seen);
      if (results.length >= 5) {
        break;
      }
    }
    return results;
  }
  if (Array.isArray(root.cueGroups) && root.cueGroups.length) {
    results.push(root.cueGroups);
  }
  for (const value of Object.values(root)) {
    collectCueGroups(value, results, seen);
    if (results.length >= 5) {
      break;
    }
  }
  return results;
}

function extractTranscriptFromStructuredData(root) {
  const candidates = collectCueGroups(root);
  for (const cueGroups of candidates) {
    const transcript = extractTranscriptFromCueGroups(cueGroups);
    if (transcript) {
      return transcript;
    }
  }
  return "";
}

function extractTranscriptFromSource(source) {
  if (!source) {
    return "";
  }

  const markers = [
    "ytInitialData =",
    "var ytInitialData =",
    "window[\"ytInitialData\"] =",
    "ytInitialData=",
    "\"ytInitialData\":"
  ];

  for (const marker of markers) {
    const initialData = parseJsonObjectAfterMarker(source, marker);
    const transcript = extractTranscriptFromStructuredData(initialData);
    if (transcript) {
      return transcript;
    }
  }

  const cueGroupsKey = "\"cueGroups\":";
  let searchIndex = 0;
  while (searchIndex < source.length) {
    const markerIndex = source.indexOf(cueGroupsKey, searchIndex);
    if (markerIndex === -1) {
      break;
    }
    const arrayStart = source.indexOf("[", markerIndex);
    if (arrayStart === -1) {
      break;
    }
    const rawArray = extractBalancedBlock(source, arrayStart, "[", "]");
    if (!rawArray) {
      searchIndex = markerIndex + cueGroupsKey.length;
      continue;
    }
    try {
      const cueGroups = JSON.parse(rawArray);
      const transcript = extractTranscriptFromCueGroups(cueGroups);
      if (transcript) {
        return transcript;
      }
    } catch (_error) {
      // Continue searching later occurrences.
    }
    searchIndex = arrayStart + rawArray.length;
  }

  return "";
}

function extractInnertubeConfigFromSource(source) {
  const config = {
    apiKey: "",
    clientVersion: "",
    clientName: "WEB",
    visitorData: "",
    hl: "",
    gl: "",
    loggedIn: false,
    context: null
  };
  const text = String(source || "");
  const assignIfMissing = (key, regex) => {
    if (config[key]) {
      return;
    }
    const match = text.match(regex);
    if (match) {
      config[key] = String(match[1] || "");
    }
  };

  assignIfMissing("apiKey", /"INNERTUBE_API_KEY"\s*:\s*"([^"]+)"/);
  assignIfMissing("clientVersion", /"INNERTUBE_CLIENT_VERSION"\s*:\s*"([^"]+)"/);
  assignIfMissing("clientName", /"INNERTUBE_CONTEXT_CLIENT_NAME"\s*:\s*"([^"]+)"/);
  assignIfMissing("visitorData", /"VISITOR_DATA"\s*:\s*"([^"]+)"/);
  assignIfMissing("hl", /"HL"\s*:\s*"([^"]+)"/);
  assignIfMissing("gl", /"GL"\s*:\s*"([^"]+)"/);

  const loggedInMatch = text.match(/"LOGGED_IN"\s*:\s*(true|false)/);
  if (loggedInMatch) {
    config.loggedIn = loggedInMatch[1] === "true";
  }

  config.context =
    parseJsonObjectAfterMarker(text, "\"INNERTUBE_CONTEXT\":") ||
    parseJsonObjectAfterMarker(text, "INNERTUBE_CONTEXT =") ||
    null;

  if (config.context?.client && typeof config.context.client === "object") {
    const client = config.context.client;
    if (!config.clientVersion && client.clientVersion) {
      config.clientVersion = String(client.clientVersion);
    }
    if (!config.clientName && client.clientName) {
      config.clientName = String(client.clientName);
    }
    if (!config.visitorData && client.visitorData) {
      config.visitorData = String(client.visitorData);
    }
    if (!config.hl && client.hl) {
      config.hl = String(client.hl);
    }
    if (!config.gl && client.gl) {
      config.gl = String(client.gl);
    }
  }

  return config;
}

function getTranscriptParamsCandidatesFromSource(source) {
  const results = [];
  const seen = new Set();
  const pushCandidate = (params, sourceName) => {
    const value = String(params || "").trim();
    if (!value || seen.has(value)) {
      return;
    }
    seen.add(value);
    results.push({ params: value, source: sourceName });
  };

  const markers = [
    "ytInitialData =",
    "var ytInitialData =",
    "window[\"ytInitialData\"] =",
    "ytInitialData=",
    "\"ytInitialData\":"
  ];

  for (const marker of markers) {
    const initialData = parseJsonObjectAfterMarker(source, marker);
    const endpoints = findValuesByKey(initialData, "getTranscriptEndpoint");
    for (const endpoint of endpoints) {
      pushCandidate(endpoint?.params, marker);
    }
  }

  for (const match of String(source || "").matchAll(/"getTranscriptEndpoint"\s*:\s*\{\s*"params"\s*:\s*"([^"]+)"/g)) {
    pushCandidate(match[1], "inline_script");
  }

  return results;
}

function buildInnertubeContextFromConfig(config, overrideClientName = "") {
  const baseContext = (() => {
    try {
      return JSON.parse(JSON.stringify(config?.context || {}));
    } catch (_error) {
      return {};
    }
  })();
  const client = baseContext.client && typeof baseContext.client === "object"
    ? baseContext.client
    : {};
  const finalClientName = String(overrideClientName || client.clientName || config?.clientName || "WEB");
  const finalClientVersion = String(client.clientVersion || config?.clientVersion || "");
  baseContext.client = {
    ...client,
    clientName: finalClientName,
    clientVersion: finalClientVersion
  };
  if (!baseContext.client.hl && config?.hl) {
    baseContext.client.hl = config.hl;
  }
  if (!baseContext.client.gl && config?.gl) {
    baseContext.client.gl = config.gl;
  }
  if (!baseContext.client.visitorData && config?.visitorData) {
    baseContext.client.visitorData = config.visitorData;
  }
  if (!baseContext.client.clientScreen) {
    baseContext.client.clientScreen = "WATCH";
  }
  if (!baseContext.request || typeof baseContext.request !== "object") {
    baseContext.request = {};
  }
  if (typeof baseContext.request.useSsl === "undefined") {
    baseContext.request.useSsl = true;
  }
  return baseContext;
}

function buildYoutubeiHeaders(config, requestContext) {
  const clientName = String(requestContext?.client?.clientName || config?.clientName || "WEB").toUpperCase();
  const headers = {
    "Content-Type": "application/json",
    "X-YouTube-Client-Name": CLIENT_NAME_TO_ID[clientName] || "1",
    "X-YouTube-Client-Version": String(requestContext?.client?.clientVersion || config?.clientVersion || ""),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"
  };
  if (config?.visitorData) {
    headers["X-Goog-Visitor-Id"] = config.visitorData;
  }
  headers["X-Youtube-Bootstrap-Logged-In"] = config?.loggedIn ? "true" : "false";
  return headers;
}

function extractTranscriptFromYoutubeiData(data) {
  const renderers = findValuesByKey(data, "transcriptSegmentListRenderer");
  const lines = [];
  for (const renderer of renderers) {
    const segments = Array.isArray(renderer?.initialSegments)
      ? renderer.initialSegments
      : Array.isArray(renderer?.segments)
        ? renderer.segments
        : [];
    for (const segment of segments) {
      const transcriptRenderer = segment?.transcriptSegmentRenderer || segment || {};
      const text = extractTextFromRuns(
        transcriptRenderer.snippet ||
        transcriptRenderer.cue ||
        transcriptRenderer.content ||
        transcriptRenderer.text ||
        transcriptRenderer
      );
      if (!text || isLikelyTranscriptTimestamp(text)) {
        continue;
      }
      lines.push(text);
    }
  }
  return normalizeWhitespace(dedupeTranscriptLines(lines).join("\n"));
}

async function fetchTranscriptViaYoutubeiFromSource(source, trace = []) {
  const config = extractInnertubeConfigFromSource(source);
  const paramsCandidates = getTranscriptParamsCandidatesFromSource(source);
  if (!config.apiKey) {
    trace.push("background_youtubei_missing_api_key");
  }
  if (!config.clientVersion) {
    trace.push("background_youtubei_missing_client_version");
  }
  if (!paramsCandidates.length) {
    trace.push("background_youtubei_missing_transcript_params");
  }
  if (!config.apiKey || !config.clientVersion || !paramsCandidates.length) {
    return "";
  }

  const contextCandidates = [];
  const seenContexts = new Set();
  const pushContext = (clientName) => {
    const context = buildInnertubeContextFromConfig(config, clientName);
    const signature = `${String(context?.client?.clientName || "")}|${String(context?.client?.clientVersion || "")}`;
    if (!context?.client?.clientVersion || seenContexts.has(signature)) {
      return;
    }
    seenContexts.add(signature);
    contextCandidates.push(context);
  };
  pushContext("");
  pushContext("WEB");
  pushContext("MWEB");

  for (const candidate of paramsCandidates.slice(0, 4)) {
    for (const requestContext of contextCandidates) {
      const clientName = String(requestContext?.client?.clientName || "WEB");
      try {
        const url = new URL("https://www.youtube.com/youtubei/v1/get_transcript");
        url.searchParams.set("prettyPrint", "false");
        url.searchParams.set("key", config.apiKey);
        const response = await fetchWithTimeout(
          url.toString(),
          {
            method: "POST",
            headers: buildYoutubeiHeaders(config, requestContext),
            body: JSON.stringify({
              context: requestContext,
              params: candidate.params
            }),
            credentials: "include",
            cache: "no-store"
          },
          20000
        );
        const rawText = await response.text();
        if (!response.ok) {
          trace.push(`background_youtubei_http_${response.status}:client=${clientName}:source=${candidate.source}:body=${normalizeWhitespace(rawText).slice(0, 160) || "empty"}`);
          continue;
        }
        const data = parseMaybeJson(rawText);
        const transcript = extractTranscriptFromYoutubeiData(data);
        if (transcript) {
          trace.push(`background_youtubei_ok:client=${clientName}:source=${candidate.source}`);
          return transcript;
        }
        trace.push(`background_youtubei_empty_segments:client=${clientName}:source=${candidate.source}`);
      } catch (error) {
        trace.push(`background_youtubei_exception:client=${clientName}:source=${candidate.source}:error=${String(error?.message || error || "unknown")}`);
      }
    }
  }
  return "";
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
      try {
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
      } catch (e) {
        // Continue to next candidate.
      }
    } catch (_error) {
      // Try next candidate.
    }
  }

  return "";
}

async function extractYouTubeTranscriptByUrl(sourceUrl) {
  let lastResult = null;

  for (let attempt = 1; attempt <= YOUTUBE_EXTRACTION_RETRY_ATTEMPTS; attempt += 1) {
    const html = await fetchYouTubeWatchHtml(sourceUrl);
    const tracks = extractCaptionTracksFromSource(html);
    const extractionTrace = [`background_attempt=${attempt}`];

    if (!tracks.length) {
      lastResult = {
        ok: false,
        error: "background_no_caption_tracks",
        debug: {
          htmlContainsCaptionTracks: html.includes("captionTracks"),
          trackCount: 0,
          trace: extractionTrace
        }
      };
      if (attempt < YOUTUBE_EXTRACTION_RETRY_ATTEMPTS) {
        await sleep(YOUTUBE_EXTRACTION_RETRY_DELAY_MS);
        continue;
      }
      return lastResult;
    }

    const sortedTracks = [...tracks].sort((a, b) => {
      const aPenalty = a?.kind === "asr" ? 1 : 0;
      const bPenalty = b?.kind === "asr" ? 1 : 0;
      return aPenalty - bPenalty;
    });

    extractionTrace.push(`tracks=${sortedTracks.map((track) => describeCaptionTrack(track)).join(" | ")}`);

    const youtubeiTranscript = await fetchTranscriptViaYoutubeiFromSource(html, extractionTrace);
    if (youtubeiTranscript) {
      return {
        ok: true,
        transcript: youtubeiTranscript,
        debug: {
          htmlContainsCaptionTracks: true,
          trackCount: tracks.length,
          source: "background_youtubei_get_transcript",
          attempt,
          trace: extractionTrace
        }
      };
    }

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
            kind: String(track?.kind || ""),
            attempt,
            trace: extractionTrace
          }
        };
      }
      extractionTrace.push(`Failed to fetch track: ${describeCaptionTrack(track)}`);
    }

    const directTranscript = extractTranscriptFromSource(html);
    if (directTranscript) {
      return {
        ok: true,
        transcript: directTranscript,
        debug: {
          htmlContainsCaptionTracks: true,
          trackCount: tracks.length,
          source: "watch_html_cuegroups_fallback",
          attempt,
          trace: extractionTrace
        }
      };
    }

    extractionTrace.push("No transcript extracted from watch HTML cueGroups fallback");
    lastResult = {
      ok: false,
      error: "background_caption_fetch_failed",
      debug: {
        htmlContainsCaptionTracks: true,
        trackCount: tracks.length,
        attempt,
        trace: extractionTrace
      }
    };

    if (attempt < YOUTUBE_EXTRACTION_RETRY_ATTEMPTS) {
      await sleep(YOUTUBE_EXTRACTION_RETRY_DELAY_MS);
    }
  }

  return lastResult;
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

async function waitForYouTubeTabReadyForExtraction(tabId, timeoutMs = TEMP_TAB_LOAD_TIMEOUT_MS) {
  if (!tabId) {
    throw new Error("tab_id_required");
  }

  const deadline = Date.now() + timeoutMs;
  let lastStatus = "";
  let lastUrl = "";

  while (Date.now() < deadline) {
    try {
      const tab = await chrome.tabs.get(tabId);
      lastStatus = String(tab?.status || "");
      lastUrl = String(tab?.url || "");
      const isUsableUrl =
        lastUrl &&
        !lastUrl.startsWith("about:blank") &&
        !lastUrl.startsWith("chrome-error://") &&
        (lastUrl.includes("youtube.com") || lastUrl.includes("youtu.be"));
      if (isUsableUrl && (lastStatus === "complete" || lastStatus === "loading")) {
        return {
          ok: true,
          status: lastStatus,
          url: lastUrl
        };
      }
    } catch (error) {
      lastStatus = "get_tab_failed";
      lastUrl = String(error?.message || error || "");
    }
    await sleep(800);
  }

  throw new Error(`temp_tab_load_timeout:status=${lastStatus || "unknown"}:url=${lastUrl || "unknown"}`);
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
    return {
      ok: false,
      error: "content_script_tab_id_required",
      debug: {
        tabId
      }
    };
  }

  try {
    return await chrome.tabs.sendMessage(tabId, { action: "extractTranscript" });
  } catch (error) {
    const message = String(error?.message || "");
    if (!message.includes("Receiving end does not exist")) {
      return {
        ok: false,
        error: "content_script_send_message_failed",
        debug: {
          tabId,
          message
        }
      };
    }
  }

  try {
    await ensureContentScriptOnTab(tabId);
    return await chrome.tabs.sendMessage(tabId, { action: "extractTranscript" });
  } catch (error) {
    return {
      ok: false,
      error: "content_script_reinject_failed",
      debug: {
        tabId,
        message: String(error?.message || error || "unknown")
      }
    };
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
    return {
      ok: false,
      error: "temp_tab_source_url_required"
    };
  }

  let tempTab = null;
  let previousActiveTabId = null;
  try {
    const [previousActiveTab] = await chrome.tabs.query({
      active: true,
      currentWindow: true
    });
    previousActiveTabId = previousActiveTab?.id || null;
    tempTab = await chrome.tabs.create({ url: sourceUrlText, active: true });
    if (!tempTab?.id) {
      return {
        ok: false,
        error: "temp_tab_create_failed"
      };
    }
    await waitForYouTubeTabReadyForExtraction(tempTab.id, TEMP_TAB_LOAD_TIMEOUT_MS);
    await sleep(TEMP_TAB_READY_DELAY_MS);
    return await extractTranscriptViaContentScriptTab(tempTab.id);
  } catch (error) {
    return {
      ok: false,
      error: "temp_tab_content_script_exception",
      debug: {
        sourceUrl: sourceUrlText,
        tabId: tempTab?.id || null,
        message: String(error?.message || error || "unknown")
      }
    };
  } finally {
    if (tempTab?.id) {
      try {
        await chrome.tabs.remove(tempTab.id);
      } catch (_error) {
        // Ignore cleanup failure for temp tab.
      }
    }
    if (previousActiveTabId) {
      try {
        await chrome.tabs.update(previousActiveTabId, { active: true });
      } catch (_error) {
        // Ignore restore focus failures.
      }
    }
  }
}

async function extractYouTubeTranscriptViaTemporaryTabMainWorld(sourceUrl) {
  const sourceUrlText = String(sourceUrl || "").trim();
  if (!sourceUrlText) {
    return {
      ok: false,
      error: "temp_tab_main_world_source_url_required"
    };
  }

  let tempTab = null;
  let previousActiveTabId = null;
  try {
    const [previousActiveTab] = await chrome.tabs.query({
      active: true,
      currentWindow: true
    });
    previousActiveTabId = previousActiveTab?.id || null;
    tempTab = await chrome.tabs.create({ url: sourceUrlText, active: true });
    if (!tempTab?.id) {
      return {
        ok: false,
        error: "temp_tab_main_world_create_failed"
      };
    }
    await waitForYouTubeTabReadyForExtraction(tempTab.id, TEMP_TAB_LOAD_TIMEOUT_MS);
    let lastResult = null;
    for (let attempt = 1; attempt <= YOUTUBE_EXTRACTION_RETRY_ATTEMPTS; attempt += 1) {
      await sleep(TEMP_TAB_READY_DELAY_MS);
      lastResult = await extractYouTubeTranscriptViaMainWorldTab(tempTab.id);
      const hasTranscript = Boolean(lastResult?.ok && String(lastResult.transcript || "").trim());
      if (lastResult?.debug && typeof lastResult.debug === "object") {
        const existingTrace = Array.isArray(lastResult.debug.trace) ? lastResult.debug.trace : [];
        lastResult.debug.trace = [`temp_tab_main_world_attempt=${attempt}`, ...existingTrace];
      }
      if (hasTranscript) {
        return lastResult;
      }
      if (attempt < YOUTUBE_EXTRACTION_RETRY_ATTEMPTS) {
        await sleep(YOUTUBE_EXTRACTION_RETRY_DELAY_MS);
      }
    }
    return lastResult || {
      ok: false,
      error: "temp_tab_main_world_empty_result",
      debug: {
        sourceUrl: sourceUrlText,
        tabId: tempTab?.id || null
      }
    };
  } catch (error) {
    return {
      ok: false,
      error: "temp_tab_main_world_exception",
      debug: {
        sourceUrl: sourceUrlText,
        tabId: tempTab?.id || null,
        message: String(error?.message || error || "unknown")
      }
    };
  } finally {
    if (tempTab?.id) {
      try {
        await chrome.tabs.remove(tempTab.id);
      } catch (_error) {
        // Ignore cleanup failure for temp tab.
      }
    }
    if (previousActiveTabId) {
      try {
        await chrome.tabs.update(previousActiveTabId, { active: true });
      } catch (_error) {
        // Ignore restore focus failures.
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
    return {
      ok: false,
      error: "main_world_tab_id_required"
    };
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

        const extractBalancedBlock = (source, startIndex, openChar, closeChar) => {
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
        };

        const parseJsonObjectAfterMarker = (source, marker) => {
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
          const lines = [];
          const source = String(xmlText || "");
          const pattern = /<(text|p|s)\b[^>]*>([\s\S]*?)<\/\1>/g;

          for (const match of source.matchAll(pattern)) {
            const raw = String(match[2] || "").replace(/<[^>]+>/g, " ");
            const cleaned = normalizeWhitespace(decodeHtmlEntities(raw));
            if (cleaned) {
              lines.push(cleaned);
            }
          }
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

        const extractTextFromRuns = (value) => {
          if (!value) {
            return "";
          }
          if (typeof value === "string") {
            return normalizeWhitespace(decodeHtmlEntities(value));
          }
          if (Array.isArray(value)) {
            return normalizeWhitespace(value.map((item) => extractTextFromRuns(item)).filter(Boolean).join(""));
          }
          if (typeof value === "object") {
            if (typeof value.text === "string") {
              return normalizeWhitespace(decodeHtmlEntities(value.text));
            }
            if (typeof value.utf8 === "string") {
              return normalizeWhitespace(decodeHtmlEntities(value.utf8));
            }
            if (typeof value.simpleText === "string") {
              return normalizeWhitespace(decodeHtmlEntities(value.simpleText));
            }
            if (Array.isArray(value.runs)) {
              return normalizeWhitespace(value.runs.map((item) => extractTextFromRuns(item)).filter(Boolean).join(""));
            }
            for (const key of ["cue", "snippet", "content", "headline", "title"]) {
              const nestedText = extractTextFromRuns(value[key]);
              if (nestedText) {
                return nestedText;
              }
            }
          }
          return "";
        };

        const isLikelyTranscriptTimestamp = (text) => /^(?:\d{1,2}:)?\d{1,2}:\d{2}$/.test(String(text || "").trim());

        const extractTranscriptFromCueGroups = (cueGroups) => {
          const lines = [];
          for (const group of Array.isArray(cueGroups) ? cueGroups : []) {
            const cues = Array.isArray(group?.transcriptCueGroupRenderer?.cues)
              ? group.transcriptCueGroupRenderer.cues
              : [];
            for (const cue of cues) {
              const renderer = cue?.transcriptCueRenderer || cue || {};
              const line = extractTextFromRuns(
                renderer.cue ||
                renderer.snippet ||
                renderer.content ||
                renderer.cueSimpleText ||
                renderer.text ||
                renderer
              );
              if (!line || isLikelyTranscriptTimestamp(line)) {
                continue;
              }
              lines.push(line);
            }
          }
          return normalizeWhitespace(dedupeTranscriptLines(lines).join("\n"));
        };

        const collectCueGroups = (root, results = [], seen = new Set()) => {
          if (!root || typeof root !== "object" || seen.has(root) || results.length >= 5) {
            return results;
          }
          seen.add(root);
          if (Array.isArray(root)) {
            for (const item of root) {
              collectCueGroups(item, results, seen);
              if (results.length >= 5) {
                break;
              }
            }
            return results;
          }
          if (Array.isArray(root.cueGroups) && root.cueGroups.length) {
            results.push(root.cueGroups);
          }
          for (const value of Object.values(root)) {
            collectCueGroups(value, results, seen);
            if (results.length >= 5) {
              break;
            }
          }
          return results;
        };

        const extractTranscriptFromStructuredData = (root) => {
          const candidates = collectCueGroups(root);
          for (const cueGroups of candidates) {
            const transcript = extractTranscriptFromCueGroups(cueGroups);
            if (transcript) {
              return transcript;
            }
          }
          return "";
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
            if (!text.includes("captionTracks") && !text.includes("ytInitialPlayerResponse") && !text.includes("ytInitialData")) {
              continue;
            }
            const markers = [
              "ytInitialPlayerResponse =",
              "var ytInitialPlayerResponse =",
              "window[\"ytInitialPlayerResponse\"] =",
              "ytInitialPlayerResponse=",
              "\"ytInitialPlayerResponse\":",
              "ytInitialData =",
              "var ytInitialData =",
              "window[\"ytInitialData\"] =",
              "ytInitialData=",
              "\"ytInitialData\":"
            ];

            for (const marker of markers) {
              const resp = parseJsonObjectAfterMarker(text, marker);
              const tracks = resp?.captions?.playerCaptionsTracklistRenderer?.captionTracks;
              if (Array.isArray(tracks) && tracks.length) {
                return tracks;
              }
            }
          }

          return [];
        };

        const CLIENT_NAME_TO_ID = {
          WEB: "1",
          MWEB: "2",
          ANDROID: "3",
          IOS: "5",
          TVHTML5: "7"
        };

        const findValuesByKey = (root, targetKey, results = [], seen = new Set()) => {
          if (!root || typeof root !== "object" || seen.has(root) || results.length >= 20) {
            return results;
          }
          seen.add(root);
          if (Array.isArray(root)) {
            for (const item of root) {
              findValuesByKey(item, targetKey, results, seen);
              if (results.length >= 20) {
                break;
              }
            }
            return results;
          }
          for (const [key, value] of Object.entries(root)) {
            if (key === targetKey) {
              results.push(value);
              if (results.length >= 20) {
                break;
              }
            }
            findValuesByKey(value, targetKey, results, seen);
            if (results.length >= 20) {
              break;
            }
          }
          return results;
        };

        const getYoutubeVideoId = () => {
          try {
            const currentUrl = new URL(String(location.href || ""));
            const watchId = currentUrl.searchParams.get("v") || "";
            if (watchId) {
              return watchId;
            }
            const pathParts = currentUrl.pathname.split("/").filter(Boolean);
            if (pathParts.length >= 2 && ["shorts", "live", "embed"].includes(pathParts[0])) {
              return pathParts[1];
            }
          } catch (_error) {
            // Ignore malformed location.
          }
          return "";
        };

        const getInnertubeConfig = () => {
          let apiKey = "";
          let clientVersion = "";
          let clientName = "";
          let visitorData = "";
          let hl = "";
          let gl = "";
          let sessionIndex = "";
          let delegatedSessionId = "";
          let loggedIn = false;
          let context = null;

          const contextCandidates = [];

          try {
            apiKey = String(globalThis?.ytcfg?.get?.("INNERTUBE_API_KEY") || "");
            clientVersion = String(globalThis?.ytcfg?.get?.("INNERTUBE_CLIENT_VERSION") || "");
            clientName = String(globalThis?.ytcfg?.get?.("INNERTUBE_CONTEXT_CLIENT_NAME") || "");
            visitorData = String(globalThis?.ytcfg?.get?.("VISITOR_DATA") || "");
            hl = String(globalThis?.ytcfg?.get?.("HL") || "");
            gl = String(globalThis?.ytcfg?.get?.("GL") || "");
            sessionIndex = String(globalThis?.ytcfg?.get?.("SESSION_INDEX") || "");
            delegatedSessionId = String(globalThis?.ytcfg?.get?.("DELEGATED_SESSION_ID") || "");
            loggedIn = Boolean(globalThis?.ytcfg?.get?.("LOGGED_IN"));
            contextCandidates.push(parseMaybeJson(globalThis?.ytcfg?.get?.("INNERTUBE_CONTEXT")));
          } catch (_e) {}

          contextCandidates.push(parseMaybeJson(globalThis?.ytcfg?.data_?.INNERTUBE_CONTEXT));

          for (const candidate of contextCandidates) {
            if (!candidate || typeof candidate !== "object") {
              continue;
            }
            const client = candidate.client || {};
            context = context || candidate;
            if (!clientVersion && typeof client.clientVersion === "string") {
              clientVersion = client.clientVersion;
            }
            if (!clientName && typeof client.clientName === "string") {
              clientName = client.clientName;
            }
            if (!visitorData && typeof client.visitorData === "string") {
              visitorData = client.visitorData;
            }
            if (!hl && typeof client.hl === "string") {
              hl = client.hl;
            }
            if (!gl && typeof client.gl === "string") {
              gl = client.gl;
            }
          }

          if (!apiKey || !clientVersion || !visitorData || !hl || !gl || !clientName || !context) {
            const scripts = Array.from(document.getElementsByTagName("script"));
            for (const s of scripts) {
              const text = s.textContent || "";
              if (!text) {
                continue;
              }
              if (!apiKey) {
                const m1 = text.match(/"INNERTUBE_API_KEY"\s*:\s*"([^"]+)"/);
                if (m1) {
                  apiKey = m1[1];
                }
              }
              if (!clientVersion) {
                const m2 = text.match(/"INNERTUBE_CLIENT_VERSION"\s*:\s*"([^"]+)"/);
                if (m2) {
                  clientVersion = m2[1];
                }
              }
              if (!clientName) {
                const m3 = text.match(/"INNERTUBE_CONTEXT_CLIENT_NAME"\s*:\s*"([^"]+)"/);
                if (m3) {
                  clientName = m3[1];
                }
              }
              if (!visitorData) {
                const m4 = text.match(/"VISITOR_DATA"\s*:\s*"([^"]+)"/);
                if (m4) {
                  visitorData = m4[1];
                }
              }
              if (!hl) {
                const m5 = text.match(/"HL"\s*:\s*"([^"]+)"/);
                if (m5) {
                  hl = m5[1];
                }
              }
              if (!gl) {
                const m6 = text.match(/"GL"\s*:\s*"([^"]+)"/);
                if (m6) {
                  gl = m6[1];
                }
              }
              if (!context) {
                context = parseJsonObjectAfterMarker(text, "\"INNERTUBE_CONTEXT\":");
              }
              if (apiKey && clientVersion && visitorData && hl && gl && clientName && context) {
                break;
              }
            }
          }

          return {
            apiKey,
            clientVersion,
            clientName: String(clientName || "WEB"),
            visitorData,
            hl,
            gl,
            sessionIndex,
            delegatedSessionId,
            loggedIn,
            context: context && typeof context === "object" ? context : null
          };
        };

        const buildInnertubeContext = (innertubeConfig, overrideClientName = "") => {
          const baseContext = (() => {
            try {
              return JSON.parse(JSON.stringify(innertubeConfig?.context || {}));
            } catch (_error) {
              return {};
            }
          })();
          const client = baseContext.client && typeof baseContext.client === "object"
            ? baseContext.client
            : {};
          const finalClientName = String(overrideClientName || client.clientName || innertubeConfig?.clientName || "WEB");
          const finalClientVersion = String(client.clientVersion || innertubeConfig?.clientVersion || "");

          baseContext.client = {
            ...client,
            clientName: finalClientName,
            clientVersion: finalClientVersion
          };

          if (!baseContext.client.hl && innertubeConfig?.hl) {
            baseContext.client.hl = innertubeConfig.hl;
          }
          if (!baseContext.client.gl && innertubeConfig?.gl) {
            baseContext.client.gl = innertubeConfig.gl;
          }
          if (!baseContext.client.visitorData && innertubeConfig?.visitorData) {
            baseContext.client.visitorData = innertubeConfig.visitorData;
          }
          if (!baseContext.client.clientScreen) {
            baseContext.client.clientScreen = "WATCH";
          }

          if (!baseContext.request || typeof baseContext.request !== "object") {
            baseContext.request = {};
          }
          if (typeof baseContext.request.useSsl === "undefined") {
            baseContext.request.useSsl = true;
          }

          if (!baseContext.user || typeof baseContext.user !== "object") {
            baseContext.user = {};
          }
          if (innertubeConfig?.delegatedSessionId && !baseContext.user.delegatedSessionId) {
            baseContext.user.delegatedSessionId = innertubeConfig.delegatedSessionId;
          }
          return baseContext;
        };

        const buildYoutubeiHeaders = (innertubeConfig, requestContext) => {
          const clientName = String(requestContext?.client?.clientName || innertubeConfig?.clientName || "WEB").toUpperCase();
          const headers = {
            "Content-Type": "application/json",
            "X-YouTube-Client-Name": CLIENT_NAME_TO_ID[clientName] || "1",
            "X-YouTube-Client-Version": String(requestContext?.client?.clientVersion || innertubeConfig?.clientVersion || "")
          };
          if (innertubeConfig?.visitorData) {
            headers["X-Goog-Visitor-Id"] = innertubeConfig.visitorData;
          }
          if (typeof innertubeConfig?.loggedIn !== "undefined") {
            headers["X-Youtube-Bootstrap-Logged-In"] = innertubeConfig.loggedIn ? "true" : "false";
          }
          if (innertubeConfig?.sessionIndex) {
            headers["X-Goog-AuthUser"] = innertubeConfig.sessionIndex;
          }
          return headers;
        };

        const getTranscriptParamsCandidates = () => {
          const results = [];
          const seen = new Set();
          const pushCandidate = (params, source) => {
            const value = String(params || "").trim();
            if (!value || seen.has(value)) {
              return;
            }
            seen.add(value);
            results.push({ params: value, source });
          };

          const initialDataCandidates = [
            { value: globalThis.ytInitialData, source: "ytInitialData" },
            { value: parseMaybeJson(globalThis?.ytcfg?.data_?.INITIAL_DATA), source: "ytcfg.data_.INITIAL_DATA" }
          ];
          if (typeof globalThis?.ytcfg?.get === "function") {
            initialDataCandidates.push({ value: parseMaybeJson(globalThis.ytcfg.get("INITIAL_DATA")), source: "ytcfg.get(INITIAL_DATA)" });
            initialDataCandidates.push({ value: parseMaybeJson(globalThis.ytcfg.get("ytInitialData")), source: "ytcfg.get(ytInitialData)" });
          }

          for (const candidate of initialDataCandidates) {
            const root = candidate.value;
            if (!root || typeof root !== "object") {
              continue;
            }
            const endpoints = findValuesByKey(root, "getTranscriptEndpoint");
            for (const endpoint of endpoints) {
              pushCandidate(endpoint?.params, candidate.source);
            }
          }

          const scripts = Array.from(document.getElementsByTagName("script"));
          for (const s of scripts) {
            const text = s.textContent || "";
            if (!text.includes("getTranscriptEndpoint")) {
              continue;
            }
            for (const match of text.matchAll(/"getTranscriptEndpoint"\s*:\s*\{\s*"params"\s*:\s*"([^"]+)"/g)) {
              pushCandidate(match[1], "inline_script");
            }
          }

          return results;
        };

        const extractTranscriptFromYoutubeiData = (data) => {
          const renderers = findValuesByKey(data, "transcriptSegmentListRenderer");
          const lines = [];

          for (const renderer of renderers) {
            const segments = Array.isArray(renderer?.initialSegments)
              ? renderer.initialSegments
              : Array.isArray(renderer?.segments)
                ? renderer.segments
                : [];
            for (const segment of segments) {
              const transcriptRenderer = segment?.transcriptSegmentRenderer || segment || {};
              const text = extractTextFromRuns(
                transcriptRenderer.snippet ||
                transcriptRenderer.cue ||
                transcriptRenderer.content ||
                transcriptRenderer.text ||
                transcriptRenderer
              );
              if (!text || isLikelyTranscriptTimestamp(text)) {
                continue;
              }
              lines.push(text);
            }
          }

          return normalizeWhitespace(dedupeTranscriptLines(lines).join("\n"));
        };

        const fetchInnertubeJson = async (endpointName, innertubeConfig, requestContext, requestBody) => {
          const url = new URL(`/youtubei/v1/${endpointName}`, location.origin);
          url.searchParams.set("prettyPrint", "false");
          if (innertubeConfig?.apiKey) {
            url.searchParams.set("key", innertubeConfig.apiKey);
          }

          const response = await fetch(url.toString(), {
            method: "POST",
            headers: buildYoutubeiHeaders(innertubeConfig, requestContext),
            body: JSON.stringify(requestBody),
            credentials: "same-origin",
            cache: "no-store"
          });

          const rawText = await response.text();
          let data = null;
          try {
            data = rawText ? JSON.parse(rawText) : null;
          } catch (_error) {
            data = null;
          }

          return {
            ok: response.ok,
            status: response.status,
            data,
            bodyPreview: normalizeWhitespace(rawText).slice(0, 240)
          };
        };

        const fetchTranscriptViaYoutubei = async () => {
          const innertubeConfig = getInnertubeConfig();
          const paramsCandidates = getTranscriptParamsCandidates();
          const debugTrace = [];

          if (!innertubeConfig.apiKey) {
            debugTrace.push("youtubei_missing_api_key");
          }
          if (!innertubeConfig.clientVersion) {
            debugTrace.push("youtubei_missing_client_version");
          }
          if (!paramsCandidates.length) {
            debugTrace.push("youtubei_missing_transcript_params");
          }
          if (!innertubeConfig.apiKey || !innertubeConfig.clientVersion || !paramsCandidates.length) {
            return {
              ok: false,
              error: "youtubei_prerequisites_missing",
              debug: {
                source: "youtubei_get_transcript",
                trace: debugTrace
              }
            };
          }

          const contextCandidates = [];
          const contextSeen = new Set();
          const pushContext = (clientName) => {
            const context = buildInnertubeContext(innertubeConfig, clientName);
            const signature = `${String(context?.client?.clientName || "")}|${String(context?.client?.clientVersion || "")}`;
            if (!context?.client?.clientVersion || contextSeen.has(signature)) {
              return;
            }
            contextSeen.add(signature);
            contextCandidates.push(context);
          };
          pushContext("");
          pushContext("WEB");
          pushContext("MWEB");

          for (const candidate of paramsCandidates.slice(0, 4)) {
            for (const requestContext of contextCandidates) {
              const clientName = String(requestContext?.client?.clientName || "WEB");
              try {
                const response = await fetchInnertubeJson(
                  "get_transcript",
                  innertubeConfig,
                  requestContext,
                  {
                    context: requestContext,
                    params: candidate.params
                  }
                );
                if (!response.ok) {
                  debugTrace.push(`youtubei_http_${response.status}:client=${clientName}:source=${candidate.source}:body=${response.bodyPreview || "empty"}`);
                  continue;
                }
                const transcript = extractTranscriptFromYoutubeiData(response.data);
                if (transcript) {
                  return {
                    ok: true,
                    transcript,
                    debug: {
                      source: "youtubei_get_transcript",
                      clientName,
                      paramsSource: candidate.source,
                      trace: debugTrace
                    }
                  };
                }
                debugTrace.push(`youtubei_empty_segments:client=${clientName}:source=${candidate.source}`);
              } catch (error) {
                debugTrace.push(`youtubei_exception:client=${clientName}:source=${candidate.source}:error=${String(error?.message || error || "unknown")}`);
              }
            }
          }

          const videoId = getYoutubeVideoId();
          if (videoId) {
            for (const requestContext of contextCandidates) {
              const clientName = String(requestContext?.client?.clientName || "WEB");
              try {
                const playerResponse = await fetchInnertubeJson(
                  "player",
                  innertubeConfig,
                  requestContext,
                  {
                    context: requestContext,
                    videoId,
                    contentCheckOk: true,
                    racyCheckOk: true
                  }
                );
                if (!playerResponse.ok) {
                  debugTrace.push(`player_http_${playerResponse.status}:client=${clientName}:body=${playerResponse.bodyPreview || "empty"}`);
                  continue;
                }
                const playerTracks = normalizeCaptionTracks(
                  playerResponse?.data?.captions?.playerCaptionsTracklistRenderer?.captionTracks
                );
                if (!playerTracks.length) {
                  debugTrace.push(`player_no_tracks:client=${clientName}`);
                  continue;
                }
                for (const track of playerTracks) {
                  const transcript = await (async () => {
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
                      // Ignore malformed URL and try the original one.
                    }
                    candidates.push(baseUrl);
                    for (const candidateUrl of candidates) {
                      try {
                        const captionResp = await fetch(candidateUrl, {
                          method: "GET",
                          credentials: "same-origin",
                          cache: "no-store"
                        });
                        if (!captionResp.ok) {
                          continue;
                        }
                        const rawText = await captionResp.text();
                        const trimmed = rawText.trim();
                        if (!trimmed) {
                          continue;
                        }
                        try {
                          if (trimmed.startsWith("{")) {
                            return parseYouTubeJsonTranscript(JSON.parse(trimmed));
                          }
                        } catch (_error) {
                          // Continue to XML/VTT parsers below.
                        }
                        return parseYouTubeXmlTranscript(trimmed) || parseYouTubeVttTranscript(trimmed);
                      } catch (_error) {
                        // Continue to the next caption URL candidate.
                      }
                    }
                    return "";
                  })();
                  if (transcript) {
                    return {
                      ok: true,
                      transcript,
                      debug: {
                        source: "youtubei_player_caption_track",
                        clientName,
                        languageCode: String(track?.languageCode || ""),
                        trace: debugTrace
                      }
                    };
                  }
                }
                debugTrace.push(`player_tracks_unreadable:client=${clientName}`);
              } catch (error) {
                debugTrace.push(`player_exception:client=${clientName}:error=${String(error?.message || error || "unknown")}`);
              }
            }
          }

          return {
            ok: false,
            error: "youtubei_get_transcript_failed",
            debug: {
              source: "youtubei_get_transcript",
              trace: debugTrace
            }
          };
        };

        const getInlineTranscript = () => {
          const initialDataCandidates = [];
          const parseMaybeJson = (val) => {
            if (!val) return null;
            if (typeof val === "object") return val;
            try { return JSON.parse(val); } catch (_error) { return null; }
          };

          initialDataCandidates.push(globalThis.ytInitialData);
          initialDataCandidates.push(parseMaybeJson(globalThis?.ytcfg?.data_?.INITIAL_DATA));
          if (typeof globalThis?.ytcfg?.get === "function") {
            initialDataCandidates.push(parseMaybeJson(globalThis.ytcfg.get("INITIAL_DATA")));
            initialDataCandidates.push(parseMaybeJson(globalThis.ytcfg.get("ytInitialData")));
          }

          for (const candidate of initialDataCandidates) {
            const transcript = extractTranscriptFromStructuredData(candidate);
            if (transcript) {
              return transcript;
            }
          }

          const scripts = Array.from(document.getElementsByTagName("script"));
          for (const scriptNode of scripts) {
            const text = scriptNode.textContent || "";
            if (!text.includes("cueGroups") && !text.includes("ytInitialData")) {
              continue;
            }
            const markers = [
              "ytInitialData =",
              "var ytInitialData =",
              "window[\"ytInitialData\"] =",
              "ytInitialData=",
              "\"ytInitialData\":"
            ];
            for (const marker of markers) {
              const parsed = parseJsonObjectAfterMarker(text, marker);
              const transcript = extractTranscriptFromStructuredData(parsed);
              if (transcript) {
                return transcript;
              }
            }
          }

          return "";
        };

        const getSearchRoots = () => {
          const roots = [document];
          const queue = [document];
          const seen = new Set([document]);
          while (queue.length) {
            const root = queue.shift();
            const elements = root.querySelectorAll ? Array.from(root.querySelectorAll("*")) : [];
            for (const element of elements) {
              if (element.shadowRoot && !seen.has(element.shadowRoot)) {
                seen.add(element.shadowRoot);
                roots.push(element.shadowRoot);
                queue.push(element.shadowRoot);
              }
            }
          }
          return roots;
        };

        const querySelectorAllDeep = (selector) => {
          const results = [];
          const seen = new Set();
          for (const root of getSearchRoots()) {
            const nodes = root.querySelectorAll ? Array.from(root.querySelectorAll(selector)) : [];
            for (const node of nodes) {
              if (!seen.has(node)) {
                seen.add(node);
                results.push(node);
              }
            }
          }
          return results;
        };

        const querySelectorDeep = (selector) => querySelectorAllDeep(selector)[0] || null;

        const isVisibleElement = (node) => {
          if (!node) {
            return false;
          }
          const rect = node.getBoundingClientRect();
          const style = globalThis.getComputedStyle(node);
          return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none";
        };

        const cleanTranscriptLine = (line) => {
          let normalized = normalizeWhitespace(line);
          if (!normalized) {
            return "";
          }
          // New transcript-segment-view-model nodes often flatten timestamp + duration + content into one line.
          for (let i = 0; i < 2; i += 1) {
            normalized = normalizeWhitespace(
              normalized
                .replace(/^(?:\d{1,2}:)?\d{1,2}:\d{2}\s*/i, "")
                .replace(/^(?:\d+\s*(?:hours?|hour|hrs?|hr|小时)\s*)?(?:\d+\s*(?:minutes?|minute|mins?|min|分钟)\s*)?(?:\d+\s*(?:seconds?|second|secs?|sec|秒钟|秒))\s*/i, "")
            );
          }
          if (!normalized || isLikelyTranscriptTimestamp(normalized)) {
            return "";
          }
          const lower = normalized.toLowerCase();
          const skipFragments = [
            "show transcript",
            "open transcript",
            "search in video",
            "在视频中搜索",
            "转写文稿",
            "内容转文字",
            "文字稿",
            "转录稿"
          ];
          if (skipFragments.some((fragment) => lower === fragment || lower.includes(fragment))) {
            return "";
          }
          if (
            /^\d+\s*(seconds?|second|secs?|sec|秒钟|秒)$/.test(lower) ||
            /^(?:\d+\s*(?:hours?|hour|hrs?|hr|小时)\s*)?(?:\d+\s*(?:minutes?|minute|mins?|min|分钟)\s*)?(?:\d+\s*(?:seconds?|second|secs?|sec|秒钟|秒))$/.test(lower)
          ) {
            return "";
          }
          return normalized;
        };

        const extractTranscriptFromVisiblePanel = () => {
          const segmentSelectors = [
            "ytd-transcript-segment-renderer .segment-text",
            "ytd-transcript-segment-renderer .cue",
            "ytd-transcript-segment-renderer yt-formatted-string",
            "ytd-engagement-panel-section-list-renderer[target-id*='transcript'] ytd-transcript-segment-renderer yt-formatted-string",
            "ytd-engagement-panel-section-list-renderer[target-id*='transcript'] .segment-text",
            "ytd-engagement-panel-section-list-renderer[target-id*='transcript'] .cue",
            "transcript-segment-view-model .segment-text",
            "transcript-segment-view-model [role='button']",
            "ytd-transcript-segment-renderer",
            "transcript-segment-view-model"
          ];
          const lines = [];
          for (const selector of segmentSelectors) {
            const nodes = querySelectorAllDeep(selector);
            if (!nodes.length) {
              continue;
            }
            for (const node of nodes) {
                const tagName = String(node?.tagName || "").toLowerCase();
                const rawText = normalizeWhitespace(node.innerText || node.textContent || "");
                if (!rawText) {
                  continue;
                }
                const shouldRequireVisible = !tagName.includes("transcript-segment-view-model");
                if (shouldRequireVisible && !isVisibleElement(node)) {
                continue;
              }
                const cleaned = cleanTranscriptLine(rawText);
              if (cleaned) {
                lines.push(cleaned);
              }
            }
            if (lines.length > 5) {
              break;
            }
          }
          const directResult = normalizeWhitespace(dedupeTranscriptLines(lines).join("\n"));
          if (directResult.length > 20) {
            return directResult;
          }

          const panel = querySelectorDeep([
            "ytd-transcript-search-panel-renderer",
            "ytd-engagement-panel-section-list-renderer[target-id*='transcript']",
            "ytd-engagement-panel-section-list-renderer[target-id='PAmodern_transcript_view']"
          ].join(", "));
          if (!panel || !isVisibleElement(panel)) {
            return "";
          }
          const rawLines = normalizeWhitespace(panel.innerText || panel.textContent || "")
            .split("\n")
            .map((line) => cleanTranscriptLine(line))
            .filter(Boolean);
          return normalizeWhitespace(dedupeTranscriptLines(rawLines).join("\n"));
        };

        const findClickableByText = (patterns) => {
          const nodes = querySelectorAllDeep('button, [role="button"], tp-yt-paper-item, ytd-menu-service-item-renderer');
          for (const node of nodes) {
            const text = normalizeWhitespace(node.textContent || "").toLowerCase();
            if (!text) {
              continue;
            }
            if (patterns.some((pattern) => text.includes(pattern))) {
              return node.closest('button, [role="button"], tp-yt-paper-item, ytd-menu-service-item-renderer') || node;
            }
          }
          return null;
        };

        const findYouTubeMoreActionsButton = () => {
          const candidates = querySelectorAllDeep("button, [role='button']");
          const labels = ["more actions", "更多操作", "更多", "actions"];
          for (const node of candidates) {
            const aria = String(node.getAttribute("aria-label") || "").toLowerCase();
            const title = String(node.getAttribute("title") || "").toLowerCase();
            const tooltip = String(node.getAttribute("data-tooltip-text") || "").toLowerCase();
            const text = normalizeWhitespace(node.textContent || "").toLowerCase();
            const joined = [aria, title, tooltip, text].join(" | ");
            if (!joined) {
              continue;
            }
            if (!labels.some((label) => joined.includes(label))) {
              continue;
            }
            if (joined.includes("download") || joined.includes("下载") || joined.includes("premium")) {
              continue;
            }
            if (isVisibleElement(node)) {
              return node;
            }
          }
          return null;
        };

        const clickNode = async (node) => {
          if (!node) {
            return false;
          }
          node.click();
          await new Promise((resolve) => globalThis.setTimeout(resolve, 800));
          return true;
        };

        const ensureTranscriptPanelVisible = async () => {
          if (extractTranscriptFromVisiblePanel()) {
            return { ok: true, autoOpened: false };
          }
          const transcriptPatterns = [
            "show transcript",
            "open transcript",
            "transcript",
            "显示文字稿",
            "显示转录稿",
            "转录稿",
            "文字稿",
            "转写文稿",
            "内容转文字"
          ];
          const directButton = findClickableByText(transcriptPatterns);
          if (await clickNode(directButton)) {
            for (let i = 0; i < 16; i += 1) {
              await new Promise((resolve) => globalThis.setTimeout(resolve, 1000));
              if (extractTranscriptFromVisiblePanel()) {
                return { ok: true, autoOpened: true, path: "direct_button" };
              }
            }
          }
          const moreActionsButton = findYouTubeMoreActionsButton();
          if (await clickNode(moreActionsButton)) {
            const menuTranscriptButton = findClickableByText(transcriptPatterns);
            if (await clickNode(menuTranscriptButton)) {
              for (let i = 0; i < 16; i += 1) {
                await new Promise((resolve) => globalThis.setTimeout(resolve, 1000));
                if (extractTranscriptFromVisiblePanel()) {
                  return { ok: true, autoOpened: true, path: "more_actions_menu" };
                }
              }
            }
          }
          return { ok: false, autoOpened: false, path: "none" };
        };

        const tracks = getCaptionTracks();
        const extractionTrace = [];
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

        // Try youtubei get_transcript first to bypass empty timedtext responses
        {
          const ytai = await fetchTranscriptViaYoutubei();
          if (Array.isArray(ytai?.debug?.trace)) {
            extractionTrace.push(...ytai.debug.trace);
          }
          if (ytai && ytai.ok && ytai.transcript) {
            return {
              ok: true,
              transcript: ytai.transcript,
              debug: {
                trackCount: tracks.length,
                source: String(ytai?.debug?.source || "youtubei_get_transcript"),
                clientName: String(ytai?.debug?.clientName || ""),
                paramsSource: String(ytai?.debug?.paramsSource || ""),
                trace: extractionTrace
              }
            };
          }
        }

        for (const track of sortedTracks) {
          const baseUrl = String(track?.baseUrl || "").trim();
          if (!baseUrl) {
            extractionTrace.push(`Empty baseUrl for track: ${track?.languageCode}`);
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
                extractionTrace.push(`Fetch failed for ${candidate.slice(0, 50)}...: ${resp.status}`);
                continue;
              }
              const rawText = await resp.text();
              const trimmed = rawText.trim();
              if (!trimmed) {
                extractionTrace.push(`Empty body for ${candidate.slice(0, 50)}...`);
                continue;
              }
              let transcript = "";
              let parseError = "";
              try {
                if (trimmed.startsWith("{")) {
                  transcript = parseYouTubeJsonTranscript(JSON.parse(trimmed));
                } else {
                  transcript = parseYouTubeXmlTranscript(trimmed) || parseYouTubeVttTranscript(trimmed);
                }
              } catch (e) {
                parseError = String(e.message || e);
                extractionTrace.push(`Parse error for ${candidate.slice(0, 50)}...: ${parseError}`);
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
              } else {
                extractionTrace.push(`No text extracted from ${candidate.slice(0, 50)}... (ParseError: ${parseError})`);
              }
            } catch (err) {
              extractionTrace.push(`Network error for ${candidate.slice(0, 50)}...: ${err.message}`);
            }
          }
        }

        const inlineTranscript = getInlineTranscript();
        if (inlineTranscript) {
          extractionTrace.push("Recovered transcript from ytInitialData cueGroups fallback");
          return {
            ok: true,
            transcript: inlineTranscript,
            debug: {
              trackCount: tracks.length,
              source: "main_world_cuegroups_fallback",
              trace: extractionTrace
            }
          };
        }
        extractionTrace.push("No transcript extracted from ytInitialData cueGroups fallback");

        const panelVisibilityResult = await ensureTranscriptPanelVisible();
        extractionTrace.push(`transcript_panel_visible=${panelVisibilityResult.ok}:autoOpened=${panelVisibilityResult.autoOpened}:path=${String(panelVisibilityResult.path || "")}`);
        const panelTranscript = extractTranscriptFromVisiblePanel();
        if (panelTranscript) {
          extractionTrace.push(`transcript_panel_dom_chars=${panelTranscript.length}`);
          extractionTrace.push("Recovered transcript from transcript panel DOM");
          return {
            ok: true,
            transcript: panelTranscript,
            debug: {
              trackCount: tracks.length,
              source: "main_world_transcript_panel_dom",
              trace: extractionTrace
            }
          };
        }
        extractionTrace.push("No transcript extracted from transcript panel DOM");

        return {
          ok: false,
          error: "main_world_caption_fetch_failed",
          debug: {
            trackCount: tracks.length,
            trace: extractionTrace
          }
        };
      }
    });
    return injectionResult?.result || {
      ok: false,
      error: "main_world_empty_injection_result",
      debug: {
        tabId
      }
    };
  } catch (error) {
    return {
      ok: false,
      error: "main_world_execute_script_failed",
      debug: {
        tabId,
        message: String(error?.message || error || "unknown")
      }
    };
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
  } else {
    attempts.push({
      stage: "matched_tab_found",
      ok: false,
      error: "no_matching_tab"
    });
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
        toolVersion: EXTENSION_TOOL_VERSION,
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
      toolVersion: EXTENSION_TOOL_VERSION,
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
        const result = await extractYouTubeTranscriptForPageFlow(sourceUrl);
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
