import { describe, expect, it } from "vitest";

import {
  DEFAULT_MOTION_PREFERENCE,
  effectiveMotionProfile,
  normalizeMotionProfile,
  parseMotionPreference,
  serializeMotionPreference,
} from "./motion";

describe("motion preference", () => {
  it("normalizes unsupported profiles to the cinematic default", () => {
    expect(normalizeMotionProfile("experimental")).toBe("experimental");
    expect(normalizeMotionProfile("unknown")).toBe("cinematic");
    expect(normalizeMotionProfile(null)).toBe("cinematic");
  });

  it("round trips the persisted preference", () => {
    const preference = { enabled: true, profile: "experimental" as const };
    expect(parseMotionPreference(serializeMotionPreference(preference))).toEqual(preference);
  });

  it("falls back safely for malformed storage", () => {
    expect(parseMotionPreference("not-json")).toEqual(DEFAULT_MOTION_PREFERENCE);
    expect(parseMotionPreference('{"enabled":"yes","profile":"cinematic"}'))
      .toEqual(DEFAULT_MOTION_PREFERENCE);
  });

  it("turns motion off when disabled or reduced motion is requested", () => {
    expect(effectiveMotionProfile({ enabled: false, profile: "cinematic" }, false)).toBe("off");
    expect(effectiveMotionProfile({ enabled: true, profile: "cinematic" }, true)).toBe("off");
    expect(effectiveMotionProfile({ enabled: true, profile: "restrained" }, false)).toBe("restrained");
  });
});
