import type {
  KnowledgePoemPayload,
  KnowledgeGlossarySelectionPayload,
  KnowledgeGlossarySelectionRequest,
  KnowledgeSearchPayload,
  KnowledgeSearchMode,
  KnowledgeStatusPayload,
  ToolResponse,
} from "@/lib/types";

async function readKnowledgeJson<T>(response: Response): Promise<ToolResponse<T>> {
  const data = (await response.json()) as ToolResponse<T>;
  if (!response.ok) {
    const payload = data.payload as { error?: string } | undefined;
    throw new Error(payload?.error ?? `知识库请求失败（${response.status}）`);
  }
  if (data.status !== "ok") {
    const payload = data.payload as { error?: string; notFound?: boolean } | undefined;
    throw new Error(
      payload?.notFound ? "该诗篇不在当前知识库中" : payload?.error ?? "知识库当前不可用",
    );
  }
  return data;
}

export interface KnowledgeSearchRequest {
  query?: string;
  poet?: string;
  dynasty?: string;
  imagery?: string;
  emotion?: string;
  scope?: "poem" | "line" | "all";
  limit?: number;
  offset?: number;
  mode?: KnowledgeSearchMode;
}

export function buildKnowledgeSearchParams(request: KnowledgeSearchRequest): URLSearchParams {
  const params = new URLSearchParams();
  const fields = ["query", "poet", "dynasty", "imagery", "emotion", "scope", "mode"] as const;
  for (const field of fields) {
    const value = request[field];
    if (typeof value === "string" && value.trim()) params.set(field, value.trim());
  }
  params.set("limit", String(request.limit ?? 20));
  params.set("offset", String(request.offset ?? 0));
  return params;
}

export async function searchKnowledge(
  request: KnowledgeSearchRequest,
  signal?: AbortSignal,
): Promise<ToolResponse<KnowledgeSearchPayload>> {
  const params = buildKnowledgeSearchParams(request);
  const response = await fetch(`/api/backend/knowledge/search?${params}`, {
    cache: "no-store",
    signal,
  });
  return readKnowledgeJson<KnowledgeSearchPayload>(response);
}

export async function fetchKnowledgePoem(
  poemId: string,
  signal?: AbortSignal,
): Promise<ToolResponse<KnowledgePoemPayload>> {
  const response = await fetch(
    `/api/backend/knowledge/poems/${encodeURIComponent(poemId)}`,
    { cache: "no-store", signal },
  );
  return readKnowledgeJson<KnowledgePoemPayload>(response);
}

export async function fetchKnowledgeStatus(
  signal?: AbortSignal,
): Promise<ToolResponse<KnowledgeStatusPayload>> {
  const response = await fetch("/api/backend/knowledge/status", {
    cache: "no-store",
    signal,
  });
  return readKnowledgeJson<KnowledgeStatusPayload>(response);
}

export async function explainGlossarySelection(
  request: KnowledgeGlossarySelectionRequest,
  signal?: AbortSignal,
): Promise<ToolResponse<KnowledgeGlossarySelectionPayload>> {
  const response = await fetch("/api/backend/knowledge/glosses/selection", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(request),
    cache: "no-store",
    signal,
  });
  return readKnowledgeJson<KnowledgeGlossarySelectionPayload>(response);
}

export function knowledgeTagLabel(value: { label?: string; id?: string } | string): string {
  return typeof value === "string" ? value : value.label ?? value.id ?? "";
}
