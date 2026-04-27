# Bridge Contract Migration Guide

## Goal

This document freezes the contract between:

- `chrome_extension_mvp`
- `bridge_api.py`
- the web app
- `local_cli_mvp`

The current system already works with a simple bridge payload, but that payload
is too thin for long-term maintenance. The goal is to keep today's flow working
while defining a clean migration path to an envelope-based contract.

---

## 1. Current Reality

Today the extension and local helper mainly send this shape:

```json
{
  "payloadId": "uuid",
  "transcript": "full transcript text",
  "sourceUrl": "https://www.youtube.com/watch?v=...",
  "title": "Video title",
  "createdAt": "2026-04-23T15:00:00Z",
  "bridgeVersion": 1
}
```

This is enough to pass transcript text through the bridge, but it has 4 major
problems:

1. The web app cannot reliably tell whether the text came from extension or local ASR.
2. There is no normalized diagnostic context.
3. There is no stable request correlation across systems.
4. Future features like segment timelines or richer provenance will be painful.

So the current contract should be treated as `compat mode`, not the final shape.

---

## 2. Target Direction

The target contract is:

- keep `bridgeVersion = 1` support for compatibility
- introduce `bridgeVersion = 2`
- make `TranscriptEnvelope` the canonical payload unit

The TypeScript source of truth is:

- [transcript_contracts.ts](file:///d:/Program%20Files/Trae/YouTubeSummarizer/shared/transcript_contracts.ts)

---

## 3. Contract Layers

### 3.1 Text Source Detection Result

Produced by the extension before extraction finishes.

```ts
interface TextSourceDetectionResult {
  hasText: boolean;
  sourceType: "subtitle" | "transcript" | "subtitle_and_transcript" | "local_asr" | "manual_text" | "none";
  confidence: number;
  reason:
    | "subtitle_panel_available"
    | "transcript_panel_available"
    | "subtitle_and_transcript_available"
    | "no_text_source_found"
    | "page_not_supported"
    | "page_parse_failed"
    | "extract_failed"
    | "unknown";
  canFallbackToLocal: boolean;
}
```

### 3.2 Transcript Envelope

Canonical transcript container shared by all systems.

```ts
interface TranscriptEnvelope {
  schemaVersion: "1.0";
  requestId: string;
  source: {
    kind: "extension" | "local_tool" | "manual_paste";
    sourceType: "subtitle" | "transcript" | "subtitle_and_transcript" | "local_asr" | "manual_text";
    toolVersion: string;
  };
  video: {
    platform: "youtube";
    videoId: string;
    url: string;
    title?: string;
    channelName?: string;
  };
  transcript: {
    language?: string;
    text: string;
    segments: Array<{ startSeconds?: number; endSeconds?: number; text: string }>;
    charCount: number;
  };
  diagnostics: {
    textSourceReason: string;
    fallbackUsed: boolean;
    extensionState?: string;
    localHelperState?: string;
    bridgeUploadAttempt?: number;
    notes?: string[];
  };
  createdAt: string;
}
```

### 3.3 Bridge Payload V1

Current compatibility layer.

```ts
interface BridgePayloadV1 {
  payloadId: string;
  transcript: string;
  sourceUrl: string;
  title?: string;
  createdAt?: string;
  bridgeVersion: 1;
}
```

### 3.4 Bridge Payload V2

Target shape.

```ts
interface BridgePayloadV2 {
  payloadId: string;
  bridgeVersion: 2;
  envelope: TranscriptEnvelope;
}
```

---

## 4. Fallback Rules

The single most important product rule:

- local helper fallback is only allowed when `reason = "no_text_source_found"`

It must **not** trigger when:

- the page is unsupported
- transcript extraction failed
- summarization failed

If this line gets blurred, the product starts using local tooling to hide bugs.

That is a serious product design failure, not a minor UX issue.

---

## 5. Endpoint Contract

## 5.1 Health Check

```http
GET /health
```

Expected fields:

```json
{
  "ok": true,
  "service": "transcript-bridge"
}
```

Optional fields may include backend diagnostics.

## 5.2 Create Payload

Current accepted request:

```http
POST /api/bridge/payload
Content-Type: application/json
```

Accepted body today:

- `BridgePayloadV1`

Accepted body after migration:

- `BridgePayloadV1`
- `BridgePayloadV2`

Response:

```json
{
  "ok": true,
  "payload_id": "uuid",
  "expires_in": 900
}
```

## 5.3 Get Payload

```http
GET /api/bridge/payload?payload_id=uuid&consume=1
```

Current response can stay permissive, but the target response should always wrap
the transcript in a canonical structure:

```json
{
  "ok": true,
  "payload_id": "uuid",
  "bridge_version": 2,
  "envelope": {
    "schemaVersion": "1.0",
    "requestId": "req_123",
    "source": {
      "kind": "local_tool",
      "sourceType": "local_asr",
      "toolVersion": "local-helper-0.1.0"
    },
    "video": {
      "platform": "youtube",
      "videoId": "abc123",
      "url": "https://www.youtube.com/watch?v=abc123",
      "title": "Demo Video"
    },
    "transcript": {
      "language": "en",
      "text": "full transcript content",
      "segments": [],
      "charCount": 2048
    },
    "diagnostics": {
      "textSourceReason": "no_text_source_found",
      "fallbackUsed": true
    },
    "createdAt": "2026-04-23T15:00:00Z"
  }
}
```

---

## 6. Migration Plan

## Phase 1

- keep `bridge_api.py` fully compatible with V1
- add shared contract definitions
- update docs and internal field names

## Phase 2

- teach extension and local helper to optionally emit `BridgePayloadV2`
- keep bridge response backward-compatible

## Phase 3

- make the web app prefer `envelope`
- fall back to V1 fields only when `envelope` is absent

## Phase 4

- stop creating new V1 payloads
- keep V1 reading only for temporary backward compatibility

---

## 7. Recommended Immediate Engineering Tasks

### Extension

- emit `TextSourceDetectionResult`
- stop mixing `no transcript` with `extract failed`
- generate a stable `requestId`

### Local Helper

- construct `TranscriptEnvelope` before bridge upload
- keep saving local transcript even if bridge fails

### Bridge API

- accept both `BridgePayloadV1` and `BridgePayloadV2`
- normalize stored data internally

### Web App

- consume `TranscriptEnvelope`
- use `source.kind` and `source.sourceType` in analytics and UI

---

## 8. Non-Negotiable Rules

1. Do not use local fallback to hide extension extraction bugs.
2. Do not keep expanding the payload with ad-hoc top-level fields.
3. Do not treat raw transcript text as a complete business object.

If those rules are broken, the integration will become fragile again.
