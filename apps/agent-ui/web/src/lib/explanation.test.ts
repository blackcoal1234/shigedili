import { describe, expect, it } from "vitest";

import { createExplanationModel } from "./explanation";
import type { ImageryPayload, RoutePayload, ScenePayload } from "./types";

const scene = {
  id: "scene-1",
  year_label: "759",
} as RoutePayload["scenes"][number];

describe("payload-only explanation models", () => {
  it("derives route metrics without inventing points", () => {
    const payload = {
      poet: "李白",
      dynasty: "唐",
      corpusWorkCount: 55,
      sceneCount: 2,
      mappedSceneCount: 1,
      precisionCounts: { exact: 1, disputed: 1 },
      scenes: [scene, { ...scene, id: "scene-2", year_label: "762" }],
      routeSegments: [],
      visualTransitions: [],
    } as RoutePayload;
    const model = createExplanationModel("route", payload);
    expect(model.metric).toBe("1/2");
    expect(model.points.map((point) => point.label)).toEqual(["759", "762"]);
  });

  it("summarizes scene bounds from the returned sequence", () => {
    const payload = {
      poet: "杜甫",
      dynasty: "唐",
      corpusWorkCount: 20,
      sceneCount: 2,
      mappedSceneCount: 2,
      scenes: [scene, { ...scene, id: "scene-2", year_label: "770" }],
      mode: "manual_step",
      pauseAtEachScene: true,
    } as ScenePayload;
    expect(createExplanationModel("scenes", payload).notes[0]).toBe("759 至 770");
  });

  it("normalizes imagery points against values already in the payload", () => {
    const payload = {
      selectionRule: "fixture",
      requestedLimit: 1,
      terms: ["月"],
      allowedTermCount: 160,
      comparisons: [{
        word: "月",
        category: "天象",
        higherIn: "唐",
        deltaSongMinusTang: -2,
        absoluteDelta: 2,
        tang: { rawHits: 2, ratePer10k: 4, chineseCharDenominator: 5_000, poemRecords: 2, poemsWithHit: 2 },
        song: { rawHits: 1, ratePer10k: 2, chineseCharDenominator: 5_000, poemRecords: 1, poemsWithHit: 1 },
        corpusEvidence: [],
      }],
    } as ImageryPayload;
    const model = createExplanationModel("imagery", payload);
    expect(model.metric).toBe("1");
    expect(model.points).toEqual([{ label: "月", value: 1 }]);
  });
});
