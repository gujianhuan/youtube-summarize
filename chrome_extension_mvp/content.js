(function () {
  const extensionApi = globalThis.browser || globalThis.chrome;
  const PAGE_REQUEST_NAMESPACE = "yt-summary-page-request";
  const PAGE_REQUEST_STORAGE_PREFIX = "yt-summary-page-request:";
  const PAGE_RESPONSE_STORAGE_PREFIX = "yt-summary-page-response:";
  const BROADCAST_CHANNEL_NAME = "yt-summary-broadcast-channel";
  const DEBUG_SERVER_URL = "http://127.0.0.1:7777/event";
  const DEBUG_SESSION_ID = "youtube-plugin-extract";
  const DEBUG_RUN_ID = `post-fix-${extensionApi?.runtime?.getManifest?.().version || "0.1.64"}`;
  const TRANSCRIPT_BUTTON_PATTERNS = [
    "show transcript",
    "open transcript",
    "transcript",
    "显示文字稿",
    "显示字幕",
    "文字稿",
    "字幕",
    "转写文本",
    "内容转写",
    "内容转文字",
    "顯示轉錄稿",
    "顯示文字稿",
    "轉錄稿",
    "逐字稿",
    "開啟轉錄稿",
    "內容轉文字"
  ];

  function reportContentBootstrap(msg, data = {}) {
    fetch(DEBUG_SERVER_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        sessionId: DEBUG_SESSION_ID,
        runId: DEBUG_RUN_ID,
        hypothesisId: "B",
        location: "content.js",
        msg: `[DEBUG] ${msg}`,
        data,
        ts: Date.now()
      })
    }).catch(() => {});
  }

  let broadcastChannel = null;
  try {
    if (typeof window.BroadcastChannel === "function") {
      broadcastChannel = new window.BroadcastChannel(BROADCAST_CHANNEL_NAME);
    }
  } catch (error) {
    reportContentBootstrap("content bootstrap broadcast channel failed", {
      message: String(error?.message || error || "unknown"),
      href: String(location.href || "")
    });
  }

  function parseYouTubeVideoId(url) {
    try {
      const parsed = new URL(String(url || ""));
      const host = String(parsed.hostname || "").toLowerCase();
      if (host.includes("youtu.be")) {
        return parsed.pathname.replace(/^\/+/, "").split(/[/?#]/)[0].trim();
      }
      const watchId = parsed.searchParams.get("v") || "";
      if (watchId) {
        return watchId.trim();
      }
      const pathParts = parsed.pathname.split("/").filter(Boolean);
      if (pathParts.length >= 2 && ["shorts", "live", "embed"].includes(pathParts[0])) {
        return pathParts[1].trim();
      }
      return "";
    } catch (_error) {
      return "";
    }
  }

  function isCurrentYouTubePageForSource(sourceUrl) {
    const currentVideoId = parseYouTubeVideoId(location.href);
    if (!currentVideoId) {
      return true;
    }
    const targetVideoId = parseYouTubeVideoId(sourceUrl);
    return Boolean(targetVideoId && currentVideoId === targetVideoId);
  }

  function getRuntimeLastError() {
    return globalThis.chrome?.runtime?.lastError || extensionApi?.runtime?.lastError || null;
  }

  function callExtensionApi(apiFunction, context, ...args) {
    return new Promise((resolve, reject) => {
      let settled = false;
      const done = (error, result) => {
        if (settled) {
          return;
        }
        settled = true;
        if (error) {
          reject(error instanceof Error ? error : new Error(String(error)));
          return;
        }
        resolve(result);
      };

      if (globalThis.browser) {
        try {
          const maybePromise = apiFunction.apply(context, args);
          if (maybePromise && typeof maybePromise.then === "function") {
            maybePromise.then(
              (result) => done(null, result),
              (error) => done(error, null),
            );
            return;
          }
        } catch (_error) {
          // Fall through to callback-style invocation for Chromium APIs.
        }
      }

      try {
        apiFunction.apply(context, [
          ...args,
          (result) => {
            const runtimeError = getRuntimeLastError();
            if (runtimeError) {
              done(new Error(runtimeError.message || String(runtimeError)));
              return;
            }
            done(null, result);
          }
        ]);
      } catch (error) {
        done(error, null);
      }
    });
  }

  function sendRuntimeMessage(message) {
    return callExtensionApi(extensionApi.runtime.sendMessage, extensionApi.runtime, message);
  }

  function sleep(ms) {
    return new Promise((resolve) => window.setTimeout(resolve, ms));
  }

  // #region debug-point B:content-report
  function reportContentDebug(hypothesisId, msg, data = {}) {
    fetch(DEBUG_SERVER_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        sessionId: DEBUG_SESSION_ID,
        runId: DEBUG_RUN_ID,
        hypothesisId,
        location: "content.js",
        msg: `[DEBUG] ${msg}`,
        data,
        ts: Date.now()
      })
    }).catch(() => {});
  }
  // #endregion

  reportContentBootstrap("content bootstrap ready", {
    href: String(location.href || ""),
    hasBroadcastChannel: Boolean(broadcastChannel),
    readyState: String(document.readyState || "")
  });

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

  function getNodeSearchableText(node) {
    if (!node || typeof node !== "object") {
      return "";
    }
    const fragments = [
      node.textContent,
      node.innerText,
      node.getAttribute?.("aria-label"),
      node.getAttribute?.("title"),
      node.getAttribute?.("data-tooltip-text"),
      node.getAttribute?.("aria-description"),
      node.getAttribute?.("aria-roledescription")
    ];
    return normalizeWhitespace(fragments.filter(Boolean).join(" | ")).toLowerCase();
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

  function isLoopbackPageOrigin(value) {
    const text = String(value || "").trim();
    if (!text) {
      return false;
    }
    try {
      const parsed = new URL(text);
      return ["127.0.0.1", "localhost"].includes(String(parsed.hostname || "").toLowerCase());
    } catch (_error) {
      return /^https?:\/\/(?:127\.0\.0\.1|localhost)(?::\d+)?(?:\/|$)/i.test(text);
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
        // 濡傛灉鑺傜偣鏈韩寰堝ぇ锛屽皾璇曞彧鎶撳彇鍐呴儴鏂囨湰鑺傜偣
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

    const panelTextTranscript = extractYouTubeTranscriptFromPanelText();
    if (panelTextTranscript.length > 20) {
      traceExtraction(`transcript_panel_text_fallback_success:length=${panelTextTranscript.length}`);
      return panelTextTranscript;
    }

    // 鏈€鍚庣殑缁濇嫑锛氬鏋滀笉鍖呭惈鐗瑰畾鐨勯€夋嫨鍣紝浣嗘湁鍙鐨?ytd-transcript-segment-renderer锛岀洿鎺ユ彁鍙?innerText
    traceExtraction("鎵€鏈夌簿纭€夋嫨鍣ㄥけ鏁堬紝灏濊瘯閫氱敤娈佃惤鎻愬彇");
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
        traceExtraction(`閫氱敤娈佃惤鎻愬彇鎴愬姛锛岄暱搴? ${fallbackResult.length}`);
        return fallbackResult;
      }
    }

    return "";
  }

  function isPlausibleTranscriptText(text) {
    const normalized = normalizeWhitespace(text);
    if (!normalized) {
      return false;
    }
    if (normalized.length >= 50) {
      return true;
    }
    const lines = normalized.split("\n").map((line) => normalizeWhitespace(line)).filter(Boolean);
    if (lines.length >= 2) {
      return true;
    }
    const compact = normalized.replace(/\s+/g, "");
    return compact.length >= 12;
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
    let normalized = normalizeWhitespace(line);
    if (!normalized) {
      return "";
    }
    // New transcript-segment-view-model nodes often flatten timestamp + duration + content into one line.
    for (let i = 0; i < 2; i += 1) {
      normalized = normalizeWhitespace(
        normalized
          .replace(/^(?:\d{1,2}:)?\d{1,2}:\d{2}\s*/i, "")
          .replace(/^(?:\d+\s*(?:hours?|hour|hrs?|hr|\u5c0f\u65f6)\s*)?(?:\d+\s*(?:minutes?|minute|mins?|min|\u5206\u949f)\s*)?(?:\d+\s*(?:seconds?|second|secs?|sec|\u79d2\u949f|\u79d2))?\s*/i, "")
      );
    }
    if (!normalized) {
      return "";
    }
    const lower = normalized.toLowerCase();
    const skipFragments = [
      "在此视频中",
      "转写文本",
      "内容转写",
      "chapters",
      "chapter",
      "search in video",
      "在视频中搜索",
      "搜索",
      "英语",
      "english",
      "show transcript",
      "open transcript",
      "转写文本",
      "内容转写",
      "内容转文字",
      "內容轉文字",
      "轉錄稿",
      "逐字稿"
    ];
    if (skipFragments.some((fragment) => lower === fragment || lower.includes(fragment))) {
      return "";
    }
    if (isLikelyTimestamp(normalized)) {
      return "";
    }
    if (
      /^\d+\s*(?:seconds?|second|secs?|sec|\u79d2\u949f|\u79d2)$/.test(lower) ||
      /^(?:\d+\s*(?:hours?|hour|hrs?|hr|\u5c0f\u65f6)\s*)?(?:\d+\s*(?:minutes?|minute|mins?|min|\u5206\u949f)\s*)?(?:\d+\s*(?:seconds?|second|secs?|sec|\u79d2\u949f|\u79d2))$/.test(lower)
    ) {
      return "";
    }
    return normalized;
  }

  /**
   * 鍏煎鏂扮増 YouTube transcript 闈㈡澘銆?
   *
   * 鏂扮増椤甸潰涓嶄細娓叉煋 `ytd-transcript-segment-renderer`锛岃€屾槸浣跨敤
   * `transcript-segment-view-model`銆傛瘡涓妭鐐规枃鏈€氬父褰㈠锛?
   * `0:10\n10绉掗挓\n瀹為檯瀛楀箷鍐呭`
   *
   * 杩欓噷浼氱Щ闄ゅ墠缃椂闂存埑/鏃堕暱鎻愮ず锛屽彧淇濈暀鐪熸鐨勫瓧骞曟鏂囥€?
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
      const tagName = String(node?.tagName || "").toLowerCase();
      const rawText = node.innerText || node.textContent || "";
      if (!normalizeWhitespace(rawText)) {
        continue;
      }
      const shouldRequireVisible = !tagName.includes("transcript-segment-view-model");
      if (shouldRequireVisible && !isVisibleElement(node)) {
        continue;
      }

      // 浼樺厛鎶撳彇鐗瑰畾鐨勬枃鏈被鎴栧睘鎬?
      const textContainer = node.querySelector(".segment-text, .cue, [role='button'], yt-formatted-string, span");
      const extractedRawText = textContainer ? textContainer.innerText : rawText;
      
      const rawLines = normalizeWhitespace(extractedRawText || "")
        .split("\n")
        .map((line) => normalizeWhitespace(line))
        .filter(Boolean);

      if (!rawLines.length) {
        continue;
      }

      const contentLines = rawLines.filter((line, index) => {
        // 杩囨护鎺夋椂闂存埑
        if (isLikelyTimestamp(line)) {
          return false;
        }
        // 杩囨护鎺夌函鏁板瓧锛堟湁鏃舵槸搴忓彿锛?
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
        if (!line || isLikelyTimestamp(line)) {
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

  function extractStructuredTranscriptFromSource(source) {
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
      const rawArray = extractBalancedJsonArray(source, arrayStart);
      if (!rawArray) {
        searchIndex = markerIndex + cueGroupsKey.length;
        continue;
      }
      try {
        const transcript = extractTranscriptFromCueGroups(JSON.parse(rawArray));
        if (transcript) {
          return transcript;
        }
      } catch (_error) {
        // Continue searching next occurrence.
      }
      searchIndex = arrayStart + rawArray.length;
    }

    return "";
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
   * 鍦ㄩ〉闈㈠師鐢熶笂涓嬫枃涓鍙?YouTube 鐨勬挱鏀惧櫒鍝嶅簲銆?
   *
   * Content script 杩愯鍦ㄩ殧绂荤幆澧冮噷锛岀洿鎺ヨ闂?`window.ytInitialPlayerResponse`
   * 杩欑被椤甸潰鍏ㄥ眬瀵硅薄骞朵笉绋冲畾锛屾墍浠ヨ繖閲岄€氳繃娉ㄥ叆鑴氭湰妗ユ帴鍥炵湡瀹為〉闈笂涓嬫枃銆?
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
      window.setTimeout(() => finalize([]), 2500);
    });
  }

  async function getYouTubeInlineTranscriptFromPageContext() {
    const eventName = `yt_inline_transcript_${Date.now()}_${Math.random().toString(16).slice(2)}`;

    return new Promise((resolve) => {
      let settled = false;

      const finalize = (transcript) => {
        if (settled) {
          return;
        }
        settled = true;
        window.removeEventListener(eventName, handleEvent);
        resolve(typeof transcript === "string" ? transcript : "");
      };

      const handleEvent = (event) => {
        const detail = event?.detail || {};
        finalize(detail.transcript);
      };

      window.addEventListener(eventName, handleEvent, { once: true });

      const script = document.createElement("script");
      script.textContent = `
        (() => {
          const eventName = ${JSON.stringify(eventName)};
          const emit = (transcript) => {
            window.dispatchEvent(new CustomEvent(eventName, {
              detail: { transcript: typeof transcript === "string" ? transcript : "" }
            }));
          };
          const normalizeWhitespace = (text) => String(text || "")
            .replace(/\\u200b/g, "")
            .replace(/[ \\t]+\\n/g, "\\n")
            .replace(/\\n{3,}/g, "\\n\\n")
            .trim();
          const decodeHtmlEntities = (text) => String(text || "")
            .replace(/&#(\\d+);/g, (_match, code) => String.fromCharCode(Number(code)))
            .replace(/&#x([0-9a-f]+);/gi, (_match, code) => String.fromCharCode(parseInt(code, 16)))
            .replace(/&amp;/g, "&")
            .replace(/&lt;/g, "<")
            .replace(/&gt;/g, ">")
            .replace(/&quot;/g, "\\"")
            .replace(/&#39;/g, "'")
            .replace(/&nbsp;/g, " ");
          const dedupeTranscriptLines = (lines) => {
            const result = [];
            const seen = new Set();
            for (const rawLine of Array.isArray(lines) ? lines : []) {
              const line = normalizeWhitespace(rawLine);
              if (!line || seen.has(line)) continue;
              seen.add(line);
              result.push(line);
            }
            return result;
          };
          const extractTextFromRuns = (value) => {
            if (!value) return "";
            if (typeof value === "string") return normalizeWhitespace(decodeHtmlEntities(value));
            if (Array.isArray(value)) {
              return normalizeWhitespace(value.map((item) => extractTextFromRuns(item)).filter(Boolean).join(""));
            }
            if (typeof value === "object") {
              if (typeof value.text === "string") return normalizeWhitespace(decodeHtmlEntities(value.text));
              if (typeof value.utf8 === "string") return normalizeWhitespace(decodeHtmlEntities(value.utf8));
              if (typeof value.simpleText === "string") return normalizeWhitespace(decodeHtmlEntities(value.simpleText));
              if (Array.isArray(value.runs)) {
                return normalizeWhitespace(value.runs.map((item) => extractTextFromRuns(item)).filter(Boolean).join(""));
              }
              for (const key of ["cue", "snippet", "content", "headline", "title"]) {
                const nestedText = extractTextFromRuns(value[key]);
                if (nestedText) return nestedText;
              }
            }
            return "";
          };
          const isLikelyTimestamp = (text) => /^(?:\\d{1,2}:)?\\d{1,2}:\\d{2}$/.test(String(text || "").trim());
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
                if (!line || isLikelyTimestamp(line)) continue;
                lines.push(line);
              }
            }
            return normalizeWhitespace(dedupeTranscriptLines(lines).join("\\n"));
          };
          const collectCueGroups = (root, results = [], seen = new Set()) => {
            if (!root || typeof root !== "object" || seen.has(root) || results.length >= 5) return results;
            seen.add(root);
            if (Array.isArray(root)) {
              for (const item of root) {
                collectCueGroups(item, results, seen);
                if (results.length >= 5) break;
              }
              return results;
            }
            if (Array.isArray(root.cueGroups) && root.cueGroups.length) {
              results.push(root.cueGroups);
            }
            for (const value of Object.values(root)) {
              collectCueGroups(value, results, seen);
              if (results.length >= 5) break;
            }
            return results;
          };
          const extractTranscriptFromStructuredData = (root) => {
            const candidates = collectCueGroups(root);
            for (const cueGroups of candidates) {
              const transcript = extractTranscriptFromCueGroups(cueGroups);
              if (transcript) return transcript;
            }
            return "";
          };
          const parseMaybeJson = (value) => {
            if (!value) return null;
            if (typeof value === "object") return value;
            try { return JSON.parse(value); } catch (_error) { return null; }
          };

          try {
            const candidates = [];
            candidates.push(window.ytInitialData);
            candidates.push(parseMaybeJson(window?.ytcfg?.data_?.INITIAL_DATA));
            if (typeof window?.ytcfg?.get === "function") {
              candidates.push(parseMaybeJson(window.ytcfg.get("INITIAL_DATA")));
              candidates.push(parseMaybeJson(window.ytcfg.get("ytInitialData")));
            }
            for (const candidate of candidates) {
              const transcript = extractTranscriptFromStructuredData(candidate);
              if (transcript) {
                emit(transcript);
                return;
              }
            }
          } catch (_error) {}

          emit("");
        })();
      `;

      const parent = document.documentElement || document.head || document.body;
      if (!parent) {
        finalize("");
        return;
      }

      parent.appendChild(script);
      script.remove();
      window.setTimeout(() => finalize(""), 2500);
    });
  }

  async function getYouTubeTranscriptFromPageContext() {
    const eventName = `yt_transcript_result_${Date.now()}_${Math.random().toString(16).slice(2)}`;

    return new Promise((resolve) => {
      let settled = false;

      const finalize = (payload) => {
        if (settled) {
          return;
        }
        settled = true;
        window.removeEventListener(eventName, handleEvent);
        const normalized = payload && typeof payload === "object" ? payload : {};
        resolve({
          ok: Boolean(normalized.ok && String(normalized.transcript || "").trim()),
          transcript: String(normalized.transcript || ""),
          error: String(normalized.error || ""),
          debug: normalized.debug && typeof normalized.debug === "object" ? normalized.debug : {}
        });
      };

      const handleEvent = (event) => {
        finalize(event?.detail || {});
      };

      window.addEventListener(eventName, handleEvent, { once: true });

      const script = document.createElement("script");
      script.textContent = `
        (async () => {
          const eventName = ${JSON.stringify(eventName)};
          const emit = (payload) => {
            window.dispatchEvent(new CustomEvent(eventName, {
              detail: payload && typeof payload === "object" ? payload : {}
            }));
          };
          const normalizeWhitespace = (text) => String(text || "")
            .replace(/\\u200b/g, "")
            .replace(/[ \\t]+\\n/g, "\\n")
            .replace(/\\n{3,}/g, "\\n\\n")
            .trim();
          const decodeHtmlEntities = (text) => String(text || "")
            .replace(/&#(\\d+);/g, (_match, code) => String.fromCharCode(Number(code)))
            .replace(/&#x([0-9a-f]+);/gi, (_match, code) => String.fromCharCode(parseInt(code, 16)))
            .replace(/&amp;/g, "&")
            .replace(/&lt;/g, "<")
            .replace(/&gt;/g, ">")
            .replace(/&quot;/g, "\\"")
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
                } else if (ch === "\\\\") {
                  escaped = true;
                } else if (ch === "\\"") {
                  inString = false;
                }
                continue;
              }
              if (ch === "\\"") {
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
          const parseMaybeJson = (value) => {
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
          const isLikelyTimestamp = (text) => /^(?:\\d{1,2}:)?\\d{1,2}:\\d{2}$/.test(String(text || "").trim());
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
            return normalizeWhitespace(dedupeTranscriptLines(lines).join("\\n"));
          };
          const parseYouTubeXmlTranscript = (xmlText) => {
            const lines = [];
            const source = String(xmlText || "");
            const pattern = /<(text|p|s)\\b[^>]*>([\\s\\S]*?)<\\/\\1>/g;
            for (const match of source.matchAll(pattern)) {
              const raw = String(match[2] || "").replace(/<[^>]+>/g, " ");
              const cleaned = normalizeWhitespace(decodeHtmlEntities(raw));
              if (cleaned) {
                lines.push(cleaned);
              }
            }
            return normalizeWhitespace(dedupeTranscriptLines(lines).join("\\n"));
          };
          const parseYouTubeVttTranscript = (vttText) => {
            const lines = [];
            const blocks = String(vttText || "")
              .replace(/\\r/g, "")
              .split(/\\n\\s*\\n/);
            for (const block of blocks) {
              const rawLines = block
                .split("\\n")
                .map((line) => normalizeWhitespace(line))
                .filter(Boolean);
              if (!rawLines.length) {
                continue;
              }
              const contentLines = rawLines.filter((line) => {
                if (line === "WEBVTT") {
                  return false;
                }
                if (/^\\d+$/.test(line)) {
                  return false;
                }
                if (/^\\d{2}:\\d{2}(?::\\d{2})?\\.\\d{3}\\s+-->\\s+\\d{2}:\\d{2}(?::\\d{2})?\\.\\d{3}/.test(line)) {
                  return false;
                }
                return true;
              });
              const cleaned = normalizeWhitespace(decodeHtmlEntities(contentLines.join(" ")));
              if (cleaned) {
                lines.push(cleaned);
              }
            }
            return normalizeWhitespace(dedupeTranscriptLines(lines).join("\\n"));
          };
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
                if (!line || isLikelyTimestamp(line)) {
                  continue;
                }
                lines.push(line);
              }
            }
            return normalizeWhitespace(dedupeTranscriptLines(lines).join("\\n"));
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
          const getInlineTranscript = () => {
            const candidates = [];
            candidates.push(window.ytInitialData);
            candidates.push(parseMaybeJson(window?.ytcfg?.data_?.INITIAL_DATA));
            if (typeof window?.ytcfg?.get === "function") {
              candidates.push(parseMaybeJson(window.ytcfg.get("INITIAL_DATA")));
              candidates.push(parseMaybeJson(window.ytcfg.get("ytInitialData")));
            }
            for (const candidate of candidates) {
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
              for (const marker of [
                "ytInitialData =",
                "var ytInitialData =",
                "window[\\"ytInitialData\\"] =",
                "ytInitialData=",
                "\\"ytInitialData\\":"
              ]) {
                const parsed = parseJsonObjectAfterMarker(text, marker);
                const transcript = extractTranscriptFromStructuredData(parsed);
                if (transcript) {
                  return transcript;
                }
              }
            }
            return "";
          };
          const getCaptionTracks = () => {
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
                return tracks;
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
          const getYoutubeVideoId = () => {
            try {
              const currentUrl = new URL(location.href);
              const watchId = currentUrl.searchParams.get("v");
              if (watchId) {
                return watchId;
              }
              const liveMatch = currentUrl.pathname.match(/\\/live\\/([^/?&#]+)/i);
              if (liveMatch && liveMatch[1]) {
                return liveMatch[1];
              }
            } catch (_error) {
              // Ignore malformed location.href and fall back to player data.
            }
            const candidates = [];
            candidates.push(globalThis?.ytInitialPlayerResponse);
            candidates.push(parseMaybeJson(globalThis?.ytplayer?.config?.args?.player_response));
            candidates.push(parseMaybeJson(globalThis?.ytcfg?.data_?.PLAYER_VARS?.player_response));
            if (typeof globalThis?.ytcfg?.get === "function") {
              candidates.push(parseMaybeJson(globalThis.ytcfg.get("PLAYER_RESPONSE")));
              candidates.push(parseMaybeJson(globalThis.ytcfg.get("ytInitialPlayerResponse")));
            }
            for (const candidate of candidates) {
              const videoId = String(candidate?.videoDetails?.videoId || candidate?.currentVideoEndpoint?.watchEndpoint?.videoId || "").trim();
              if (videoId) {
                return videoId;
              }
            }
            return "";
          };
          const buildAcceptLanguageHeader = () => {
            const languages = Array.isArray(globalThis?.navigator?.languages) && globalThis.navigator.languages.length
              ? globalThis.navigator.languages
              : [globalThis?.navigator?.language || "en-US"];
            const normalized = [];
            const seen = new Set();
            for (const rawLanguage of languages) {
              const language = String(rawLanguage || "").trim();
              if (!language || seen.has(language)) {
                continue;
              }
              seen.add(language);
              normalized.push(language);
              const shortLanguage = language.split("-")[0];
              if (shortLanguage && !seen.has(shortLanguage)) {
                seen.add(shortLanguage);
                normalized.push(shortLanguage);
              }
              if (normalized.length >= 6) {
                break;
              }
            }
            return normalized
              .slice(0, 6)
              .map((language, index) => index === 0 ? language : language + ";q=" + Math.max(0.1, 1 - (index * 0.1)).toFixed(1))
              .join(", ");
          };
          const getInnertubeConfig = () => {
            let apiKey = "";
            let clientVersion = "";
            let clientName = "";
            let visitorData = "";
            let hl = "";
            let gl = "";
            let loggedIn = false;
            let context = null;
            try {
              apiKey = String(window?.ytcfg?.get?.("INNERTUBE_API_KEY") || "");
              clientVersion = String(window?.ytcfg?.get?.("INNERTUBE_CLIENT_VERSION") || "");
              clientName = String(window?.ytcfg?.get?.("INNERTUBE_CONTEXT_CLIENT_NAME") || "");
              visitorData = String(window?.ytcfg?.get?.("VISITOR_DATA") || "");
              hl = String(window?.ytcfg?.get?.("HL") || "");
              gl = String(window?.ytcfg?.get?.("GL") || "");
              loggedIn = Boolean(window?.ytcfg?.get?.("LOGGED_IN"));
              context = parseMaybeJson(window?.ytcfg?.get?.("INNERTUBE_CONTEXT"));
            } catch (_error) {
              // Continue to fallback script scanning below.
            }
            if (!context) {
              context = parseMaybeJson(window?.ytcfg?.data_?.INNERTUBE_CONTEXT);
            }
            if (!apiKey || !clientVersion || !clientName || !visitorData || !hl || !gl || !context) {
              const scripts = Array.from(document.getElementsByTagName("script"));
              for (const scriptNode of scripts) {
                const text = scriptNode.textContent || "";
                if (!text) {
                  continue;
                }
                if (!apiKey) {
                  apiKey = String((text.match(/"INNERTUBE_API_KEY"\\s*:\\s*"([^"]+)"/) || [])[1] || apiKey);
                }
                if (!clientVersion) {
                  clientVersion = String((text.match(/"INNERTUBE_CLIENT_VERSION"\\s*:\\s*"([^"]+)"/) || [])[1] || clientVersion);
                }
                if (!clientName) {
                  clientName = String((text.match(/"INNERTUBE_CONTEXT_CLIENT_NAME"\\s*:\\s*"([^"]+)"/) || [])[1] || clientName);
                }
                if (!visitorData) {
                  visitorData = String((text.match(/"VISITOR_DATA"\\s*:\\s*"([^"]+)"/) || [])[1] || visitorData);
                }
                if (!hl) {
                  hl = String((text.match(/"HL"\\s*:\\s*"([^"]+)"/) || [])[1] || hl);
                }
                if (!gl) {
                  gl = String((text.match(/"GL"\\s*:\\s*"([^"]+)"/) || [])[1] || gl);
                }
                if (!context) {
                  context = parseJsonObjectAfterMarker(text, "\\"INNERTUBE_CONTEXT\\":");
                }
                if (apiKey && clientVersion && clientName && visitorData && hl && gl && context) {
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
              loggedIn,
              context: context && typeof context === "object" ? context : null
            };
          };
          const buildInnertubeContext = (config, overrideClientName = "") => {
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
          };
          const buildYoutubeiHeaders = (config, requestContext) => {
            const clientName = String(requestContext?.client?.clientName || config?.clientName || "WEB").toUpperCase();
            const headers = {
              "Content-Type": "application/json",
              "X-YouTube-Client-Name": CLIENT_NAME_TO_ID[clientName] || "1",
              "X-YouTube-Client-Version": String(requestContext?.client?.clientVersion || config?.clientVersion || ""),
              "Accept-Language": buildAcceptLanguageHeader()
            };
            if (config?.visitorData) {
              headers["X-Goog-Visitor-Id"] = config.visitorData;
            }
            headers["X-Youtube-Bootstrap-Logged-In"] = config?.loggedIn ? "true" : "false";
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
              { value: window.ytInitialData, source: "ytInitialData" },
              { value: parseMaybeJson(window?.ytcfg?.data_?.INITIAL_DATA), source: "ytcfg.data_.INITIAL_DATA" }
            ];
            if (typeof window?.ytcfg?.get === "function") {
              initialDataCandidates.push({ value: parseMaybeJson(window.ytcfg.get("INITIAL_DATA")), source: "ytcfg.get(INITIAL_DATA)" });
              initialDataCandidates.push({ value: parseMaybeJson(window.ytcfg.get("ytInitialData")), source: "ytcfg.get(ytInitialData)" });
            }
            for (const candidate of initialDataCandidates) {
              const endpoints = findValuesByKey(candidate.value, "getTranscriptEndpoint");
              for (const endpoint of endpoints) {
                pushCandidate(endpoint?.params, candidate.source);
              }
            }
            const scripts = Array.from(document.getElementsByTagName("script"));
            for (const scriptNode of scripts) {
              const text = scriptNode.textContent || "";
              if (!text.includes("getTranscriptEndpoint")) {
                continue;
              }
              for (const match of text.matchAll(/"getTranscriptEndpoint"\\s*:\\s*\\{\\s*"params"\\s*:\\s*"([^"]+)"/g)) {
                pushCandidate(match[1], "inline_script");
              }
            }
            return results;
          };
          const fetchInnertubeJson = async (endpointName, config, requestContext, requestBody) => {
            const url = new URL("/youtubei/v1/" + endpointName, location.origin);
            url.searchParams.set("prettyPrint", "false");
            if (config?.apiKey) {
              url.searchParams.set("key", config.apiKey);
            }
            const controller = new AbortController();
            const timeoutId = window.setTimeout(() => controller.abort(), 8000);
            let response;
            try {
              response = await fetch(url.toString(), {
                method: "POST",
                headers: buildYoutubeiHeaders(config, requestContext),
                body: JSON.stringify(requestBody),
                credentials: "same-origin",
                cache: "no-store",
                signal: controller.signal
              });
            } finally {
              window.clearTimeout(timeoutId);
            }
            const rawText = await response.text();
            return {
              ok: response.ok,
              status: response.status,
              bodyPreview: normalizeWhitespace(rawText).slice(0, 240),
              data: parseMaybeJson(rawText)
            };
          };
          const fetchTranscriptParamsViaNext = async (trace, config) => {
            const videoId = getYoutubeVideoId();
            if (!videoId) {
              trace.push("page_context_next_missing_video_id");
              return [];
            }
            const contexts = [];
            const seenContexts = new Set();
            const pushContext = (clientName) => {
              const context = buildInnertubeContext(config, clientName);
              const signature = String(context?.client?.clientName || "") + "|" + String(context?.client?.clientVersion || "");
              if (!context?.client?.clientVersion || seenContexts.has(signature)) {
                return;
              }
              seenContexts.add(signature);
              contexts.push(context);
            };
            pushContext("");
            pushContext("WEB");
            pushContext("MWEB");
            pushContext("ANDROID");
            pushContext("IOS");
            pushContext("TVHTML5");
            const paramsCandidates = [];
            const seenParams = new Set();
            const pushParam = (params, source) => {
              const value = String(params || "").trim();
              if (!value || seenParams.has(value)) {
                return;
              }
              seenParams.add(value);
              paramsCandidates.push({ params: value, source });
            };
            for (const requestContext of contexts) {
              const clientName = String(requestContext?.client?.clientName || "WEB");
              try {
                const response = await fetchInnertubeJson(
                  "next",
                  config,
                  requestContext,
                  {
                    context: requestContext,
                    videoId,
                    contentCheckOk: true,
                    racyCheckOk: true
                  }
                );
                if (!response.ok) {
                  trace.push("page_context_next_http_" + response.status + ":client=" + clientName + ":body=" + (response.bodyPreview || "empty"));
                  continue;
                }
                const endpoints = findValuesByKey(response.data, "getTranscriptEndpoint");
                for (const endpoint of endpoints) {
                  pushParam(endpoint?.params, "youtubei_next:" + clientName);
                }
                if (paramsCandidates.length) {
                  trace.push("page_context_next_found_transcript_params:client=" + clientName + ":count=" + paramsCandidates.length);
                  return paramsCandidates;
                }
                trace.push("page_context_next_missing_transcript_endpoint:client=" + clientName);
              } catch (error) {
                trace.push("page_context_next_exception:client=" + clientName + ":error=" + String(error?.message || error || "unknown"));
              }
            }
            return paramsCandidates;
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
                if (!text || isLikelyTimestamp(text)) {
                  continue;
                }
                lines.push(text);
              }
            }
            return normalizeWhitespace(dedupeTranscriptLines(lines).join("\\n"));
          };
          const fetchTranscriptViaYoutubei = async (trace) => {
            const config = getInnertubeConfig();
            const paramsCandidates = getTranscriptParamsCandidates();
            if (!paramsCandidates.length && config.apiKey && config.clientVersion) {
              paramsCandidates.push(...(await fetchTranscriptParamsViaNext(trace, config)));
            }
            if (!config.apiKey || !config.clientVersion || !paramsCandidates.length) {
              if (!config.apiKey) trace.push("page_context_missing_api_key");
              if (!config.clientVersion) trace.push("page_context_missing_client_version");
              if (!paramsCandidates.length) trace.push("page_context_missing_transcript_params");
              return "";
            }
            const contexts = [];
            const seenContexts = new Set();
            const pushContext = (clientName) => {
              const context = buildInnertubeContext(config, clientName);
              const signature = \`\${String(context?.client?.clientName || "")}|\${String(context?.client?.clientVersion || "")}\`;
              if (!context?.client?.clientVersion || seenContexts.has(signature)) {
                return;
              }
              seenContexts.add(signature);
              contexts.push(context);
            };
            pushContext("");
            pushContext("WEB");
            pushContext("MWEB");
            pushContext("ANDROID");
            pushContext("IOS");
            pushContext("TVHTML5");
            for (const candidate of paramsCandidates.slice(0, 4)) {
              for (const requestContext of contexts) {
                const clientName = String(requestContext?.client?.clientName || "WEB");
                try {
                  const response = await fetchInnertubeJson(
                    "get_transcript",
                    config,
                    requestContext,
                    {
                      context: requestContext,
                      params: candidate.params
                    }
                  );
                  if (!response.ok) {
                    trace.push(\`page_context_youtubei_http_\${response.status}:client=\${clientName}:source=\${candidate.source}:body=\${response.bodyPreview || "empty"}\`);
                    continue;
                  }
                  const transcript = extractTranscriptFromYoutubeiData(response.data);
                  if (transcript) {
                    trace.push(\`page_context_youtubei_ok:client=\${clientName}:source=\${candidate.source}\`);
                    return transcript;
                  }
                  trace.push(\`page_context_youtubei_empty:client=\${clientName}:source=\${candidate.source}\`);
                } catch (error) {
                  trace.push(\`page_context_youtubei_exception:client=\${clientName}:source=\${candidate.source}:error=\${String(error?.message || error || "unknown")}\`);
                }
              }
            }
            return "";
          };
          const fetchCaptionTrack = async (track, trace) => {
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
              // Ignore malformed URL and try original.
            }
            candidates.push(baseUrl);
            for (const candidate of candidates) {
              try {
                const response = await fetch(candidate, {
                  method: "GET",
                  credentials: "same-origin",
                  cache: "no-store"
                });
                if (!response.ok) {
                  trace.push(\`page_context_track_http_\${response.status}\`);
                  continue;
                }
                const rawText = await response.text();
                const trimmed = rawText.trim();
                if (!trimmed) {
                  trace.push("page_context_track_empty_body");
                  continue;
                }
                let transcript = "";
                if (trimmed.startsWith("{")) {
                  transcript = parseYouTubeJsonTranscript(JSON.parse(trimmed));
                } else {
                  transcript = parseYouTubeXmlTranscript(trimmed) || parseYouTubeVttTranscript(trimmed);
                }
                if (transcript) {
                  return transcript;
                }
              } catch (error) {
                trace.push(\`page_context_track_exception:\${String(error?.message || error || "unknown")}\`);
              }
            }
            return "";
          };

          try {
            const trace = [];
            const tracks = getCaptionTracks();
            if (!tracks.length) {
              const inlineTranscript = getInlineTranscript();
              if (inlineTranscript) {
                emit({
                  ok: true,
                  transcript: inlineTranscript,
                  debug: {
                    source: "page_context_inline_transcript",
                    trace
                  }
                });
                return;
              }
              emit({
                ok: false,
                error: "page_context_no_caption_tracks",
                debug: { trace }
              });
              return;
            }
            const youtubeiTranscript = await fetchTranscriptViaYoutubei(trace);
            if (youtubeiTranscript) {
              emit({
                ok: true,
                transcript: youtubeiTranscript,
                debug: {
                  source: "page_context_youtubei_get_transcript",
                  trace
                }
              });
              return;
            }
            const sortedTracks = [...tracks].sort((a, b) => {
              const aPenalty = a?.kind === "asr" ? 1 : 0;
              const bPenalty = b?.kind === "asr" ? 1 : 0;
              return aPenalty - bPenalty;
            });
            for (const track of sortedTracks) {
              const transcript = await fetchCaptionTrack(track, trace);
              if (transcript) {
                emit({
                  ok: true,
                  transcript,
                  debug: {
                    source: "page_context_caption_track_fetch",
                    languageCode: String(track?.languageCode || ""),
                    kind: String(track?.kind || ""),
                    trace
                  }
                });
                return;
              }
            }
            const inlineTranscript = getInlineTranscript();
            if (inlineTranscript) {
              emit({
                ok: true,
                transcript: inlineTranscript,
                debug: {
                  source: "page_context_inline_transcript",
                  trace
                }
              });
              return;
            }
            emit({
              ok: false,
              error: "page_context_caption_fetch_failed",
              debug: { trace }
            });
          } catch (error) {
            emit({
              ok: false,
              error: String(error?.message || error || "page_context_exception"),
              debug: {
                trace: [\`page_context_exception:\${String(error?.message || error || "unknown")}\`]
              }
            });
          }
        })();
      `;

      const parent = document.documentElement || document.head || document.body;
      if (!parent) {
        finalize({ ok: false, error: "page_context_parent_not_found" });
        return;
      }

      parent.appendChild(script);
      script.remove();
      window.setTimeout(() => finalize({ ok: false, error: "page_context_timeout" }), 12000);
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
    return Boolean(findClickableByText(TRANSCRIPT_BUTTON_PATTERNS));
  }

  function parseYouTubeXmlTranscript(xmlText) {
    try {
      const parser = new DOMParser();
      const xml = parser.parseFromString(xmlText, "text/xml");
      const textNodes = [
        ...Array.from(xml.getElementsByTagName("text")),
        ...Array.from(xml.getElementsByTagName("p")),
        ...Array.from(xml.getElementsByTagName("s"))
      ];
      const lines = dedupeTranscriptLines(textNodes
        .map((node) => decodeHtmlEntities(node.textContent || ""))
        .map((line) => normalizeWhitespace(line))
        .filter(Boolean));
      return normalizeWhitespace(lines.join("\n"));
    } catch (_error) {
      return "";
    }
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
      // #region debug-point C:track-no-baseurl
      reportContentDebug("C", "content caption track missing baseUrl", {
        languageCode: String(track?.languageCode || ""),
        kind: String(track?.kind || "")
      });
      // #endregion
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
        // #region debug-point C:track-fetch-response
        reportContentDebug("C", "content caption track fetch response", {
          candidateType: candidate.includes("fmt=json3") ? "json3" : "base",
          status: Number(resp.status || 0),
          ok: Boolean(resp.ok),
          languageCode: String(track?.languageCode || ""),
          kind: String(track?.kind || "")
        });
        // #endregion
        if (!resp.ok) {
          continue;
        }
        const rawText = await resp.text();
        const trimmed = rawText.trim();
        // #region debug-point C:track-fetch-body
        reportContentDebug("C", "content caption track fetch body", {
          candidateType: candidate.includes("fmt=json3") ? "json3" : "base",
          bodyLen: trimmed.length,
          bodyPrefix: trimmed.slice(0, 120),
          languageCode: String(track?.languageCode || ""),
          kind: String(track?.kind || "")
        });
        // #endregion
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
        for (const parser of [parseYouTubeXmlTranscript, parseYouTubeVttTranscript]) {
          const transcript = parser(trimmed);
          if (transcript) {
            return transcript;
          }
        }
      } catch (_error) {
        // #region debug-point C:track-fetch-exception
        reportContentDebug("C", "content caption track fetch exception", {
          candidateType: candidate.includes("fmt=json3") ? "json3" : "base",
          languageCode: String(track?.languageCode || ""),
          kind: String(track?.kind || "")
        });
        // #endregion
        // try next candidate
      }
    }
    return "";
  }

  async function extractYouTubeTranscriptFromData() {
    for (let attempt = 0; attempt < 1; attempt += 1) {
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
      const pageContextTranscript = await getYouTubeInlineTranscriptFromPageContext();
      if (pageContextTranscript) {
        return pageContextTranscript;
      }
      const htmlSource = await fetchCurrentPageHtml();
      const htmlTranscript = extractStructuredTranscriptFromSource(htmlSource);
      if (htmlTranscript) {
        return htmlTranscript;
      }
      if (attempt < 2) {
        cachedYouTubeCaptionTracks = null;
        cachedYouTubeCaptionTracksUrl = "";
        await sleep(600);
      }
    }

    const pageContextResult = await getYouTubeTranscriptFromPageContext();
    if (pageContextResult?.ok && pageContextResult.transcript) {
      traceExtraction(`页面主上下文桥接提取成功，来源: ${String(pageContextResult?.debug?.source || "unknown")}`);
      return pageContextResult.transcript;
    }
    if (pageContextResult?.error) {
      traceExtraction(`页面主上下文桥接未拿到 transcript: ${pageContextResult.error}`);
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

  reportContentBootstrap("content bootstrap registering runtime listener", {
    href: String(location.href || ""),
    readyState: String(document.readyState || "")
  });

  extensionApi.runtime.onMessage.addListener((message, _sender, sendResponse) => {
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
          // #region debug-point B:content-start
          reportContentDebug("B", "content extractTranscript received", {
            host,
            href: String(location.href || ""),
            title,
            readyState: String(document.readyState || "")
          });
          // #endregion

          const tracks = await getYouTubeCaptionTracks();
          log(`获取到 captionTracks 数量: ${tracks.length}`);
          // #region debug-point C:tracks-count
          reportContentDebug("C", "content captionTracks fetched", {
            href: String(location.href || ""),
            trackCount: tracks.length,
            hasVisiblePanel: hasVisibleYouTubeTranscriptPanel(),
            hasPotentialButton: hasPotentialTranscriptButton()
          });
          // #endregion

          log("优先从当前页面 DOM 提取 transcript");
          transcript = extractYouTubeTranscript();
          reportContentDebug("C", "content transcript-from-dom-first result", {
            href: String(location.href || ""),
            transcriptLen: String(transcript || "").trim().length,
            hasVisiblePanel: hasVisibleYouTubeTranscriptPanel(),
            hasPotentialButton: hasPotentialTranscriptButton()
          });
          if (transcript) {
            log(`已从页面 DOM 提取文本，长度: ${transcript.length}`);
            helperMessage = "已从当前页面 transcript 面板读取文本。";
          }

          if (!transcript) {
            log("优先尝试自动展开 YouTube transcript 面板");
            const ensureResult = await ensureYouTubeTranscriptVisible();
            log(`展开面板结果: ${ensureResult.ok ? "成功" : "失败"}, autoOpened: ${ensureResult.autoOpened}, path: ${ensureResult.path || ""}`);
            reportContentDebug("C", "content ensure transcript visible first result", {
              href: String(location.href || ""),
              ensureOk: Boolean(ensureResult?.ok),
              autoOpened: Boolean(ensureResult?.autoOpened),
              hasVisiblePanel: hasVisibleYouTubeTranscriptPanel(),
              hasPotentialButton: hasPotentialTranscriptButton()
            });

            transcript = extractYouTubeTranscript();
            reportContentDebug("C", "content transcript-after-panel-first result", {
              href: String(location.href || ""),
              transcriptLen: String(transcript || "").trim().length,
              hasVisiblePanel: hasVisibleYouTubeTranscriptPanel(),
              hasPotentialButton: hasPotentialTranscriptButton()
            });
            if (ensureResult.autoOpened) {
              helperMessage = "已自动尝试展开 YouTube transcript 面板。";
            }
            if (transcript) {
              log(`展开面板后提取成功，长度: ${transcript.length}`);
            }
          }

          if (!transcript) {
            log("面板路径未成功，继续尝试页面内嵌字幕数据");
            transcript = await extractYouTubeTranscriptFromData();
            reportContentDebug("C", "content transcript-from-data result", {
              href: String(location.href || ""),
              transcriptLen: String(transcript || "").trim().length,
              hasVisiblePanel: hasVisibleYouTubeTranscriptPanel(),
              hasPotentialButton: hasPotentialTranscriptButton()
            });
            if (transcript) {
              log(`已从页面内嵌数据提取 transcript，长度: ${transcript.length}`);
              helperMessage = "已从 YouTube 页面内嵌字幕数据中提取 transcript。";
            }
          }

          if (!transcript) {
            log("再次尝试自动展开 YouTube transcript 面板");
            const ensureResult = await ensureYouTubeTranscriptVisible();
            log(`展开面板结果: ${ensureResult.ok ? "成功" : "失败"}, autoOpened: ${ensureResult.autoOpened}, path: ${ensureResult.path || ""}`);
            reportContentDebug("C", "content ensure transcript visible result", {
              href: String(location.href || ""),
              ensureOk: Boolean(ensureResult?.ok),
              autoOpened: Boolean(ensureResult?.autoOpened),
              hasVisiblePanel: hasVisibleYouTubeTranscriptPanel(),
              hasPotentialButton: hasPotentialTranscriptButton()
            });

            transcript = extractYouTubeTranscript();
            reportContentDebug("C", "content transcript-after-panel result", {
              href: String(location.href || ""),
              transcriptLen: String(transcript || "").trim().length,
              hasVisiblePanel: hasVisibleYouTubeTranscriptPanel(),
              hasPotentialButton: hasPotentialTranscriptButton()
            });
            if (ensureResult.autoOpened) {
              helperMessage = "已自动尝试展开 YouTube transcript 面板。";
            }
            if (transcript) {
              log(`展开面板后提取成功，长度: ${transcript.length}`);
            }
          }

          if (transcript && !isPlausibleTranscriptText(transcript)) {
            log(`提取到的文本可信度不足 (${transcript.length})，可能命中了错误容器，重置 transcript`);
            transcript = "";
          }

          if (!transcript && tracks.length === 0 && !hasVisibleYouTubeTranscriptPanel() && !hasPotentialTranscriptButton()) {
            log("未发现任何字幕来源（无 tracks、无面板、无按钮）");
            detailedError = isYouTubeWatchPage()
              ? "当前视频页未发现可直接读取的 YouTube transcript / captionTracks。请先确认该视频是否真的开放了平台字幕；如果页面肉眼可见 transcript 但扩展仍失败，说明还需要继续补适配。"
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
          // #region debug-point B:content-failed
          reportContentDebug("B", "content extraction failed", {
            href: String(location.href || ""),
            platform,
            trackCount: host.includes("youtube.com") ? (await getYouTubeCaptionTracks()).length : null,
            helperMessage,
            detailedError: detailedError || "",
            extractionLogs
          });
          // #endregion
          sendResponse({
            ok: false,
            platform,
            title,
            url: location.href,
            transcript: "",
            helperMessage,
            error: detailedError || "当前页面未提取到可见字幕。YouTube 链路已经自动尝试展开面板但仍未成功。请确认视频确实开启了字幕，或手动刷新页面后再试。",
            detection
          });
          return;
        }

        // #region debug-point B:content-success
        reportContentDebug("B", "content extraction succeeded", {
          href: String(location.href || ""),
          platform,
          transcriptLen: transcript.length,
          helperMessage,
          extractionLogs
        });
        // #endregion
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

  const pageFlowRequestStates = new Map();

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
    if (!normalizedRequestId) {
      return;
    }
    if (!isCurrentYouTubePageForSource(payload?.sourceUrl || "")) {
      return;
    }

    const existingState = pageFlowRequestStates.get(normalizedRequestId);
    if (existingState) {
      if (existingState.replyPayload && typeof existingState.replyPayload === "object") {
        const replayPayload = {
          ...existingState.replyPayload,
          debug: {
            ...((existingState.replyPayload.debug && typeof existingState.replyPayload.debug === "object")
              ? existingState.replyPayload.debug
              : {}),
            attempts: [
              {
                stage: receivedStage,
                ok: true,
                requestId: normalizedRequestId,
                sourceUrl: String(payload?.sourceUrl || "").trim(),
                duplicateRequest: true
              },
              {
                stage: "content_script_replay_cached_reply",
                ok: true
              },
              ...((Array.isArray(existingState.replyPayload?.debug?.attempts)
                ? existingState.replyPayload.debug.attempts
                : []).filter(Boolean))
            ]
          }
        };
        postReplyToKnownWindows(normalizedRequestId, replayPayload, targetWindow);
        writePageFlowStorageResponse(normalizedRequestId, replayPayload);
      }
      return;
    }

    const attempts = [
      {
        stage: receivedStage,
        ok: true,
        requestId: normalizedRequestId,
        sourceUrl: String(payload?.sourceUrl || "").trim()
      }
    ];
    pageFlowRequestStates.set(normalizedRequestId, {
      requestId: normalizedRequestId,
      sourceUrl: String(payload?.sourceUrl || "").trim(),
      replyPayload: null
    });

    attempts.push({
      stage: "content_script_send_runtime_message",
      ok: true
    });
    (async () => {
      try {
        const response = await sendRuntimeMessage({
          action: "startSummarizeFlowFromPage",
          payload: {
            ...(payload && typeof payload === "object" ? payload : {}),
            requestOrigin: location.origin,
            requestPageUrl: location.href,
            preferLocal: payload?.preferLocal === false
              ? false
              : Boolean(payload?.preferLocal) || isLoopbackPageOrigin(location.origin)
          }
        });
        attempts.push({
          stage: "content_script_runtime_callback",
          ok: true,
          error: String(response?.error || "")
        });
        const replyPayload = {
          ...(response || { ok: false, error: "empty_background_response" }),
          debug: {
            ...((response && response.debug && typeof response.debug === "object") ? response.debug : {}),
            attempts: [
              ...attempts,
              ...((((response && response.debug) || {}).attempts) instanceof Array ? response.debug.attempts : [])
            ]
          }
        };

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
        pageFlowRequestStates.set(normalizedRequestId, {
          requestId: normalizedRequestId,
          sourceUrl: String(payload?.sourceUrl || "").trim(),
          replyPayload
        });
        writePageFlowStorageResponse(normalizedRequestId, replyPayload);
      } catch (error) {
        attempts.push({
          stage: "content_script_runtime_callback",
          ok: false,
          error: String(error?.message || error || "runtime_message_failed")
        });
        const replyPayload = {
          ok: false,
          error: String(error?.message || error || "runtime_message_failed"),
          debug: { attempts: [...attempts] }
        };

        attempts.push({
          stage: "content_script_post_reply_to_bridge",
          ok: true
        });
        postReplyToKnownWindows(normalizedRequestId, replyPayload, targetWindow);

        attempts.push({
          stage: "content_script_write_storage_reply",
          ok: true
        });
        pageFlowRequestStates.set(normalizedRequestId, {
          requestId: normalizedRequestId,
          sourceUrl: String(payload?.sourceUrl || "").trim(),
          replyPayload
        });
        writePageFlowStorageResponse(normalizedRequestId, replyPayload);
      }
    })();
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

  pollPageFlowStorageRequests();
  window.setInterval(pollPageFlowStorageRequests, 250);

  function findClickableByText(patterns) {
    const nodes = querySelectorAllDeep([
      'button',
      '[role="button"]',
      '[role="menuitem"]',
      'a',
      'tp-yt-paper-item',
      'ytd-menu-service-item-renderer',
      'ytd-menu-navigation-item-renderer',
      'yt-list-item-view-model',
      'yt-button-view-model',
      'yt-button-shape button',
      'ytd-button-renderer'
    ].join(", "));
    for (const node of nodes) {
      const text = getNodeSearchableText(node);
      if (!text) {
        continue;
      }
      if (patterns.some((pattern) => text.includes(pattern))) {
        const closestClickable = node.closest([
                'button',
                '[role="button"]',
                '[role="menuitem"]',
                'a',
                'tp-yt-paper-item',
                'ytd-menu-service-item-renderer',
                'ytd-menu-navigation-item-renderer',
                'yt-list-item-view-model',
                'yt-button-view-model',
                'yt-button-shape',
                'ytd-button-renderer'
              ].join(", ")) || node;
        const nestedButton = closestClickable.querySelector?.([
          'button',
          '[role="button"]',
          '[role="menuitem"]',
          'tp-yt-paper-button'
        ].join(", "));
        if (nestedButton && isVisibleElement(nestedButton)) {
          return nestedButton;
        }
        const nodeNestedButton = node.querySelector?.([
          'button',
          '[role="button"]',
          '[role="menuitem"]',
          'tp-yt-paper-button'
        ].join(", "));
        if (nodeNestedButton && isVisibleElement(nodeNestedButton)) {
          return nodeNestedButton;
        }
        if (isVisibleElement(closestClickable)) {
          return closestClickable;
        }
        if (isVisibleElement(node)) {
          return node;
        }
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
      "鏇村鎿嶄綔",
      "鏇村",
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
      if (joined.includes("download") || joined.includes("涓嬭浇") || joined.includes("premium")) {
        continue;
      }
      if (isVisibleElement(node)) {
        return node;
      }
    }
    return null;
  }

  function findYouTubeDescriptionExpandButton() {
    const directSelectors = [
      "ytd-text-inline-expander tp-yt-paper-button#expand",
      "ytd-text-inline-expander #expand",
      "tp-yt-paper-button#expand",
      "ytd-watch-metadata #description button[aria-label*='more' i]",
      "ytd-watch-metadata #description [role='button']",
      "#description-inline-expander button",
      "#description-inline-expander [role='button']"
    ];
    for (const selector of directSelectors) {
      const nodes = querySelectorAllDeep(selector);
      for (const node of nodes) {
        const text = getNodeSearchableText(node);
        if (!isVisibleElement(node)) {
          continue;
        }
        if (
          !text ||
          text.includes("more") ||
          text.includes("show more") ||
          text.includes("更多") ||
          text.includes("展开") ||
          text.includes("展開")
        ) {
          return node;
        }
      }
    }
    return findClickableByText([
      "show more",
      "...more",
      "…more",
      "more",
      "更多",
      "展开",
      "展開"
    ]);
  }

  function hasVisibleTranscriptPanelShell() {
    const panel = querySelectorDeep([
      "ytd-transcript-search-panel-renderer",
      "ytd-engagement-panel-section-list-renderer[target-id*='transcript']",
      "ytd-engagement-panel-section-list-renderer[target-id='PAmodern_transcript_view']"
    ].join(", "));
    return Boolean(panel && isVisibleElement(panel));
  }

  function hasVisibleMenuPopup() {
    return Boolean(querySelectorDeep([
      "ytd-menu-popup-renderer tp-yt-paper-listbox",
      "tp-yt-iron-dropdown ytd-menu-popup-renderer",
      "tp-yt-paper-dialog ytd-menu-popup-renderer",
      "[role='menu']",
      "tp-yt-paper-listbox"
    ].join(", ")));
  }

  async function waitForCondition(checker, attempts = 12, delayMs = 350) {
    for (let i = 0; i < attempts; i += 1) {
      const value = checker();
      if (value) {
        return value;
      }
      await sleep(delayMs);
    }
    return null;
  }

  async function clickNode(node) {
    if (!node) {
      return false;
    }
    const clickTarget = node.querySelector?.([
      'button',
      '[role="button"]',
      '[role="menuitem"]',
      'tp-yt-paper-button'
    ].join(", "));
    if (clickTarget && isVisibleElement(clickTarget)) {
      node = clickTarget;
    }
    try {
      if (typeof node.scrollIntoView === "function") {
        node.scrollIntoView({ block: "center", inline: "center", behavior: "instant" });
      }
    } catch (_error) {
      // Ignore scroll errors and keep clicking.
    }
    try {
      if (typeof node.focus === "function") {
        node.focus({ preventScroll: true });
      }
    } catch (_error) {
      // Ignore focus errors.
    }
    const eventTypes = ["pointerdown", "mousedown", "pointerup", "mouseup", "click"];
    for (const eventType of eventTypes) {
      try {
        node.dispatchEvent(new MouseEvent(eventType, {
          bubbles: true,
          cancelable: true,
          composed: true,
          view: window
        }));
      } catch (_error) {
        // Fall through to the next dispatch strategy.
      }
    }
    if (typeof node.click === "function") {
      try {
        node.click();
      } catch (_error) {
        // Ignore direct click failures after dispatching events.
      }
    }
    await sleep(500);
    return true;
  }

  async function waitForTranscriptPanelText(attempts = 18, delayMs = 500) {
    for (let i = 0; i < attempts; i += 1) {
      const transcript = extractYouTubeTranscript();
      if (transcript) {
        return transcript;
      }
      await sleep(delayMs);
    }
    return "";
  }

  async function ensureYouTubeTranscriptVisible() {
    const existingTranscript = extractYouTubeTranscript();
    if (existingTranscript) {
      return { ok: true, autoOpened: false };
    }
    if (hasVisibleTranscriptPanelShell()) {
      const transcriptFromExistingPanel = await waitForTranscriptPanelText(12, 450);
      if (transcriptFromExistingPanel) {
        return { ok: true, autoOpened: false, path: "existing_panel" };
      }
    }

    const descriptionExpandButton = findYouTubeDescriptionExpandButton();
    if (await clickNode(descriptionExpandButton)) {
      await sleep(700);
      const transcriptAfterDescriptionExpand = extractYouTubeTranscript();
      if (transcriptAfterDescriptionExpand) {
        return { ok: true, autoOpened: true, path: "description_expand_existing_text" };
      }
    }

    const directTranscriptButton = findClickableByText([
      ...TRANSCRIPT_BUTTON_PATTERNS
    ]);
    if (await clickNode(directTranscriptButton)) {
      const transcriptFromDirectButton = await waitForTranscriptPanelText(18, 500);
      if (transcriptFromDirectButton) {
        return { ok: true, autoOpened: true, path: "direct_button" };
      }
    }

    const moreActionsButton = findYouTubeMoreActionsButton();
    if (await clickNode(moreActionsButton)) {
      await waitForCondition(() => hasVisibleMenuPopup() || hasVisibleTranscriptPanelShell(), 10, 300);
      const menuTranscriptButton = findClickableByText([
        ...TRANSCRIPT_BUTTON_PATTERNS
      ]);
      if (await clickNode(menuTranscriptButton)) {
        const transcriptFromMenu = await waitForTranscriptPanelText(20, 500);
        if (transcriptFromMenu) {
          return { ok: true, autoOpened: true, path: "more_actions_menu" };
        }
      }
    }

    const transcriptTabButton = findClickableByText([
      "transcript",
      "转写文本",
      "内容转写",
      "文字稿",
      "字幕"
    ]);
    if (await clickNode(transcriptTabButton)) {
      const transcriptFromTab = await waitForTranscriptPanelText(20, 500);
      if (transcriptFromTab) {
        return { ok: true, autoOpened: true, path: "transcript_tab" };
      }
    }

    if (hasVisibleTranscriptPanelShell()) {
      const transcriptFromLatePanel = await waitForTranscriptPanelText(12, 500);
      if (transcriptFromLatePanel) {
        return { ok: true, autoOpened: true, path: "late_panel_content" };
      }
      return { ok: false, autoOpened: true, path: "panel_shell_without_text" };
    }

    return { ok: false, autoOpened: false, path: "none" };
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

