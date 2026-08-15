import { describe, expect, it } from "vitest";

import {
  freezeRouteArrival,
  getRouteMotionPolicy,
  remainingMotionDelayMs,
  revealJourneyPath,
  routeArrivalMotionProfile,
  routeTravelDurationMs,
  shouldAnimateJourneyLeg,
} from "./routeMotion";
import type { JourneyCoordinate, JourneyLeg } from "./journey";

const historicalLeg: JourneyLeg = {
  from_id: "a",
  to_id: "b",
  coords: [[108, 30], [112, 34]],
  kind: "historical_route",
  certainty: "strict",
  historical_claim: true,
  source: "historical_segment",
  transport_mode: "boat",
  transport_label: "舟船",
  transport_basis: "来源文字：乘舟东下",
  transport_certainty: "documented",
};

const cameraLeg: JourneyLeg = {
  ...historicalLeg,
  kind: "camera_transition",
  certainty: "not_asserted",
  historical_claim: false,
  source: "tool_visual_transition",
  transport_mode: "journey",
  transport_label: "山径行旅",
  transport_basis: "实际行路与交通方式未载，仅作镜头转场。",
  transport_certainty: "unspecified",
};

describe("route motion policy", () => {
  it("reveals only the travelled portion of a Tool-derived path", () => {
    const path: JourneyCoordinate[] = [
      [0, 0],
      [10, 0],
      [20, 0],
    ];

    expect(revealJourneyPath(path, 0)).toEqual([[0, 0], [0, 0]]);
    expect(revealJourneyPath(path, 0.25)).toEqual([[0, 0], [5, 0]]);
    expect(revealJourneyPath(path, 0.75)).toEqual([[0, 0], [10, 0], [15, 0]]);
    expect(revealJourneyPath(path, 2)).toEqual(path);
  });

  it("keeps camera-only gaps out of geographic travel", () => {
    expect(shouldAnimateJourneyLeg(historicalLeg)).toBe(true);
    expect(shouldAnimateJourneyLeg(cameraLeg)).toBe(false);
    expect(shouldAnimateJourneyLeg(undefined)).toBe(false);
  });

  it("maps profiles to distinct arrival layers and an immediate off state", () => {
    expect(getRouteMotionPolicy("off")).toMatchObject({
      bypassWaits: true,
      focusOnArrival: false,
      showPaperVeil: false,
      showArrivalSeal: false,
      showInkSpread: false,
      showNodeRipple: false,
    });
    expect(getRouteMotionPolicy("restrained")).toMatchObject({
      bypassWaits: false,
      focusOnArrival: false,
      showPaperVeil: false,
      showArrivalSeal: false,
      showInkSpread: false,
      showNodeRipple: false,
    });
    expect(getRouteMotionPolicy("cinematic")).toMatchObject({
      bypassWaits: false,
      focusOnArrival: true,
      showPaperVeil: true,
      showArrivalSeal: true,
      showInkSpread: false,
      showNodeRipple: false,
    });
    expect(getRouteMotionPolicy("experimental")).toMatchObject({
      bypassWaits: false,
      focusOnArrival: true,
      showPaperVeil: true,
      showArrivalSeal: true,
      showInkSpread: true,
      showNodeRipple: true,
    });
  });

  it("keeps distance timing while scaling the three motion profiles", () => {
    expect(routeTravelDurationMs(historicalLeg, "off")).toBe(0);
    const restrained = routeTravelDurationMs(historicalLeg, "restrained");
    const cinematic = routeTravelDurationMs(historicalLeg, "cinematic");
    const experimental = routeTravelDurationMs(historicalLeg, "experimental");
    expect(restrained).toBeLessThan(cinematic);
    expect(experimental).toBeGreaterThan(cinematic);
  });

  it("resumes a hidden arrival from its remaining delay", () => {
    expect(remainingMotionDelayMs(460, 1_000, 1_120)).toBe(340);
    expect(remainingMotionDelayMs(460, 1_000, 900)).toBe(460);
    expect(remainingMotionDelayMs(460, 1_000, 1_600)).toBe(0);
  });

  it("freezes each arrival profile and delay while preserving the live off escape", () => {
    const arrival = freezeRouteArrival("cinematic");

    expect(arrival).toEqual({ profile: "cinematic", delayMs: 460 });
    expect(routeArrivalMotionProfile("experimental", arrival, true)).toBe(
      "cinematic",
    );
    expect(routeArrivalMotionProfile("experimental", arrival, false)).toBe(
      "experimental",
    );
    expect(routeArrivalMotionProfile("off", arrival, true)).toBe("off");
    expect(remainingMotionDelayMs(arrival.delayMs, 1_000, 1_120)).toBe(340);
  });
});
