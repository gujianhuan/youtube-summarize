(function () {
  function sleep(ms) {
    return new Promise((resolve) => window.setTimeout(resolve, ms));
  }

  function normalizeWhitespace(text) {
    return String(text || "")
      .replace(/\u200b/g, "")
      .replace(/[ \t]+\n/g, "\n")
      .replace(/\n{3,}/g, "\n\n")
      .trim();
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
      "[target-id] .segment-text",
      "[target-id] .cue"
    ];
    const lines = [];
    for (const selector of segmentSelectors) {
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

  function decodeHtmlEntities(text) {
    const textarea = document.createElement("textarea");
    textarea.innerHTML = String(text || "");
    return textarea.value;
  }

  function extractBalancedJson(source, startIndex) {
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
      if (ch === "{") {
        depth += 1;
      } else if (ch === "}") {
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

  function getYouTubeCaptionTracks() {
    const scriptNodes = Array.from(document.scripts || []);
    const markers = [
      "ytInitialPlayerResponse =",
      "var ytInitialPlayerResponse =",
      "window[\"ytInitialPlayerResponse\"] =",
      "ytInitialPlayerResponse="
    ];

    for (const scriptNode of scriptNodes) {
      const source = scriptNode.textContent || "";
      if (!source || !source.includes("captionTracks")) {
        continue;
      }
      for (const marker of markers) {
        const playerResponse = parseJsonObjectAfterMarker(source, marker);
        const tracks = playerResponse?.captions?.playerCaptionsTracklistRenderer?.captionTracks;
        if (Array.isArray(tracks) && tracks.length) {
          return tracks;
        }
      }
    }
    return [];
  }

  function parseYouTubeXmlTranscript(xmlText) {
    try {
      const parser = new DOMParser();
      const xml = parser.parseFromString(xmlText, "text/xml");
      const textNodes = Array.from(xml.getElementsByTagName("text"));
      const lines = textNodes
        .map((node) => decodeHtmlEntities(node.textContent || ""))
        .map((line) => normalizeWhitespace(line))
        .filter(Boolean);
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
    return normalizeWhitespace(lines.join("\n"));
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
    const tracks = getYouTubeCaptionTracks();
    if (!tracks.length) {
      return "";
    }
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
    return "";
  }

  function findClickableByText(patterns) {
    const nodes = Array.from(document.querySelectorAll('button, [role="button"], tp-yt-paper-item, ytd-menu-service-item-renderer'));
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
      "文字稿"
    ]);
    if (await clickNode(directTranscriptButton)) {
      for (let i = 0; i < 5; i += 1) {
        await sleep(800);
        if (extractYouTubeTranscript()) {
          return { ok: true, autoOpened: true };
        }
      }
    }

    const moreActionsButton = document.querySelector(
      'button[aria-label*="More actions"], button[aria-label*="更多操作"], ytd-menu-renderer yt-button-shape button'
    );
    if (await clickNode(moreActionsButton)) {
      const menuTranscriptButton = findClickableByText([
        "show transcript",
        "open transcript",
        "显示文字稿",
        "显示转录稿",
        "转录稿",
        "文字稿"
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

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (!message || message.action !== "extractTranscript") {
      return;
    }
    (async () => {
      const host = location.host;
      const title = getTitle();
      let transcript = "";
      let platform = "unknown";
      let helperMessage = "";

      if (host.includes("youtube.com")) {
        platform = "youtube";
        transcript = extractYouTubeTranscript();
        if (!transcript) {
          transcript = await extractYouTubeTranscriptFromData();
          if (transcript) {
            helperMessage = "已从 YouTube 页面内嵌字幕数据中提取 transcript。";
          }
        }
        if (!transcript) {
          const ensureResult = await ensureYouTubeTranscriptVisible();
          transcript = extractYouTubeTranscript();
          if (ensureResult.autoOpened) {
            helperMessage = "已自动尝试展开 YouTube transcript 面板。";
          }
        }
      } else if (host.includes("bilibili.com") || host.includes("b23.tv")) {
        platform = "bilibili";
        transcript = extractBilibiliTranscript();
      }

      if (!transcript) {
        sendResponse({
          ok: false,
          platform,
          title,
          url: location.href,
          transcript: "",
          helperMessage,
          error: "当前页面未提取到可见字幕。YouTube 已自动尝试展开 transcript 面板；如果仍失败，请手动展开 transcript/字幕面板后再试。"
        });
        return;
      }

      sendResponse({
        ok: true,
        platform,
        title,
        url: location.href,
        transcript,
        helperMessage
      });
    })();
    return true;
  });
})();
