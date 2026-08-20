import { proxyBackend } from "@/lib/backend";

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  return proxyBackend("/knowledge/glosses/selection", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: await request.text(),
  });
}
