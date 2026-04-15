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
