import { describe, expect, it } from "vitest";

import { buildKnowledgeSearchParams, knowledgeTagLabel } from "./knowledge";

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
});
