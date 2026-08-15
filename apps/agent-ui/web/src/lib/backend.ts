import { NextResponse } from "next/server";

export const BACKEND_URL = (
  process.env.POETRY_AGENT_BACKEND_URL ?? "http://127.0.0.1:8123"
).replace(/\/$/, "");

export async function proxyBackend(path: string, init?: RequestInit): Promise<Response> {
  try {
    const response = await fetch(`${BACKEND_URL}${path}`, {
      ...init,
      cache: "no-store",
      headers: {
        accept: "application/json",
        ...(init?.headers ?? {}),
      },
      signal: AbortSignal.timeout(30_000),
    });
    const body = await response.arrayBuffer();
    return new Response(body, {
      status: response.status,
      headers: {
        "content-type": response.headers.get("content-type") ?? "application/json; charset=utf-8",
        "cache-control": "no-store",
      },
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Backend request failed";
    return NextResponse.json(
      {
        status: "source_error",
        schemaVersion: "proxy-1",
        sourceHashes: {},
        methodNote: "Python 数据服务未响应，未使用替代数据。",
        payload: { error: message },
      },
      { status: 502 },
    );
  }
}
