import { describe, expect, it } from "vitest";

import {
  clampSceneIndex,
  easeInOutCubic,
  interpolateJourneyPath,
  journeyPayloadKey,
  resolveJourneyLeg,
  revealDelayMs,
  sampleJourneyPath,
} from "./journey";
import type { RouteSegment } from "./types";

const documentedSegment: RouteSegment = {
  from_id: "a",
  to_id: "b",
  coords: [[108, 30], [112, 34]],
  kind: "chronology",
  certainty: "strict",
  historical_claim: true,
  transport_mode: "boat",
  transport_label: "舟船",
  transport_basis: "来源文字：乘舟东下",
  transport_certainty: "documented",
};

const visualTransition: RouteSegment = {
  from_id: "a",
  to_id: "b",
  coords: [[108, 30], [112, 34]],
  kind: "visual_transition",
  certainty: "not_asserted",
  historical_claim: false,
  gap_reason: "adjacent_locatable_scene_gap",
  transport_mode: "journey",
  transport_label: "山径行旅",
  transport_basis: "实际行路与交通方式未载，仅作镜头转场。",
  transport_certainty: "unspecified",
};

const scene = (id: string, lon: number | null, lat: number | null) => ({
  id,
  lon,
  lat,
  map_eligible: lon !== null && lat !== null,
});

describe("journey state helpers", () => {
  it("prefers a forward historical segment over a visual transition", () => {
    const leg = resolveJourneyLeg(
      [documentedSegment],
      [visualTransition],
      scene("a", 108, 30),
      scene("b", 112, 34),
    );

    expect(leg).toMatchObject({
      kind: "historical_route",
      historical_claim: true,
      transport_mode: "boat",
    });
  });

  it("uses a Tool visual transition when history has no direct edge", () => {
    const leg = resolveJourneyLeg(
      [],
      [visualTransition],
      scene("a", 108, 30),
      scene("b", 112, 34),
    );

    expect(leg).toMatchObject({
      kind: "camera_transition",
      historical_claim: false,
      transport_mode: "journey",
      source: "tool_visual_transition",
    });
  });

  it("turns reverse history navigation into a camera transition", () => {
    const leg = resolveJourneyLeg(
      [documentedSegment],
      [],
      scene("b", 112, 34),
      scene("a", 108, 30),
    );

    expect(leg).toMatchObject({
      from_id: "b",
      to_id: "a",
      coords: [[112, 34], [108, 30]],
      kind: "camera_transition",
      historical_claim: false,
      transport_mode: "journey",
      source: "reverse_history_view",
    });
    expect(documentedSegment.coords).toEqual([[108, 30], [112, 34]]);
  });

  it("does not create a leg when either scene lacks coordinates", () => {
    expect(resolveJourneyLeg(
      [documentedSegment],
      [],
      scene("a", 108, 30),
      scene("b", null, null),
    )).toBeUndefined();
  });

  it("samples a deterministic curved path with exact endpoints", () => {
    const leg = resolveJourneyLeg(
      [documentedSegment],
      [],
      scene("a", 108, 30),
      scene("b", 112, 34),
    );
    expect(leg).toBeDefined();

    const first = sampleJourneyPath(leg!);
    const second = sampleJourneyPath(leg!);
    expect(first).toEqual(second);
    expect(first).toHaveLength(28);
    expect(first[0]).toEqual([108, 30]);
    expect(first.at(-1)).toEqual([112, 34]);
    const midpoint = first[14] as [number, number];
    expect(midpoint[0] - 108).not.toBeCloseTo(midpoint[1] - 30, 5);
    expect(interpolateJourneyPath(first, 0)).toEqual([108, 30]);
    expect(interpolateJourneyPath(first, 1)).toEqual([112, 34]);
  });

  it("uses easeInOutCubic without overshooting", () => {
    expect(easeInOutCubic(-1)).toBe(0);
    expect(easeInOutCubic(0)).toBe(0);
    expect(easeInOutCubic(0.5)).toBe(0.5);
    expect(easeInOutCubic(1)).toBe(1);
    expect(easeInOutCubic(2)).toBe(1);
    expect(easeInOutCubic(0.25)).toBeLessThan(0.25);
    expect(easeInOutCubic(0.75)).toBeGreaterThan(0.75);
  });

  it("uses punctuation-aware reveal pauses", () => {
    expect(revealDelayMs("山")).toBe(38);
    expect(revealDelayMs("，")).toBe(115);
    expect(revealDelayMs("。")).toBe(230);
    expect(revealDelayMs("\n")).toBe(160);
  });

  it("clamps scene indices", () => {
    expect(clampSceneIndex(-1, 6)).toBe(0);
    expect(clampSceneIndex(9, 6)).toBe(5);
    expect(clampSceneIndex(2, 0)).toBe(0);
  });

  it("keys playback by both historical and visual Tool data", () => {
    const route = {
      poet: "李白",
      scenes: [{ id: "a" }, { id: "b" }],
      routeSegments: [documentedSegment],
      visualTransitions: [visualTransition],
    };

    expect(journeyPayloadKey(route)).toBe("李白::a,b::h:a>b::v:a>b");
    expect(journeyPayloadKey({ ...route, visualTransitions: [] }))
      .not.toBe(journeyPayloadKey(route));
  });
});
