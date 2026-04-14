(function () {
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

  function extractBilibiliTranscript() {
    const selectors = [
      ".bpx-player-subtitle-panel-text",
      ".bcc-subtitle-row",
      ".subtitle-item-text",
      ".bui-collapse-wrap .text"
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
    const host = location.host;
    const title = getTitle();
    let transcript = "";
    let platform = "unknown";

    if (host.includes("youtube.com")) {
      platform = "youtube";
      transcript = extractYouTubeTranscript();
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
        error: "当前页面未提取到可见字幕。请先在页面中展开 transcript/字幕面板后再试。"
      });
      return;
    }

    sendResponse({
      ok: true,
      platform,
      title,
      url: location.href,
      transcript
    });
  });
})();
