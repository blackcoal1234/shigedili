import {
  CopilotRuntime,
  copilotRuntimeNextJSAppRouterEndpoint,
} from "@copilotkit/runtime";
import { HttpAgent } from "@ag-ui/client";

import { BACKEND_URL } from "@/lib/backend";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const copilotRuntime = new CopilotRuntime({
  agents: {
    poetry_evidence_agent: new HttpAgent({ url: `${BACKEND_URL}/` }),
  },
});

const { handleRequest } = copilotRuntimeNextJSAppRouterEndpoint({
  runtime: copilotRuntime,
  endpoint: "/api/copilotkit",
});

export const GET = handleRequest;
export const POST = handleRequest;
export const OPTIONS = handleRequest;
