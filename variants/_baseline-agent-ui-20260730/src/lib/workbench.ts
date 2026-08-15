import type {
  ImageryPayload,
  PoetCatalog,
  RoutePayload,
  ScenePayload,
  ToolResponse,
  WorkbenchMode,
  WorkbenchPayload,
} from "@/lib/types";

export const MODE_TOOL = {
  route: "generate_poet_route",
  scenes: "play_poem_scenes",
  imagery: "compare_imagery",
} as const satisfies Record<WorkbenchMode, string>;

export const MODE_LABEL = {
  route: "诗人行迹",
  scenes: "逐幕诗篇",
  imagery: "唐宋意象",
} as const satisfies Record<WorkbenchMode, string>;

export function buildToolBody(mode: WorkbenchMode, poet: string): Record<string, unknown> {
  switch (mode) {
    case "route":
      return { poet, include_approximate: true, include_disputed: true };
    case "scenes":
      return { poet, autoplay: false };
    case "imagery":
      return { limit: 8 };
  }
}

export function scenePlaybackDelayMs(readSeconds: number | undefined): number {
  const seconds = Number.isFinite(readSeconds) ? Number(readSeconds) : 12;
  return Math.min(60_000, Math.max(1_000, seconds * 1_000));
}

async function readJson<T>(response: Response): Promise<T> {
  const data = (await response.json()) as T;
  if (!response.ok) {
    const payload = data as { payload?: { error?: string }; error?: string };
    throw new Error(payload.payload?.error ?? payload.error ?? `请求失败（${response.status}）`);
  }
  return data;
}

export async function fetchCatalog(signal?: AbortSignal): Promise<ToolResponse<PoetCatalog>> {
  const response = await fetch("/api/backend/catalog", {
    cache: "no-store",
    signal,
  });
  return readJson<ToolResponse<PoetCatalog>>(response);
}

export async function fetchWorkbenchMode(
  mode: WorkbenchMode,
  poet: string,
  signal?: AbortSignal,
): Promise<ToolResponse<WorkbenchPayload>> {
  const response = await fetch(`/api/backend/tools/${MODE_TOOL[mode]}`, {
    method: "POST",
    cache: "no-store",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(buildToolBody(mode, poet)),
    signal,
  });
  return readJson<ToolResponse<WorkbenchPayload>>(response);
}

export function payloadError(response: ToolResponse<WorkbenchPayload>): string | null {
  if (response.status === "ok" || response.status === "insufficient_evidence") {
    return null;
  }
  const payload = response.payload as { error?: unknown };
  return typeof payload.error === "string" ? payload.error : "数据服务返回异常状态";
}

export function isRoutePayload(payload: WorkbenchPayload): payload is RoutePayload {
  return "routeSegments" in payload;
}

export function isScenePayload(payload: WorkbenchPayload): payload is ScenePayload {
  return "mode" in payload && "scenes" in payload && !isRoutePayload(payload);
}

export function isImageryPayload(payload: WorkbenchPayload): payload is ImageryPayload {
  return "comparisons" in payload;
}
