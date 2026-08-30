import { NextResponse } from "next/server";

import { proxyBackend } from "@/lib/backend";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const poemId = new URL(request.url).searchParams.get("poem_id")?.trim();
  if (!poemId) {
    return NextResponse.json(
      { status: "invalid_request", reason: "poem_id_required" },
      { status: 400 },
    );
  }
  return proxyBackend(`/knowledge/rich-guide/${encodeURIComponent(poemId)}`);
}

export async function POST(request: Request) {
  return proxyBackend("/knowledge/rich-guide", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: await request.text(),
  });
}
