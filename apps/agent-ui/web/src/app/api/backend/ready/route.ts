import { proxyBackend } from "@/lib/backend";

export const dynamic = "force-dynamic";

export async function GET() {
  return proxyBackend("/ready");
}
