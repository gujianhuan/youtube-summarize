const statusEl = document.getElementById("status");
const titleInput = document.getElementById("titleInput");
const urlInput = document.getElementById("urlInput");
const transcriptOutput = document.getElementById("transcriptOutput");
const extractBtn = document.getElementById("extractBtn");
const copyBtn = document.getElementById("copyBtn");
const openBtn = document.getElementById("openBtn");
const helperPanel = document.getElementById("helperPanel");
const helperTitleEl = document.getElementById("helperTitle");
const helperDescEl = document.getElementById("helperDesc");
const helperGuideBtn = document.getElementById("helperGuideBtn");
const copyLinkBtn = document.getElementById("copyLinkBtn");

const FLOW_STATUS_KEY = "summarizerFlowStatus";
const EXTENSION_TOOL_VERSION = "chrome-extension-mvp";
const LOCAL_HELPER_GUIDE_PAGE = "local_helper_guide.html";
let lastExtractResponse = null;

/**
 * 同步提取结果相关按钮状态，避免失败态继续触发总结流程。
 *
 * 只有在本次提取成功且存在可用文本时，才允许点击“一键总结”。
 */
function syncActionButtons() {
  const transcript = transcriptOutput.value.trim();
  const hasTranscript = Boolean(transcript);
  const hasSuccessfulExtraction = Boolean(lastExtractResponse?.ok && hasTranscript);

  copyBtn.disabled = !hasTranscript;
  openBtn.disabled = !hasSuccessfulExtraction;
}

function setStatus(text, isError = false) {
  statusEl.textContent = text;
  statusEl.style.color = isError ? "#dc2626" : "#4b5563";
}

function hideHelperPanel() {
  helperPanel.classList.add("helper-panel-hidden");
  helperTitleEl.textContent = "需要本地转写助手";
  helperDescEl.textContent = "";
}

function showHelperPanel(title, description, allowGuide = true) {
  helperTitleEl.textContent = title;
  helperDescEl.textContent = description;
  helperGuideBtn.style.display = allowGuide ? "block" : "none";
  helperPanel.classList.remove("helper-panel-hidden");
}

function updateHelperPanelFromResponse(response) {
  const detection = response?.detection || {};
  const reason = String(detection.reason || "");
  const canFallback = Boolean(detection.canFallbackToLocal);

  if (canFallback && reason === "no_platform_caption_tracks") {
    showHelperPanel(
      "该视频没有开放平台字幕轨道",
      "这个视频大概率只有画面硬字幕，或作者没有对外开放 YouTube 字幕轨道，所以扩展拿不到 transcript。建议直接使用本地转写助手处理。",
      true,
    );
    return;
  }

  if (canFallback && reason === "no_text_source_found") {
    showHelperPanel(
      "该视频建议使用本地转写助手",
      "当前页面没有可直接提取的公开文本。你看到的可能只是画面硬字幕，不是平台可抓取字幕。建议打开本地转写助手，粘贴当前视频链接后再转写总结。",
      true,
    );
    return;
  }

  if (reason === "extract_failed") {
    showHelperPanel(
      "当前更像是提取失败，不是无文本",
      "扩展检测到页面可能存在文本来源，但这次提取没有成功。请优先重试，或先手动展开 transcript/字幕面板，再重新提取。",
      false,
    );
    return;
  }

  if (reason === "page_not_supported") {
    showHelperPanel(
      "当前页面暂不支持",
      "请在 YouTube 或 Bilibili 的视频详情页使用这个扩展。这个状态不应该引导你去安装本地工具。",
      false,
    );
    return;
  }

  hideHelperPanel();
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

function parseYouTubeVideoId(url) {
  try {
    const parsed = new URL(String(url || ""));
    if (parsed.hostname.includes("youtu.be")) {
      return parsed.pathname.replace(/^\/+/, "").trim();
    }
    return parsed.searchParams.get("v") || "";
  } catch (_error) {
    return "";
  }
}

/**
 * Builds the internal extension guide URL and forwards the current extraction context.
 *
 * @param {object | null} response Last extraction response.
 * @param {string} currentUrl Current source URL from popup input.
 * @returns {string}
 */
function buildLocalHelperGuideUrl(response, currentUrl) {
  const guideUrl = new URL(chrome.runtime.getURL(LOCAL_HELPER_GUIDE_PAGE));
  const sourceUrl = String(response?.url || currentUrl || "").trim();
  const reason = String(response?.detection?.reason || "").trim();

  if (sourceUrl) {
    guideUrl.searchParams.set("sourceUrl", sourceUrl);
  }
  if (reason) {
    guideUrl.searchParams.set("reason", reason);
  }

  return guideUrl.toString();
}

async function loadLastFlowStatus() {
  try {
    const result = await chrome.storage.local.get(FLOW_STATUS_KEY);
    const status = result?.[FLOW_STATUS_KEY];
    if (!status?.message) {
      return;
    }
    setStatus(status.message, Boolean(status.isError));
  } catch (_error) {
    // Ignore storage read failures in popup.
  }
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

/**
 * 在 YouTube 页面的原生上下文中直接读取播放器字幕轨道并抓取 transcript。
 *
 * 这样可以绕开 content script 隔离环境和后台抓取差异，优先利用页面已拿到的真实播放器数据。
 */
async function extractYouTubeTranscriptViaMainWorld(tabId) {
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
          const nodes = Array.from(xml.getElementsByTagName("text"));
          const lines = nodes
            .map((node) => decodeHtmlEntities(node.textContent || ""))
            .map((line) => normalizeWhitespace(line))
            .filter(Boolean);
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
          candidates.push(globalThis.ytInitialPlayerResponse || null);
          candidates.push(parseMaybeJson(globalThis?.ytplayer?.config?.args?.player_response));
          candidates.push(parseMaybeJson(globalThis?.ytcfg?.data_?.PLAYER_VARS?.player_response));
          if (typeof globalThis?.ytcfg?.get === "function") {
            candidates.push(parseMaybeJson(globalThis.ytcfg.get("PLAYER_VARS")?.player_response));
            candidates.push(parseMaybeJson(globalThis.ytcfg.get("PLAYER_RESPONSE")));
          }
          const moviePlayer = document.getElementById("movie_player");
          if (moviePlayer && typeof moviePlayer.getPlayerResponse === "function") {
            candidates.push(moviePlayer.getPlayerResponse());
          }
          for (const playerResponse of candidates) {
            const tracks = playerResponse?.captions?.playerCaptionsTracklistRenderer?.captionTracks;
            if (Array.isArray(tracks) && tracks.length) {
              return tracks;
            }
          }
          if (moviePlayer && typeof moviePlayer.getOption === "function") {
            const optionCandidates = [
              moviePlayer.getOption("captions", "tracklist"),
              moviePlayer.getOption("captions", "playerCaptionsTracklistRenderer"),
              moviePlayer.getOption("captions", "track")
            ];
            for (const candidate of optionCandidates) {
              const tracks = normalizeCaptionTracks(candidate);
              if (tracks.length) {
                return tracks;
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
                transcript = parseYouTubeXmlTranscript(trimmed);
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

async function extractYouTubeTranscriptViaBackground(sourceUrl) {
  if (!sourceUrl || !sourceUrl.includes("youtube.com")) {
    return null;
  }
  try {
    return await chrome.runtime.sendMessage({
      action: "extractYouTubeTranscriptByUrl",
      url: sourceUrl
    });
  } catch (_error) {
    return null;
  }
}

function buildYouTubeBackgroundSuccessResponse(baseResponse, fallbackResult, tab) {
  const sourceUrl = baseResponse?.url || tab?.url || "";
  return {
    ...(baseResponse || {}),
    ok: true,
    platform: "youtube",
    title: baseResponse?.title || tab?.title || "",
    url: sourceUrl,
    transcript: fallbackResult.transcript,
    helperMessage: "已通过扩展后台直连 YouTube 字幕接口完成提取。",
    detection: {
      hasText: true,
      sourceType: "transcript",
      confidence: 0.99,
      reason: "background_caption_fetch",
      canFallbackToLocal: false
    },
    debug: fallbackResult.debug || {}
  };
}

function applyExtractSuccess(response, sourceUrl) {
  titleInput.value = response.title || "";
  urlInput.value = response.url || sourceUrl || "";
  transcriptOutput.value = response.transcript || "";
  const helperText = response.helperMessage ? ` ${response.helperMessage}` : "";
  setStatus(`提取完成：${response.platform}，约 ${response.transcript.length} 字符。${helperText}`);
  lastExtractResponse = response;
  syncActionButtons();
  updateHelperPanelFromResponse(response);
  return response;
}

async function extractTranscript() {
  const tab = await getActiveTab();
  if (!tab || !tab.id) {
    lastExtractResponse = null;
    syncActionButtons();
    setStatus("未找到当前页面。", true);
    return;
  }
  openBtn.disabled = true;
  const activeUrl = String(tab.url || "");

  if (activeUrl.includes("youtube.com")) {
    setStatus("正在直接从当前 YouTube 页面读取播放器字幕...");
    const mainWorldResult = await extractYouTubeTranscriptViaMainWorld(tab.id);
    if (mainWorldResult?.ok && mainWorldResult.transcript) {
      const mainWorldResponse = buildYouTubeBackgroundSuccessResponse({
        title: tab.title || "",
        url: activeUrl
      }, mainWorldResult, tab);
      mainWorldResponse.helperMessage = "已通过当前页面播放器数据直接提取 YouTube 字幕。";
      mainWorldResponse.detection.reason = "main_world_caption_fetch";
      return applyExtractSuccess(mainWorldResponse, activeUrl);
    }

    setStatus("页面主上下文读取未成功，正在通过扩展后台直连抓取 YouTube 字幕...");
    const directResult = await extractYouTubeTranscriptViaBackground(activeUrl);
    if (directResult?.ok && directResult.transcript) {
      const directResponse = buildYouTubeBackgroundSuccessResponse({
        title: tab.title || "",
        url: activeUrl
      }, directResult, tab);
      return applyExtractSuccess(directResponse, activeUrl);
    }
    if (directResult?.error || mainWorldResult?.error) {
      setStatus(`直连未成功，正在回退到页面提取... ${mainWorldResult?.error || "main_world_failed"} / ${directResult?.error || "background_failed"}`);
    } else {
      setStatus("直连未成功，正在回退到页面提取...");
    }
  } else {
    setStatus("正在向页面请求字幕...");
  }

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
        lastExtractResponse = null;
        syncActionButtons();
        setStatus(`提取失败: ${retryError.message}`, true);
        return;
      }
    } else {
      lastExtractResponse = null;
      syncActionButtons();
      setStatus(`提取失败: ${message || "未知错误"}`, true);
      return;
    }
  }
  if (!response) {
    lastExtractResponse = null;
    syncActionButtons();
    return;
  }
  if (!response.ok) {
    const sourceUrl = response.url || tab.url || "";
    if (sourceUrl.includes("youtube.com")) {
      setStatus("页面提取失败，正在尝试 YouTube 直连兜底...");
      const mainWorldFallback = await extractYouTubeTranscriptViaMainWorld(tab.id);
      if (mainWorldFallback?.ok && mainWorldFallback.transcript) {
        const mainWorldResponse = buildYouTubeBackgroundSuccessResponse(response, mainWorldFallback, tab);
        mainWorldResponse.helperMessage = "已通过当前页面播放器数据直接提取 YouTube 字幕。";
        mainWorldResponse.detection.reason = "main_world_caption_fetch";
        return applyExtractSuccess(mainWorldResponse, sourceUrl);
      }

      const fallbackResult = await extractYouTubeTranscriptViaBackground(sourceUrl);
      if (fallbackResult?.ok && fallbackResult.transcript) {
        const backgroundResponse = buildYouTubeBackgroundSuccessResponse(response, fallbackResult, tab);
        return applyExtractSuccess(backgroundResponse, sourceUrl);
      }
      if (
        mainWorldFallback?.error === "main_world_no_caption_tracks" &&
        fallbackResult?.error === "background_no_caption_tracks"
      ) {
        response.detection = {
          ...(response.detection || {}),
          hasText: false,
          sourceType: "none",
          confidence: 0.98,
          reason: "no_platform_caption_tracks",
          canFallbackToLocal: true
        };
        response.helperMessage = "已确认当前视频没有可直接读取的 YouTube 平台字幕轨道；如果画面里能看到字幕，那更像是视频内嵌硬字幕。";
      }
      response.error = `${response.error || "页面提取失败。"} 直连也失败：${mainWorldFallback?.error || "main_world_failed"} / ${fallbackResult?.error || "background_failed"}`;
    }

    const helperText = response.helperMessage ? ` ${response.helperMessage}` : "";
    setStatus((response.error || "未提取到字幕。") + helperText, true);
    titleInput.value = response.title || "";
    urlInput.value = response.url || tab.url || "";
    transcriptOutput.value = response.transcript || "";
    lastExtractResponse = response;
    syncActionButtons();
    updateHelperPanelFromResponse(response);
    return;
  }
  return applyExtractSuccess(response, tab.url || "");
}

chrome.runtime.onMessage.addListener((message) => {
  if (message?.action !== "summarizeFlowStatus") {
    return;
  }
  const payload = message.payload || {};
  if (payload.message) {
    setStatus(String(payload.message), Boolean(payload.isError));
  }
});

loadLastFlowStatus();
syncActionButtons();

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

helperGuideBtn.addEventListener("click", async () => {
  const guideUrl = buildLocalHelperGuideUrl(lastExtractResponse, urlInput.value.trim());
  await chrome.tabs.create({ url: guideUrl });
});

copyLinkBtn.addEventListener("click", async () => {
  const currentUrl = urlInput.value.trim();
  if (!currentUrl) {
    setStatus("当前没有可复制的视频链接。", true);
    return;
  }
  await navigator.clipboard.writeText(currentUrl);
  setStatus("已复制视频链接，可粘贴到本地转写助手。");
});

openBtn.addEventListener("click", async () => {
  let transcript = transcriptOutput.value.trim();
  let sourceUrl = urlInput.value.trim();
  let response = lastExtractResponse;
  if (!transcript) {
    response = await extractTranscript();
    if (!response || !response.ok) {
      const detection = response?.detection || {};
      if (detection.canFallbackToLocal && detection.reason === "no_text_source_found") {
        setStatus("当前视频没有可直接提取的文本，请改用本地转写助手。", true);
      } else {
        setStatus("未能自动提取字幕，无法发送到主站。", true);
      }
      return;
    }
    transcript = (response.transcript || "").trim();
    sourceUrl = (response.url || "").trim();
  }
  if (!transcript) {
    setStatus("没有可发送的字幕文本。", true);
    return;
  }

  try {
    await navigator.clipboard.writeText(transcript);
  } catch (_error) {
    // Clipboard is best-effort fallback.
  }

  const payloadId = buildPayloadId();
  const envelope = buildTranscriptEnvelope(payloadId, response, transcript, sourceUrl, titleInput.value.trim());
  const payload = {
    payloadId,
    transcript,
    sourceUrl,
    title: titleInput.value.trim(),
    createdAt: new Date().toISOString(),
    bridgeVersion: 2,
    envelope
  };

  try {
    setStatus("任务已交给后台，正在打开主站并发送 transcript...");
    await chrome.runtime.sendMessage({
      action: "startSummarizeFlow",
      payload
    });
  } catch (error) {
    const message = String(error?.message || "");
    setStatus(`后台任务启动失败。${message ? ` ${message}` : ""}`, true);
  }
});
