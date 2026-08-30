export type RichGuideSource = "hand" | "llm";
export type RichGuideAnchorTier = "verified" | "rule" | "ai" | "none";
export type RichGuideReferenceMode =
  | "reviewed_references"
  | "poem_only"
  | "legacy_unconstrained";

export interface RichGuideNote {
  original: string;
  translation: string;
  annotations: string[];
}

export interface RichGuideSourceReference {
  reference_id: string;
  name: string;
  url: string;
}

export interface RichGuideItem {
  poem_id: string;
  story: string;
  notes: RichGuideNote[];
  ap: string[];
  batch: "auto" | null;
  hw: boolean;
  anchor_tier: RichGuideAnchorTier;
  sources: RichGuideSourceReference[];
  reference_mode?: RichGuideReferenceMode;
}

export interface RichGuideAbsentResponse {
  status: "absent";
  poem_id: string;
}

export interface RichGuideAvailableResponse {
  status: "exists" | "generated";
  source: RichGuideSource;
  batch: string;
  item: RichGuideItem;
}

export type RichGuideResponse = RichGuideAbsentResponse | RichGuideAvailableResponse;

export type RichGuideErrorStatus =
  | "invalid_request"
  | "not_found"
  | "unavailable"
  | "upstream_error"
  | "quality_failed"
  | "source_error"
  | "network_error"
  | "invalid_response";

export interface RichGuideErrorPayload {
  status: RichGuideErrorStatus | string;
  reason?: string;
  missing?: string[];
  errors?: string[];
  payload?: { error?: string };
}

export class RichGuideRequestError extends Error {
  constructor(
    message: string,
    public readonly statusCode: number,
    public readonly status: RichGuideErrorStatus | string,
    public readonly payload?: RichGuideErrorPayload,
  ) {
    super(message);
    this.name = "RichGuideRequestError";
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((entry) => typeof entry === "string");
}

function isRichGuideItem(value: unknown): value is RichGuideItem {
  if (!isRecord(value)) return false;
  const validNotes = Array.isArray(value.notes) && value.notes.every((note) =>
    isRecord(note)
    && typeof note.original === "string"
    && typeof note.translation === "string"
    && isStringArray(note.annotations));
  const validSources = Array.isArray(value.sources) && value.sources.every((source) =>
    isRecord(source)
    && typeof source.reference_id === "string"
    && typeof source.name === "string"
    && typeof source.url === "string");
  return typeof value.poem_id === "string"
    && typeof value.story === "string"
    && validNotes
    && isStringArray(value.ap)
    && (value.batch === "auto" || value.batch === null)
    && typeof value.hw === "boolean"
    && ["verified", "rule", "ai", "none"].includes(String(value.anchor_tier))
    && validSources
    && (value.reference_mode === undefined
      || ["reviewed_references", "poem_only", "legacy_unconstrained"].includes(
        String(value.reference_mode),
      ));
}

function isRichGuideResponse(value: unknown): value is RichGuideResponse {
  if (!isRecord(value)) return false;
  if (value.status === "absent") return typeof value.poem_id === "string";
  return (value.status === "exists" || value.status === "generated")
    && (value.source === "hand" || value.source === "llm")
    && typeof value.batch === "string"
    && isRichGuideItem(value.item);
}

function errorMessage(payload: RichGuideErrorPayload, statusCode: number): string {
  return payload.reason
    ?? payload.payload?.error
    ?? payload.errors?.[0]
    ?? `译注赏析请求失败（${statusCode}）`;
}

async function requestRichGuide(url: string, init?: RequestInit): Promise<RichGuideResponse> {
  let response: Response;
  try {
    response = await fetch(url, { ...init, cache: "no-store" });
  } catch (error) {
    const message = error instanceof Error ? error.message : "网络请求失败";
    throw new RichGuideRequestError(message, 0, "network_error");
  }

  let data: unknown;
  try {
    data = await response.json();
  } catch {
    throw new RichGuideRequestError(
      `译注赏析服务返回了非法响应（${response.status}）`,
      response.status,
      "invalid_response",
    );
  }

  if (!response.ok) {
    const payload: RichGuideErrorPayload = isRecord(data)
      ? {
          status: typeof data.status === "string" ? data.status : "invalid_response",
          ...(typeof data.reason === "string" ? { reason: data.reason } : {}),
          ...(isStringArray(data.missing) ? { missing: data.missing } : {}),
          ...(isStringArray(data.errors) ? { errors: data.errors } : {}),
          ...(isRecord(data.payload) && typeof data.payload.error === "string"
            ? { payload: { error: data.payload.error } }
            : {}),
        }
      : { status: "invalid_response" };
    throw new RichGuideRequestError(
      errorMessage(payload, response.status),
      response.status,
      payload.status,
      payload,
    );
  }

  if (!isRichGuideResponse(data)) {
    throw new RichGuideRequestError(
      "译注赏析服务返回了不符合契约的数据",
      response.status,
      "invalid_response",
    );
  }
  return data;
}

export function fetchRichGuide(
  poemId: string,
  signal?: AbortSignal,
): Promise<RichGuideResponse> {
  const params = new URLSearchParams({ poem_id: poemId.trim() });
  return requestRichGuide(`/api/backend/knowledge/rich-guide?${params}`, { signal });
}

export function generateRichGuide(
  poemId: string,
  signal?: AbortSignal,
): Promise<RichGuideResponse> {
  return requestRichGuide("/api/backend/knowledge/rich-guide", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ poem_id: poemId.trim() }),
    signal,
  });
}
