(function () {
  const PAGE_REQUEST_NAMESPACE = "yt-summary-page-request";
  const PAGE_REQUEST_STORAGE_PREFIX = "yt-summary-page-request:";
  const PAGE_RESPONSE_STORAGE_PREFIX = "yt-summary-page-response:";
  const BROADCAST_CHANNEL_NAME = "yt-summary-broadcast-channel";

  // Initialize BroadcastChannel if available
  const broadcastChannel = (typeof window.BroadcastChannel === "function") 
    ? new window.BroadcastChannel(BROADCAST_CHANNEL_NAME)
    : null;

  function sleep(ms) {
    return new Promise((resolve) => window.setTimeout(resolve, ms));
  }

  function getSearchRoots() {
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
  }

  function querySelectorAllDeep(selector) {
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
  }

  function querySelectorDeep(selector) {
    const matches = querySelectorAllDeep(selector);
    return matches[0] || null;
  }

  function normalizeWhitespace(text) {
    return String(text || "")
      .replace(/\u200b/g, "")
      .replace(/[ \t]+\n/g, "\n")
      .replace(/\n{3,}/g, "\n\n")
      .trim();
  }

  let activeExtractionLogger = null;

  function setExtractionLogger(logger) {
    activeExtractionLogger = typeof logger === "function" ? logger : null;
  }

  function traceExtraction(message) {
    if (!activeExtractionLogger) {
      return;
    }
    try {
      activeExtractionLogger(message);
    } catch (_error) {
      // Never let diagnostic logging break transcript extraction.
    }
  }

  function parseJsonSafely(rawValue) {
    if (!rawValue) {
      return null;
    }
    try {
      return JSON.parse(rawValue);
    } catch (_error) {
      return null;
    }
  }

  function writePageFlowStorageResponse(requestId, replyPayload) {
    const responseKey = `${PAGE_RESPONSE_STORAGE_PREFIX}${requestId}`;
    const envelope = JSON.stringify({
      namespace: PAGE_REQUEST_NAMESPACE,
      action: "summarizeFlowReply",
      requestId,
      payload: replyPayload
    });
    for (const store of [window.localStorage, window.sessionStorage]) {
      try {
        store.setItem(responseKey, envelope);
      } catch (_error) {
        // Ignore storage write issues and keep other delivery paths alive.
      }
    }
  }

  function consumePageFlowStorageRequest(storageKey) {
    for (const store of [window.localStorage, window.sessionStorage]) {
      try {
        store.removeItem(storageKey);
      } catch (_error) {
        // Ignore cleanup errors.
      }
    }
  }

  function dedupeTranscriptLines(lines) {
    const result = [];
    const seen = new Set();
    for (const rawLine of Array.isArray(lines) ? lines : []) {
      const line = normalizeWhitespace(rawLine);
      if (!line) {
        continue;
      }
      if (seen.has(line)) {
        continue;
      }
      seen.add(line);
      result.push(line);
    }
    return result;
  }

  function getTitle() {
    const selectors = [
      "h1.ytd-watch-metadata",
      "h1.video-title",
      "h1",
      ".video-title",
      ".title-txt"
    ];
    for (const selector of selectors) {
      const node = document.querySelector(selector);
      if (node && node.textContent.trim()) {
        return node.textContent.trim();
      }
    }
    return document.title || "";
  }

  function extractYouTubeTranscript() {
    const segmentSelectors = [
      "ytd-transcript-segment-renderer .segment-text",
      "ytd-transcript-segment-renderer .cue",
      "ytd-transcript-segment-renderer yt-formatted-string",
      "ytd-transcript-search-panel-renderer ytd-transcript-segment-renderer yt-formatted-string",
      "ytd-engagement-panel-section-list-renderer[target-id*='transcript'] ytd-transcript-segment-renderer yt-formatted-string",
      "ytd-engagement-panel-section-list-renderer[target-id*='transcript'] .segment-text",
      "ytd-engagement-panel-section-list-renderer[target-id*='transcript'] .cue",
      "ytd-engagement-panel-section-list-renderer[target-id*='transcript'] yt-formatted-string",
      "transcript-segment-view-model .segment-text",
      "transcript-segment-view-model [role='button']",
      ".ytd-transcript-segment-list-renderer .segment-text",
      "ytd-transcript-segment-renderer",
      "transcript-segment-view-model",
      ".segment-text",
      ".cue"
    ];
    const lines = [];
    for (const selector of segmentSelectors) {
      const nodes = querySelectorAllDeep(selector);
      if (!nodes.length) {
        continue;
      }
      for (const node of nodes) {
        // 如果节点本身很大，尝试只抓取内部文本节点
        const text = normalizeWhitespace(node.innerText || node.textContent);
        if (text && !isLikelyTimestamp(text)) {
          lines.push(text);
        }
      }
      if (lines.length > 5) {
        break;
      }
    }
    if (!lines.length) {
      const modernSegments = extractYouTubeTranscriptFromModernSegments();
      if (modernSegments) {
        return modernSegments;
      }
    }
    if (!lines.length) {
      const byTimestampBlocks = extractYouTubeTranscriptFromTimestampBlocks();
      if (byTimestampBlocks) {
        return byTimestampBlocks;
      }
    }
    
    const result = normalizeWhitespace(dedupeTranscriptLines(lines).join("\n"));
    if (result.length > 20) {
      return result;
    }

    // 最后的绝招：如果不包含特定的选择器，但有可见的 ytd-transcript-segment-renderer，直接提取 innerText
    traceExtraction("所有精确选择器失效，尝试通用段落提取");
    const allSegments = querySelectorAllDeep("ytd-transcript-segment-renderer, transcript-segment-view-model, .ytd-transcript-segment-renderer");
    if (allSegments.length > 0) {
      const fallbackLines = [];
      for (const seg of allSegments) {
        if (isVisibleElement(seg)) {
          const text = normalizeWhitespace(seg.innerText || seg.textContent);
          if (text && !isLikelyTimestamp(text)) {
            fallbackLines.push(text);
          }
        }
      }
      const fallbackResult = normalizeWhitespace(dedupeTranscriptLines(fallbackLines).join("\n"));
      if (fallbackResult.length > 20) {
        traceExtraction(`通用段落提取成功，长度: ${fallbackResult.length}`);
        return fallbackResult;
      }
    }

    return "";
  }

  function isLikelyTimestamp(text) {
    return /^(\d{1,2}:)?\d{1,2}:\d{2}$/.test(text.trim());
  }

  function collectVisibleTranscriptContainers() {
    const selectors = [
      "ytd-transcript-search-panel-renderer",
      "ytd-engagement-panel-section-list-renderer[target-id*='transcript']",
      "ytd-engagement-panel-section-list-renderer[target-id='PAmodern_transcript_view']"
    ];
    const containers = [];
    for (const selector of selectors) {
      for (const node of querySelectorAllDeep(selector)) {
        if (!isVisibleElement(node)) {
          continue;
        }
        const text = normalizeWhitespace(node.textContent || "");
        if (!text) {
          continue;
        }
        const timestampMatches = text.match(/(?:^|\s)(?:\d{1,2}:)?\d{1,2}:\d{2}(?=\s|$)/g) || [];
        if (timestampMatches.length >= 2) {
          containers.push(node);
        }
      }
    }
    return containers;
  }

  function collectTextNodesFromRoot(root, output) {
    if (!root || !root.createTreeWalker) {
      return;
    }
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let node = walker.nextNode();
    while (node) {
      output.push(node);
      node = walker.nextNode();
    }
  }

  function getDeepTextNodes() {
    const nodes = [];
    for (const root of getSearchRoots()) {
      collectTextNodesFromRoot(root, nodes);
    }
    return nodes;
  }

  function cleanTranscriptLine(line) {
    const normalized = normalizeWhitespace(line);
    if (!normalized) {
      return "";
    }
    const lower = normalized.toLowerCase();
    const skipFragments = [
      "在此视频中",
      "转写文稿",
      "内容转文字",
      "chapters",
      "chapter",
      "search in video",
      "在视频中搜索",
      "搜索",
      "英语",
      "english",
      "show transcript",
      "open transcript"
    ];
    if (skipFragments.some((fragment) => lower === fragment || lower.includes(fragment))) {
      return "";
    }
    if (isLikelyTimestamp(normalized)) {
      return "";
    }
    if (
      /^\d+\s*(seconds?|second|secs?|sec|秒钟|秒)$/.test(lower) ||
      /^(?:\d+\s*(?:hours?|hour|hrs?|hr|小时)\s*)?(?:\d+\s*(?:minutes?|minute|mins?|min|分钟)\s*)?(?:\d+\s*(?:seconds?|second|secs?|sec|秒钟|秒))$/.test(lower)
    ) {
      return "";
    }
    return normalized;
  }

  /**
   * 兼容新版 YouTube transcript 面板。
   *
   * 新版页面不会渲染 `ytd-transcript-segment-renderer`，而是使用
   * `transcript-segment-view-model`。每个节点文本通常形如：
   * `0:10\n10秒钟\n实际字幕内容`
   *
   * 这里会移除前置时间戳/时长提示，只保留真正的字幕正文。
   *
   * @returns {string}
   */
  function extractYouTubeTranscriptFromModernSegments() {
    const nodes = querySelectorAllDeep("transcript-segment-view-model, ytd-transcript-segment-renderer, .ytd-transcript-segment-renderer");
    if (!nodes.length) {
      return "";
    }

    const lines = [];
    for (const node of nodes) {
      if (!isVisibleElement(node)) {
        continue;
      }

      // 优先抓取特定的文本类或属性
      const textContainer = node.querySelector(".segment-text, .cue, [role='button'], yt-formatted-string, span");
      const rawText = textContainer ? textContainer.innerText : (node.innerText || node.textContent);
      
      const rawLines = normalizeWhitespace(rawText || "")
        .split("\n")
        .map((line) => normalizeWhitespace(line))
        .filter(Boolean);

      if (!rawLines.length) {
        continue;
      }

      const contentLines = rawLines.filter((line, index) => {
        // 过滤掉时间戳
        if (isLikelyTimestamp(line)) {
          return false;
        }
        // 过滤掉纯数字（有时是序号）
        if (/^\d+$/.test(line)) {
          return false;
        }
        return Boolean(cleanTranscriptLine(line));
      });

      const content = normalizeWhitespace(contentLines.join(" "));
      if (content) {
        lines.push(content);
      }
    }

    const result = normalizeWhitespace(dedupeTranscriptLines(lines).join("\n"));
    return result.length > 20 ? result : "";
  }

  function extractYouTubeTranscriptFromTimestampBlocks() {
    const containers = collectVisibleTranscriptContainers();
    for (const container of containers) {
      const rawLines = normalizeWhitespace(container.innerText || container.textContent || "")
        .split("\n")
        .map((line) => normalizeWhitespace(line))
        .filter(Boolean);
      if (!rawLines.length) {
        continue;
      }

      const result = [];
      let buffer = [];

      const flushBuffer = () => {
        const text = normalizeWhitespace(buffer.join(" "));
        if (text && result[result.length - 1] !== text) {
          result.push(text);
        }
        buffer = [];
      };

      for (const rawLine of rawLines) {
        const line = normalizeWhitespace(rawLine);
        if (!line) {
          continue;
        }
        if (isLikelyTimestamp(line)) {
          flushBuffer();
          continue;
        }
        const cleaned = cleanTranscriptLine(line);
        if (!cleaned) {
          continue;
        }
        buffer.push(cleaned);
      }
      flushBuffer();

      const transcript = normalizeWhitespace(result.join("\n"));
      if (transcript && transcript.length >= 40) {
        return transcript;
      }
    }
    return "";
  }

  function extractYouTubeTranscriptFromPanelText() {
    const panel = querySelectorDeep(
      [
        "ytd-transcript-search-panel-renderer",
        "ytd-engagement-panel-section-list-renderer[target-id*='transcript']",
        "ytd-engagement-panel-section-list-renderer[target-id='PAmodern_transcript_view']"
      ].join(", ")
    );
    if (!panel) {
      return "";
    }
    const rawLines = normalizeWhitespace(panel.textContent || "")
      .split("\n")
      .map((line) => normalizeWhitespace(line))
      .filter(Boolean);

    const result = [];
    for (const line of rawLines) {
      const cleaned = cleanTranscriptLine(line);
      if (cleaned && result[result.length - 1] !== cleaned) {
        result.push(cleaned);
      }
    }
    return normalizeWhitespace(dedupeTranscriptLines(result).join("\n"));
  }

  function decodeHtmlEntities(text) {
    const textarea = document.createElement("textarea");
    textarea.innerHTML = String(text || "");
    return textarea.value;
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

  function extractBalancedJson(source, startIndex) {
    return extractBalancedBlock(source, startIndex, "{", "}");
  }

  function extractBalancedJsonArray(source, startIndex) {
    return extractBalancedBlock(source, startIndex, "[", "]");
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
    const rawJson = extractBalancedJson(source, braceIndex);
    if (!rawJson) {
      return null;
    }
    try {
      return JSON.parse(rawJson);
    } catch (_error) {
      return null;
    }
  }

  function extractCaptionTracksFromPlayerResponse(playerResponse) {
    const tracks = playerResponse?.captions?.playerCaptionsTracklistRenderer?.captionTracks;
    if (Array.isArray(tracks) && tracks.length) {
      return tracks;
    }
    return [];
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
      const tracks = extractCaptionTracksFromPlayerResponse(playerResponse);
      if (tracks.length) {
        return tracks;
      }
    }

    const captionTrackKeys = ["\"captionTracks\":", "\"captionTracks\" :"];
    for (const key of captionTrackKeys) {
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
        const rawArray = extractBalancedJsonArray(source, arrayStart);
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
          // Continue searching next occurrence.
        }
        searchIndex = arrayStart + rawArray.length;
      }
    }

    return [];
  }

  async function fetchCurrentPageHtml() {
    try {
      const resp = await fetch(location.href, {
        credentials: "include",
        cache: "no-store"
      });
      if (!resp.ok) {
        return "";
      }
      return await resp.text();
    } catch (_error) {
      return "";
    }
  }

  /**
   * 在页面原生上下文中读取 YouTube 的播放器响应。
   *
   * Content script 运行在隔离环境里，直接访问 `window.ytInitialPlayerResponse`
   * 这类页面全局对象并不稳定，所以这里通过注入脚本桥接回真实页面上下文。
   *
   * @returns {Promise<Array<object>>}
   */
  async function getYouTubeCaptionTracksFromPageContext() {
    const eventName = `yt_caption_tracks_${Date.now()}_${Math.random().toString(16).slice(2)}`;

    return new Promise((resolve) => {
      let settled = false;

      const finalize = (tracks) => {
        if (settled) {
          return;
        }
        settled = true;
        window.removeEventListener(eventName, handleEvent);
        resolve(Array.isArray(tracks) ? tracks : []);
      };

      const handleEvent = (event) => {
        const detail = event?.detail || {};
        finalize(detail.tracks);
      };

      window.addEventListener(eventName, handleEvent, { once: true });

      const script = document.createElement("script");
      script.textContent = `
        (() => {
          const eventName = ${JSON.stringify(eventName)};
          const emit = (tracks) => {
            window.dispatchEvent(new CustomEvent(eventName, {
              detail: { tracks: Array.isArray(tracks) ? tracks : [] }
            }));
          };
          const parseMaybeJson = (value) => {
            if (!value) return null;
            if (typeof value === "object") return value;
            try { return JSON.parse(value); } catch (e) { return null; }
          };

          try {
            const candidates = [];
            candidates.push(window.ytInitialPlayerResponse);
            candidates.push(parseMaybeJson(window?.ytplayer?.config?.args?.player_response));
            candidates.push(parseMaybeJson(window?.ytcfg?.data_?.PLAYER_VARS?.player_response));
            if (typeof window?.ytcfg?.get === "function") {
              candidates.push(parseMaybeJson(window.ytcfg.get("PLAYER_VARS")?.player_response));
              candidates.push(parseMaybeJson(window.ytcfg.get("PLAYER_RESPONSE")));
              candidates.push(parseMaybeJson(window.ytcfg.get("ytInitialPlayerResponse")));
            }
            const moviePlayer = document.getElementById("movie_player");
            if (moviePlayer && typeof moviePlayer.getPlayerResponse === "function") {
              candidates.push(moviePlayer.getPlayerResponse());
            }

            for (const candidate of candidates) {
              const tracks = candidate?.captions?.playerCaptionsTracklistRenderer?.captionTracks;
              if (Array.isArray(tracks) && tracks.length) {
                emit(tracks);
                return;
              }
            }
          } catch (_error) {}

          emit([]);
        })();
      `;

      const parent = document.documentElement || document.head || document.body;
      if (!parent) {
        finalize([]);
        return;
      }

      parent.appendChild(script);
      script.remove();
      window.setTimeout(() => finalize([]), 1200);
    });
  }

  let cachedYouTubeCaptionTracks = null;
  let cachedYouTubeCaptionTracksUrl = "";

  async function getYouTubeCaptionTracks() {
    const currentUrl = location.href;
    if (
      Array.isArray(cachedYouTubeCaptionTracks) &&
      cachedYouTubeCaptionTracks.length &&
      cachedYouTubeCaptionTracksUrl === currentUrl
    ) {
      return cachedYouTubeCaptionTracks;
    }

    const pageContextTracks = await getYouTubeCaptionTracksFromPageContext();
    if (pageContextTracks.length) {
      cachedYouTubeCaptionTracks = pageContextTracks;
      cachedYouTubeCaptionTracksUrl = currentUrl;
      return pageContextTracks;
    }

    const scriptNodes = Array.from(document.scripts || []);
    for (const scriptNode of scriptNodes) {
      const tracks = extractCaptionTracksFromSource(scriptNode.textContent || "");
      if (tracks.length) {
        cachedYouTubeCaptionTracks = tracks;
        cachedYouTubeCaptionTracksUrl = currentUrl;
        return tracks;
      }
    }

    const htmlSource = await fetchCurrentPageHtml();
    const htmlTracks = extractCaptionTracksFromSource(htmlSource);
    if (htmlTracks.length) {
      cachedYouTubeCaptionTracks = htmlTracks;
      cachedYouTubeCaptionTracksUrl = currentUrl;
      return htmlTracks;
    }

    return [];
  }

  function hasVisibleYouTubeTranscriptPanel() {
    return Boolean(
      querySelectorDeep("ytd-transcript-segment-renderer .segment-text") ||
      querySelectorDeep("ytd-transcript-segment-renderer .cue") ||
      querySelectorDeep("ytd-engagement-panel-section-list-renderer[target-id*='transcript'] .segment-text") ||
      querySelectorDeep("ytd-engagement-panel-section-list-renderer[target-id*='transcript'] .cue") ||
      querySelectorDeep("transcript-segment-view-model") ||
      collectVisibleTranscriptContainers().length > 0
    );
  }

  function hasPotentialTranscriptButton() {
    const patterns = ["show transcript", "open transcript", "transcript", "显示文字稿", "显示转录稿", "转录稿", "文字稿", "转写文稿", "内容转文字"];
    return Boolean(findClickableByText(patterns));
  }

  function parseYouTubeXmlTranscript(xmlText) {
    try {
      const parser = new DOMParser();
      const xml = parser.parseFromString(xmlText, "text/xml");
      const textNodes = Array.from(xml.getElementsByTagName("text"));
      const lines = dedupeTranscriptLines(textNodes
        .map((node) => decodeHtmlEntities(node.textContent || ""))
        .map((line) => normalizeWhitespace(line))
        .filter(Boolean));
      return normalizeWhitespace(lines.join("\n"));
    } catch (_error) {
      return "";
    }
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

  async function fetchYouTubeCaptionTrack(track) {
    const baseUrl = String(track?.baseUrl || "").trim();
    if (!baseUrl) {
      return "";
    }

    const candidates = [];
    try {
      const jsonUrl = new URL(baseUrl, location.origin);
      jsonUrl.searchParams.set("fmt", "json3");
      candidates.push(jsonUrl.toString());
    } catch (_error) {
      // ignore malformed URL, fallback to original
    }
    candidates.push(baseUrl);

    for (const candidate of candidates) {
      try {
        const resp = await fetch(candidate, { credentials: "include" });
        if (!resp.ok) {
          continue;
        }
        const rawText = await resp.text();
        const trimmed = rawText.trim();
        if (!trimmed) {
          continue;
        }
        if (trimmed.startsWith("{")) {
          const payload = JSON.parse(trimmed);
          const transcript = parseYouTubeJsonTranscript(payload);
          if (transcript) {
            return transcript;
          }
        }
        const transcript = parseYouTubeXmlTranscript(trimmed);
        if (transcript) {
          return transcript;
        }
      } catch (_error) {
        // try next candidate
      }
    }
    return "";
  }

  async function extractYouTubeTranscriptFromData() {
    for (let attempt = 0; attempt < 3; attempt += 1) {
      const tracks = await getYouTubeCaptionTracks();
      if (tracks.length) {
        const sortedTracks = [...tracks].sort((a, b) => {
          const aPenalty = a?.kind === "asr" ? 1 : 0;
          const bPenalty = b?.kind === "asr" ? 1 : 0;
          return aPenalty - bPenalty;
        });
        for (const track of sortedTracks) {
          const transcript = await fetchYouTubeCaptionTrack(track);
          if (transcript) {
            return transcript;
          }
        }
      }
      cachedYouTubeCaptionTracks = null;
      cachedYouTubeCaptionTracksUrl = "";
      await sleep(600);
    }
    return "";
  }

  function clearYouTubeExtractionCacheIfUrlChanged() {
    if (cachedYouTubeCaptionTracksUrl && cachedYouTubeCaptionTracksUrl !== location.href) {
      cachedYouTubeCaptionTracks = null;
      cachedYouTubeCaptionTracksUrl = "";
    }
  }

  function isYouTubeWatchPage() {
    return location.host.includes("youtube.com") && (location.pathname === "/watch" || location.pathname.startsWith("/live/"));
  }

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (!message || message.action !== "extractTranscript") {
      return;
    }
    clearYouTubeExtractionCacheIfUrlChanged();
    (async () => {
      const host = location.host;
      const title = getTitle();
      let transcript = "";
      let platform = "unknown";
      let helperMessage = "";
      let detailedError = "";
      const extractionLogs = [];

      const log = (msg) => {
        const time = new Date().toLocaleTimeString();
        extractionLogs.push(`[${time}] ${msg}`);
      };
      setExtractionLogger(log);
      try {
        if (host.includes("youtube.com")) {
          platform = "youtube";
          log("开始 YouTube 提取流程");

          const tracks = await getYouTubeCaptionTracks();
          log(`获取到 captionTracks 数量: ${tracks.length}`);

          transcript = await extractYouTubeTranscriptFromData();
          if (transcript) {
            log(`成功从内嵌数据提取文本，长度: ${transcript.length}`);
            helperMessage = "已优先从 YouTube 页面内嵌字幕数据中提取 transcript。";
          }

          if (!transcript) {
            log("尝试从页面 DOM 直接提取");
            transcript = extractYouTubeTranscript();
            if (transcript) {
              log(`成功从页面 DOM 提取文本，长度: ${transcript.length}`);
            }
          }

          if (!transcript) {
            log("尝试自动展开 YouTube transcript 面板");
            const ensureResult = await ensureYouTubeTranscriptVisible();
            log(`展开面板结果: ${ensureResult.ok ? "成功" : "失败"}, autoOpened: ${ensureResult.autoOpened}`);

            transcript = extractYouTubeTranscript();
            if (ensureResult.autoOpened) {
              helperMessage = "已自动尝试展开 YouTube transcript 面板。";
            }
            if (transcript) {
              log(`展开面板后成功提取文本，长度: ${transcript.length}`);
            }
          }

          if (transcript && transcript.length < 50) {
            log(`提取到的文本过短 (${transcript.length})，可能提取到了错误的容器，重置 transcript`);
            transcript = "";
          }

          if (!transcript && tracks.length === 0 && !hasVisibleYouTubeTranscriptPanel() && !hasPotentialTranscriptButton()) {
            log("未发现任何字幕来源 (无 tracks, 无面板, 无按钮)");
            detailedError = isYouTubeWatchPage()
              ? "当前视频页未发现可直接读取的 YouTube transcript / captionTracks。请先确认该视频是否真的开放了平台字幕，若页面肉眼可见 transcript 但扩展仍失败，说明是页面结构差异，需要继续补适配。"
              : "当前页面疑似不是标准 YouTube 视频详情页，暂时无法稳定读取 transcript。";
          } else if (!transcript) {
            log("所有提取尝试均告失败");
          }
        } else if (host.includes("bilibili.com") || host.includes("b23.tv")) {
          platform = "bilibili";
          log("开始 Bilibili 提取流程");
          transcript = extractBilibiliTranscript();
          if (transcript) {
            log("成功提取 Bilibili 字幕");
          } else {
            log("未能提取 Bilibili 字幕");
          }
        }

        const detection = {
          hasText: !!transcript,
          extractionLogs: extractionLogs
        };

        if (!transcript) {
          sendResponse({
            ok: false,
            platform,
            title,
            url: location.href,
            transcript: "",
            helperMessage,
            error: detailedError || "当前页面未提取到可见字幕。YouTube 已自动尝试展开面板但仍未成功。请确认视频确实开启了字幕，或手动尝试刷新页面后再试。",
            detection
          });
          return;
        }

        sendResponse({
          ok: true,
          platform,
          title,
          url: location.href,
          transcript,
          helperMessage,
          detection
        });
      } catch (error) {
        log(`提取流程异常: ${String(error?.message || error || "unknown_error")}`);
        sendResponse({
          ok: false,
          platform,
          title,
          url: location.href,
          transcript: "",
          helperMessage,
          error: String(error?.message || error || "content_script_extract_exception"),
          detection: {
            hasText: false,
            extractionLogs
          }
        });
      } finally {
        setExtractionLogger(null);
      }
    })();
    return true;
  });

  const handledPageFlowRequests = new Set();

  function replyEnvelope(requestId, replyPayload) {
    return {
      namespace: PAGE_REQUEST_NAMESPACE,
      action: "summarizeFlowReply",
      requestId,
      payload: replyPayload
    };
  }

  function postReplyToKnownWindows(requestId, replyPayload, targetWindow) {
    const envelope = replyEnvelope(requestId, replyPayload);
    const notified = new Set();

    const tryPost = (target) => {
      if (!target || typeof target.postMessage !== "function" || notified.has(target)) {
        return;
      }
      notified.add(target);
      try {
        target.postMessage(envelope, "*");
      } catch (_error) {
        // Ignore cross-window delivery issues and continue broadcasting.
      }
    };

    tryPost(targetWindow);
    tryPost(window);
    tryPost(window.top);

    try {
      for (let i = 0; i < window.frames.length; i += 1) {
        tryPost(window.frames[i]);
      }
    } catch (_error) {
      // Ignore frame enumeration issues.
    }

    if (broadcastChannel) {
      try {
        broadcastChannel.postMessage(envelope);
      } catch (_error) {
        // Ignore broadcast failures.
      }
    }
  }

  function handlePageFlowRequest(requestId, payload, targetWindow, receivedStage) {
    const normalizedRequestId = String(requestId || "").trim();
    if (!normalizedRequestId || handledPageFlowRequests.has(normalizedRequestId)) {
      return;
    }
    handledPageFlowRequests.add(normalizedRequestId);

    const attempts = [
      {
        stage: receivedStage,
        ok: true,
        requestId: normalizedRequestId,
        sourceUrl: String(payload?.sourceUrl || "").trim()
      }
    ];

    attempts.push({
      stage: "content_script_send_runtime_message",
      ok: true
    });
    chrome.runtime.sendMessage(
      {
        action: "startSummarizeFlowFromPage",
        payload
      },
      (response) => {
        const runtimeError = chrome.runtime.lastError;
        let replyPayload;

        if (runtimeError) {
          attempts.push({
            stage: "content_script_runtime_callback",
            ok: false,
            error: String(runtimeError.message || "runtime_message_failed")
          });
          replyPayload = {
            ok: false,
            error: String(runtimeError.message || "runtime_message_failed"),
            debug: { attempts: [...attempts] }
          };
        } else {
          attempts.push({
            stage: "content_script_runtime_callback",
            ok: true,
            error: String(response?.error || "")
          });
          replyPayload = {
            ...(response || { ok: false, error: "empty_background_response" }),
            debug: {
              ...((response && response.debug && typeof response.debug === "object") ? response.debug : {}),
              attempts: [
                ...attempts,
                ...((((response && response.debug) || {}).attempts) instanceof Array ? response.debug.attempts : [])
              ]
            }
          };
        }

        attempts.push({
          stage: "content_script_post_reply_to_bridge",
          ok: true
        });
        postReplyToKnownWindows(normalizedRequestId, replyPayload, targetWindow);

        attempts.push({
          stage: "content_script_write_storage_reply",
          ok: true
        });
        if (replyPayload.debug && typeof replyPayload.debug === "object") {
          replyPayload.debug.attempts = [
            ...attempts,
            ...((Array.isArray(replyPayload.debug.attempts) ? replyPayload.debug.attempts : []).filter(Boolean))
          ];
        }
        writePageFlowStorageResponse(normalizedRequestId, replyPayload);
      }
    );
  }

  function pollPageFlowStorageRequests() {
    for (const store of [window.localStorage, window.sessionStorage]) {
      let keys = [];
      try {
        keys = Array.from({ length: store.length }, (_, index) => store.key(index)).filter(Boolean);
      } catch (_error) {
        continue;
      }

      for (const key of keys) {
        if (!String(key).startsWith(PAGE_REQUEST_STORAGE_PREFIX)) {
          continue;
        }
        const payload = parseJsonSafely(store.getItem(key));
        if (!payload || payload.namespace !== PAGE_REQUEST_NAMESPACE || payload.action !== "startSummarizeFlowFromPage") {
          continue;
        }
        consumePageFlowStorageRequest(key);
        handlePageFlowRequest(payload.requestId, payload.payload || {}, null, "content_script_received_storage_request");
      }
    }
  }

  window.addEventListener("message", (event) => {
    const data = event && event.data;
    if (!data || data.namespace !== PAGE_REQUEST_NAMESPACE) {
      return;
    }
    if (data.action !== "startSummarizeFlowFromPage") {
      return;
    }
    handlePageFlowRequest(data.requestId, data.payload || {}, event.source, "content_script_received_bridge_request");
  });

  if (broadcastChannel) {
    broadcastChannel.addEventListener("message", (event) => {
      const data = event && event.data;
      if (!data || data.namespace !== PAGE_REQUEST_NAMESPACE) {
        return;
      }
      if (data.action !== "startSummarizeFlowFromPage") {
        return;
      }
      handlePageFlowRequest(data.requestId, data.payload || {}, null, "content_script_received_broadcast_request");
    });
  }

  window.setInterval(pollPageFlowStorageRequests, 350);

  function findClickableByText(patterns) {
    const nodes = querySelectorAllDeep('button, [role="button"], tp-yt-paper-item, ytd-menu-service-item-renderer');
    for (const node of nodes) {
      const text = normalizeWhitespace(node.textContent).toLowerCase();
      if (!text) {
        continue;
      }
      if (patterns.some((pattern) => text.includes(pattern))) {
        return node.closest('button, [role="button"], tp-yt-paper-item, ytd-menu-service-item-renderer') || node;
      }
    }
    return null;
  }

  function isVisibleElement(node) {
    if (!node) {
      return false;
    }
    const rect = node.getBoundingClientRect();
    const style = window.getComputedStyle(node);
    return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none";
  }

  function findYouTubeMoreActionsButton() {
    const candidates = querySelectorAllDeep("button, [role='button']");
    const labels = [
      "more actions",
      "更多操作",
      "更多",
      "actions"
    ];

    for (const node of candidates) {
      const aria = String(node.getAttribute("aria-label") || "").toLowerCase();
      const title = String(node.getAttribute("title") || "").toLowerCase();
      const tooltip = String(node.getAttribute("data-tooltip-text") || "").toLowerCase();
      const text = normalizeWhitespace(node.textContent).toLowerCase();
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
  }

  async function clickNode(node) {
    if (!node) {
      return false;
    }
    node.click();
    await sleep(700);
    return true;
  }

  async function ensureYouTubeTranscriptVisible() {
    if (extractYouTubeTranscript()) {
      return { ok: true, autoOpened: false };
    }

    const directTranscriptButton = findClickableByText([
      "show transcript",
      "open transcript",
      "transcript",
      "显示文字稿",
      "显示转录稿",
      "转录稿",
      "文字稿",
      "转写文稿",
      "内容转文字"
    ]);
    if (await clickNode(directTranscriptButton)) {
      for (let i = 0; i < 5; i += 1) {
        await sleep(800);
        if (extractYouTubeTranscript()) {
          return { ok: true, autoOpened: true };
        }
      }
    }

    const moreActionsButton = findYouTubeMoreActionsButton();
    if (await clickNode(moreActionsButton)) {
      const menuTranscriptButton = findClickableByText([
        "show transcript",
        "open transcript",
        "显示文字稿",
        "显示转录稿",
        "转录稿",
        "文字稿",
        "转写文稿",
        "内容转文字"
      ]);
      if (await clickNode(menuTranscriptButton)) {
        for (let i = 0; i < 6; i += 1) {
          await sleep(900);
          if (extractYouTubeTranscript()) {
            return { ok: true, autoOpened: true };
          }
        }
      }
    }

    const transcriptTabButton = findClickableByText([
      "transcript",
      "转写文稿",
      "内容转文字",
      "文字稿",
      "转录稿"
    ]);
    if (await clickNode(transcriptTabButton)) {
      for (let i = 0; i < 6; i += 1) {
        await sleep(700);
        if (extractYouTubeTranscript()) {
          return { ok: true, autoOpened: true };
        }
      }
    }

    return { ok: false, autoOpened: false };
  }

  function extractBilibiliTranscript() {
    const selectors = [
      ".bpx-player-subtitle-panel-text",
      ".bcc-subtitle-row",
      ".subtitle-item-text",
      ".bui-collapse-wrap .text",
      ".bpx-player-subtitle-wrap .bpx-player-subtitle-item-text",
      ".bpx-player-ctrl-subtitle-item-text",
      "[class*='subtitle'] [class*='text']"
    ];
    const lines = [];
    for (const selector of selectors) {
      const nodes = Array.from(document.querySelectorAll(selector));
      if (!nodes.length) {
        continue;
      }
      for (const node of nodes) {
        const text = normalizeWhitespace(node.textContent);
        if (text) {
          lines.push(text);
        }
      }
      if (lines.length) {
        break;
      }
    }
    return normalizeWhitespace(lines.join("\n"));
  }
})();
