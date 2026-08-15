import { proxyBackend } from "@/lib/backend";

export const dynamic = "force-dynamic";

export async function GET(
  _request: Request,
  context: { params: Promise<{ id: string }> },
) {
  const { id } = await context.params;
  return proxyBackend(`/knowledge/poems/${encodeURIComponent(id)}`);
}
