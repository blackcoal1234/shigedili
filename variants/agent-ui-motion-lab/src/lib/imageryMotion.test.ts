import { describe, expect, it } from "vitest";

import {
  counterValue,
  imageryMotionDuration,
  shouldChangeImagerySelection,
  shouldSettleImageryCounterImmediately,
} from "./imageryMotion";

describe("imagery motion", () => {
  it("clamps counter interpolation", () => {
    expect(counterValue(10, 20, -1)).toBe(10);
    expect(counterValue(10, 20, 0.5)).toBe(15);
    expect(counterValue(10, 20, 2)).toBe(20);
  });

  it.each([
    ["off", 0],
    ["restrained", 260],
    ["cinematic", 620],
    ["experimental", 780],
  ] as const)("uses the %s profile duration", (profile, duration) => {
    expect(imageryMotionDuration(profile)).toBe(duration);
  });

  it("keeps the current counter running when the active word is selected again", () => {
    expect(shouldChangeImagerySelection("月", "月")).toBe(false);
    expect(shouldChangeImagerySelection("月", "江")).toBe(true);
  });

  it("settles immediately when motion starts in a hidden document", () => {
    expect(shouldSettleImageryCounterImmediately(620, true, "hidden")).toBe(true);
    expect(shouldSettleImageryCounterImmediately(620, true, "visible")).toBe(false);
    expect(shouldSettleImageryCounterImmediately(0, true, "visible")).toBe(true);
    expect(shouldSettleImageryCounterImmediately(620, false, "visible")).toBe(true);
  });
});
