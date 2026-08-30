import { afterEach, describe, expect, it, vi } from "vitest";

import {
  fetchRichGuide,
  generateRichGuide,
  RichGuideRequestError,
} from "./rich-guide";

const item = {
  poem_id: "poem/1",
  story: "诗歌背景",
  notes: [{ original: "明月", translation: "明亮的月", annotations: ["月：月亮"] }],
  ap: ["情景交融"],
  batch: "auto",
  hw: false,
  anchor_tier: "verified",
  sources: [{ reference_id: "R1", name: "资料", url: "https://example.com" }],
  reference_mode: "reviewed_references",
};

afterEach(() => vi.unstubAllGlobals());

describe("rich guide client contract", () => {
  it("queries an encoded poem id and accepts an existing guide", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      status: "exists", source: "llm", batch: "batch_auto_001", item,
    }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchRichGuide(" poem/1 ")).resolves.toMatchObject({ status: "exists", item });
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/backend/knowledge/rich-guide?poem_id=poem%2F1",
      expect.objectContaining({ cache: "no-store" }),
    );
  });

  it("posts the backend body and accepts a generated guide", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      status: "generated", source: "llm", batch: "batch_auto_001", item,
    }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(generateRichGuide(" poem/1 ")).resolves.toMatchObject({ status: "generated" });
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/backend/knowledge/rich-guide",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ poem_id: "poem/1" }),
      }),
    );
  });

  it.each([
    [404, { status: "not_found", reason: "poem_id 不在知识库" }],
    [503, { status: "unavailable", reason: "missing_env", missing: ["AGENT_LLM_API_KEY"] }],
  ])("preserves a %s backend error", async (statusCode, payload) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      new Response(JSON.stringify(payload), { status: statusCode }),
    ));

    const error = await generateRichGuide("p1").catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(RichGuideRequestError);
    expect(error).toMatchObject({ statusCode, status: payload.status, payload });
  });

  it("turns network failures into an identifiable client error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("fetch failed")));

    await expect(fetchRichGuide("p1")).rejects.toMatchObject({
      statusCode: 0,
      status: "network_error",
      message: "fetch failed",
    });
  });

  it.each([
    new Response("not json", { status: 200 }),
    new Response(JSON.stringify({ status: "exists", item: {} }), { status: 200 }),
  ])("rejects an illegal successful response", async (response) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response));

    await expect(fetchRichGuide("p1")).rejects.toMatchObject({
      statusCode: 200,
      status: "invalid_response",
    });
  });
});
