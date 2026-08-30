import { beforeEach, describe, expect, it, vi } from "vitest";

const { proxyBackend } = vi.hoisted(() => ({ proxyBackend: vi.fn() }));

vi.mock("@/lib/backend", () => ({ proxyBackend }));

import { GET, POST } from "./route";

describe("rich guide backend proxy", () => {
  beforeEach(() => {
    proxyBackend.mockReset();
    proxyBackend.mockResolvedValue(new Response(null, { status: 204 }));
  });

  it("maps the GET query to the encoded backend path", async () => {
    await GET(new Request(
      "http://localhost/api/backend/knowledge/rich-guide?poem_id=poem%2F1",
    ));

    expect(proxyBackend).toHaveBeenCalledWith("/knowledge/rich-guide/poem%2F1");
  });

  it("returns an identifiable 400 without a poem id", async () => {
    const response = await GET(new Request(
      "http://localhost/api/backend/knowledge/rich-guide",
    ));

    expect(response.status).toBe(400);
    await expect(response.json()).resolves.toEqual({
      status: "invalid_request",
      reason: "poem_id_required",
    });
    expect(proxyBackend).not.toHaveBeenCalled();
  });

  it("forwards the POST body unchanged", async () => {
    const body = JSON.stringify({ poem_id: "p1" });
    await POST(new Request("http://localhost/api/backend/knowledge/rich-guide", {
      method: "POST",
      body,
    }));

    expect(proxyBackend).toHaveBeenCalledWith("/knowledge/rich-guide", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body,
    });
  });
});
