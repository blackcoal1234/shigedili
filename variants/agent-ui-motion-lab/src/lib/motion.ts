export type MotionProfile = "restrained" | "cinematic" | "experimental";
export type EffectiveMotionProfile = MotionProfile | "off";

export interface MotionPreference {
  enabled: boolean;
  profile: MotionProfile;
}

export const MOTION_STORAGE_KEY = "poetry-motion-lab";
export const MOTION_PREFERENCE_EVENT = "poetry-motion-preference";
export const DEFAULT_MOTION_PREFERENCE: MotionPreference = {
  enabled: true,
  profile: "cinematic",
};

const MOTION_PROFILES: ReadonlySet<string> = new Set([
  "restrained",
  "cinematic",
  "experimental",
]);

export function normalizeMotionProfile(value: unknown): MotionProfile {
  return typeof value === "string" && MOTION_PROFILES.has(value)
    ? value as MotionProfile
    : DEFAULT_MOTION_PREFERENCE.profile;
}

export function parseMotionPreference(value: string | null | undefined): MotionPreference {
  if (!value) return { ...DEFAULT_MOTION_PREFERENCE };
  try {
    const parsed = JSON.parse(value) as { enabled?: unknown; profile?: unknown };
    if (typeof parsed.enabled !== "boolean" || !MOTION_PROFILES.has(String(parsed.profile))) {
      return { ...DEFAULT_MOTION_PREFERENCE };
    }
    return {
      enabled: parsed.enabled,
      profile: normalizeMotionProfile(parsed.profile),
    };
  } catch {
    return { ...DEFAULT_MOTION_PREFERENCE };
  }
}

export function serializeMotionPreference(preference: MotionPreference): string {
  return JSON.stringify({
    enabled: preference.enabled,
    profile: normalizeMotionProfile(preference.profile),
  });
}

export function effectiveMotionProfile(
  preference: MotionPreference,
  reducedMotion: boolean,
): EffectiveMotionProfile {
  return preference.enabled && !reducedMotion ? preference.profile : "off";
}
