/**
 * Shared transcript contracts for extension, web app, bridge, and local helper.
 *
 * This file is intentionally framework-agnostic so the current JS MVP can
 * gradually migrate to typed contracts without introducing a new build chain.
 */

export const TRANSCRIPT_SCHEMA_VERSION = "1.0" as const;
export const BRIDGE_PAYLOAD_VERSION_V1 = 1 as const;
export const BRIDGE_PAYLOAD_VERSION_V2 = 2 as const;

export type PlatformKind = "youtube";

export type SourceKind = "extension" | "local_tool" | "manual_paste";

export type SourceTextType =
  | "subtitle"
  | "transcript"
  | "subtitle_and_transcript"
  | "local_asr"
  | "manual_text"
  | "none";

export type DetectionReason =
  | "subtitle_panel_available"
  | "transcript_panel_available"
  | "subtitle_and_transcript_available"
  | "no_text_source_found"
  | "page_not_supported"
  | "page_parse_failed"
  | "extract_failed"
  | "unknown";

export type ExtensionFlowState =
  | "idle"
  | "checking_page"
  | "checking_text_source"
  | "text_source_found"
  | "extracting_text"
  | "text_ready"
  | "sending_to_web"
  | "summarizing"
  | "summary_ready"
  | "fallback_required"
  | "page_unsupported"
  | "extract_failed"
  | "summary_failed";

export type LocalHelperFlowState =
  | "idle"
  | "checking_runtime"
  | "downloading_runtime"
  | "runtime_ready"
  | "resolving_video"
  | "downloading_audio"
  | "transcribing"
  | "uploading_bridge"
  | "completed"
  | "failed";

export interface VideoMetadata {
  platform: PlatformKind;
  videoId: string;
  url: string;
  title?: string;
  channelName?: string;
}

export interface TranscriptSegment {
  startSeconds?: number;
  endSeconds?: number;
  text: string;
}

export interface TextSourceDetectionResult {
  hasText: boolean;
  sourceType: SourceTextType;
  confidence: number;
  reason: DetectionReason;
  canFallbackToLocal: boolean;
}

export interface TranscriptEnvelope {
  schemaVersion: typeof TRANSCRIPT_SCHEMA_VERSION;
  requestId: string;
  source: {
    kind: SourceKind;
    sourceType: Exclude<SourceTextType, "none">;
    toolVersion: string;
  };
  video: VideoMetadata;
  transcript: {
    language?: string;
    text: string;
    segments: TranscriptSegment[];
    charCount: number;
  };
  diagnostics: {
    textSourceReason: DetectionReason;
    fallbackUsed: boolean;
    extensionState?: ExtensionFlowState;
    localHelperState?: LocalHelperFlowState;
    bridgeUploadAttempt?: number;
    notes?: string[];
  };
  createdAt: string;
}

/**
 * Current bridge payload shape used by the MVP extension and local helper.
 * This remains necessary until the bridge API migrates to envelope-first input.
 */
export interface BridgePayloadV1 {
  payloadId: string;
  transcript: string;
  sourceUrl: string;
  title?: string;
  createdAt?: string;
  bridgeVersion: typeof BRIDGE_PAYLOAD_VERSION_V1;
}

/**
 * Target bridge payload shape for the next contract revision.
 */
export interface BridgePayloadV2 {
  payloadId: string;
  bridgeVersion: typeof BRIDGE_PAYLOAD_VERSION_V2;
  envelope: TranscriptEnvelope;
}

export type AnyBridgePayload = BridgePayloadV1 | BridgePayloadV2;

export interface FallbackAction {
  shouldFallback: boolean;
  state: ExtensionFlowState;
  reason: DetectionReason;
  userMessage: string;
}

export function buildDetectionResult(
  partial: Partial<TextSourceDetectionResult>,
): TextSourceDetectionResult {
  const sourceType = partial.sourceType ?? "none";
  const hasText = partial.hasText ?? sourceType !== "none";
  const reason = partial.reason ?? (hasText ? "unknown" : "no_text_source_found");
  return {
    hasText,
    sourceType,
    confidence: clamp01(partial.confidence ?? (hasText ? 0.9 : 1)),
    reason,
    canFallbackToLocal: partial.canFallbackToLocal ?? (!hasText && reason === "no_text_source_found"),
  };
}

export function shouldTriggerFallback(
  detection: TextSourceDetectionResult,
  state: ExtensionFlowState,
): boolean {
  return (
    state === "fallback_required" &&
    detection.hasText === false &&
    detection.reason === "no_text_source_found" &&
    detection.canFallbackToLocal === true
  );
}

export function buildFallbackAction(
  detection: TextSourceDetectionResult,
  state: ExtensionFlowState,
): FallbackAction {
  if (shouldTriggerFallback(detection, state)) {
    return {
      shouldFallback: true,
      state,
      reason: detection.reason,
      userMessage: "This video has no directly extractable text. Use the local helper.",
    };
  }

  if (state === "extract_failed") {
    return {
      shouldFallback: false,
      state,
      reason: "extract_failed",
      userMessage: "Text likely exists, but extraction failed. Retry instead of opening the local helper.",
    };
  }

  if (state === "summary_failed") {
    return {
      shouldFallback: false,
      state,
      reason: "unknown",
      userMessage: "Transcript is ready, but summarization failed. Retry summarization.",
    };
  }

  return {
    shouldFallback: false,
    state,
    reason: detection.reason,
    userMessage: "No fallback action is required.",
  };
}

export function buildTranscriptEnvelope(input: {
  requestId: string;
  sourceKind: SourceKind;
  sourceType: Exclude<SourceTextType, "none">;
  toolVersion: string;
  video: VideoMetadata;
  transcriptText: string;
  transcriptLanguage?: string;
  transcriptSegments?: TranscriptSegment[];
  textSourceReason: DetectionReason;
  fallbackUsed?: boolean;
  extensionState?: ExtensionFlowState;
  localHelperState?: LocalHelperFlowState;
  bridgeUploadAttempt?: number;
  notes?: string[];
  createdAt?: string;
}): TranscriptEnvelope {
  const transcriptText = String(input.transcriptText || "").trim();
  const segments = input.transcriptSegments ?? [];

  return {
    schemaVersion: TRANSCRIPT_SCHEMA_VERSION,
    requestId: input.requestId,
    source: {
      kind: input.sourceKind,
      sourceType: input.sourceType,
      toolVersion: input.toolVersion,
    },
    video: input.video,
    transcript: {
      language: input.transcriptLanguage,
      text: transcriptText,
      segments,
      charCount: transcriptText.length,
    },
    diagnostics: {
      textSourceReason: input.textSourceReason,
      fallbackUsed: Boolean(input.fallbackUsed),
      extensionState: input.extensionState,
      localHelperState: input.localHelperState,
      bridgeUploadAttempt: input.bridgeUploadAttempt,
      notes: input.notes,
    },
    createdAt: input.createdAt ?? new Date().toISOString(),
  };
}

export function buildBridgePayloadV1(input: {
  payloadId: string;
  transcript: string;
  sourceUrl: string;
  title?: string;
  createdAt?: string;
}): BridgePayloadV1 {
  return {
    payloadId: input.payloadId,
    transcript: String(input.transcript || "").trim(),
    sourceUrl: String(input.sourceUrl || "").trim(),
    title: input.title?.trim(),
    createdAt: input.createdAt ?? new Date().toISOString(),
    bridgeVersion: BRIDGE_PAYLOAD_VERSION_V1,
  };
}

export function buildBridgePayloadV2(input: {
  payloadId: string;
  envelope: TranscriptEnvelope;
}): BridgePayloadV2 {
  return {
    payloadId: input.payloadId,
    bridgeVersion: BRIDGE_PAYLOAD_VERSION_V2,
    envelope: input.envelope,
  };
}

export function isBridgePayloadV2(payload: AnyBridgePayload): payload is BridgePayloadV2 {
  return (
    payload.bridgeVersion === BRIDGE_PAYLOAD_VERSION_V2 &&
    typeof (payload as BridgePayloadV2).envelope === "object"
  );
}

export function isBridgePayloadV1(payload: AnyBridgePayload): payload is BridgePayloadV1 {
  return (
    payload.bridgeVersion === BRIDGE_PAYLOAD_VERSION_V1 &&
    typeof (payload as BridgePayloadV1).transcript === "string"
  );
}

function clamp01(value: number): number {
  if (value < 0) {
    return 0;
  }
  if (value > 1) {
    return 1;
  }
  return value;
}
