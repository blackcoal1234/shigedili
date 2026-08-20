import { describe, expect, it, vi } from "vitest";

import { buildKnowledgeSearchParams, explainGlossarySelection, knowledgeTagLabel } from "./knowledge";

describe("knowledge client contracts", () => {
  it("serializes trimmed composable filters and pagination", () => {
    const params = buildKnowledgeSearchParams({
      query: "  明月  ",
      poet: " 李白 ",
      imagery: "月",
      mode: "hybrid",
      scope: "line",
      limit: 12,
      offset: 24,
    });
    expect(params.get("query")).toBe("明月");
    expect(params.get("poet")).toBe("李白");
    expect(params.get("imagery")).toBe("月");
    expect(params.get("scope")).toBe("line");
    expect(params.get("mode")).toBe("hybrid");
    expect(params.get("limit")).toBe("12");
    expect(params.get("offset")).toBe("24");
  });

  it("keeps legacy requests compatible when no vector mode is supplied", () => {
    const params = buildKnowledgeSearchParams({ query: "明月" });
    expect(params.has("mode")).toBe(false);
  });

  it("normalizes both compact strings and structured tags", () => {
    expect(knowledgeTagLabel("离愁")).toBe("离愁");
    expect(knowledgeTagLabel({ id: "longing", label: "思念" })).toBe("思念");
  });

  it("serializes an online glossary selection request", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: "ok", payload: { term: "关山", definition: "边地", method: "llm_web", reviewStatus: "published" } }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await explainGlossarySelection({ poemId: "p1", lineNo: 2, startOffset: 3, endOffset: 5, mode: "web" });

    expect(fetchMock).toHaveBeenCalledWith("/api/backend/knowledge/glosses/selection", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ poemId: "p1", lineNo: 2, startOffset: 3, endOffset: 5, mode: "web" }),
    }));
  });

  it("surfaces backend and protocol errors", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ payload: { error: "拒绝" } }), { status: 400 })));
    await expect(explainGlossarySelection({ poemId: "p1", lineNo: 1, startOffset: 0, endOffset: 1, mode: "model" })).rejects.toThrow("拒绝");

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: "source_error", payload: { error: "不可用" } }), { status: 200 })));
    await expect(explainGlossarySelection({ poemId: "p1", lineNo: 1, startOffset: 0, endOffset: 1, mode: "model" })).rejects.toThrow("不可用");
  });
});
