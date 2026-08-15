import { proxyBackend } from "@/lib/backend";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const url = new URL(request.url);
  const safe = new URLSearchParams();
  for (const key of [
    "query", "poet", "dynasty", "imagery", "emotion", "mode", "scope", "limit", "offset",
  ]) {
    const value = url.searchParams.get(key);
    if (value !== null) safe.set(key, value);
  }
  return proxyBackend(`/knowledge/search?${safe.toString()}`);
}
