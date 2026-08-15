import type { EffectiveMotionProfile } from "./motion";

const PROFILE_DURATIONS: Readonly<Record<EffectiveMotionProfile, number>> = {
  off: 0,
  restrained: 260,
  cinematic: 620,
  experimental: 780,
};

export function counterValue(from: number, to: number, progress: number): number {
  const clampedProgress = Math.max(0, Math.min(1, progress));
  return from + (to - from) * clampedProgress;
}

export function imageryMotionDuration(profile: EffectiveMotionProfile): number {
  return PROFILE_DURATIONS[profile];
}

export function shouldChangeImagerySelection(
  currentWord: string,
  nextWord: string,
): boolean {
  return currentWord !== nextWord;
}

export function shouldSettleImageryCounterImmediately(
  durationMs: number,
  animationSupported: boolean,
  visibilityState: string,
): boolean {
  return durationMs <= 0
    || !animationSupported
    || visibilityState === "hidden";
}
