import { NextResponse } from "next/server";

import { proxyBackend } from "@/lib/backend";

const TOOL_NAMES = new Set([
  "generate_poet_route",
  "play_poem_scenes",
  "compare_imagery",
  "search_poetry_knowledge",
  "get_poem_knowledge",
  "get_line_knowledge",
]);

export async function POST(
  request: Request,
  context: { params: Promise<{ name: string }> },
) {
  const { name } = await context.params;
  if (!TOOL_NAMES.has(name)) {
    return NextResponse.json({ error: "Unknown tool" }, { status: 404 });
  }

  return proxyBackend(`/tools/${name}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: await request.text(),
  });
}
