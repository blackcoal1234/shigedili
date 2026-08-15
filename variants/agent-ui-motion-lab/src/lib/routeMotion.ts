import type { JourneyCoordinate, JourneyLeg } from "./journey";
import type { EffectiveMotionProfile } from "./motion";

export interface RouteMotionPolicy {
  bypassWaits: boolean;
  arrivalDelayMs: number;
  characterDelayScale: number;
  travelDurationScale: number;
  mapAnimationMs: number;
  focusOnArrival: boolean;
  focusZoomScale: number;
  showPaperVeil: boolean;
  showArrivalSeal: boolean;
  showInkSpread: boolean;
  showNodeRipple: boolean;
  activeStrokeWidth: number;
  activeHaloWidth: number;
}

export interface RouteArrivalSnapshot {
  profile: EffectiveMotionProfile;
  delayMs: number;
}

const ROUTE_MOTION_POLICIES: Record<EffectiveMotionProfile, RouteMotionPolicy> = {
  off: {
    bypassWaits: true,
    arrivalDelayMs: 0,
    characterDelayScale: 0,
    travelDurationScale: 0,
    mapAnimationMs: 0,
    focusOnArrival: false,
    focusZoomScale: 1,
    showPaperVeil: false,
    showArrivalSeal: false,
    showInkSpread: false,
    showNodeRipple: false,
    activeStrokeWidth: 3,
    activeHaloWidth: 0,
  },
  restrained: {
    bypassWaits: false,
    arrivalDelayMs: 180,
    characterDelayScale: 0,
    travelDurationScale: 0.72,
    mapAnimationMs: 260,
    focusOnArrival: false,
    focusZoomScale: 1,
    showPaperVeil: false,
    showArrivalSeal: false,
    showInkSpread: false,
    showNodeRipple: false,
    activeStrokeWidth: 3.6,
    activeHaloWidth: 0,
  },
  cinematic: {
    bypassWaits: false,
    arrivalDelayMs: 460,
    characterDelayScale: 1,
    travelDurationScale: 1,
    mapAnimationMs: 680,
    focusOnArrival: true,
    focusZoomScale: 1.2,
    showPaperVeil: true,
    showArrivalSeal: true,
    showInkSpread: false,
    showNodeRipple: false,
    activeStrokeWidth: 5,
    activeHaloWidth: 7,
  },
  experimental: {
    bypassWaits: false,
    arrivalDelayMs: 620,
    characterDelayScale: 0.82,
    travelDurationScale: 1.08,
    mapAnimationMs: 820,
    focusOnArrival: true,
    focusZoomScale: 1.28,
    showPaperVeil: true,
    showArrivalSeal: true,
    showInkSpread: true,
    showNodeRipple: true,
    activeStrokeWidth: 5.4,
    activeHaloWidth: 9,
  },
};

export function getRouteMotionPolicy(
  profile: EffectiveMotionProfile,
): RouteMotionPolicy {
  return ROUTE_MOTION_POLICIES[profile];
}

export function freezeRouteArrival(
  profile: EffectiveMotionProfile,
): RouteArrivalSnapshot {
  return {
    profile,
    delayMs: getRouteMotionPolicy(profile).arrivalDelayMs,
  };
}

export function routeArrivalMotionProfile(
  liveProfile: EffectiveMotionProfile,
  arrival: RouteArrivalSnapshot,
  isArriving: boolean,
): EffectiveMotionProfile {
  if (liveProfile === "off") return "off";
  return isArriving ? arrival.profile : liveProfile;
}

export function shouldAnimateJourneyLeg(
  leg: JourneyLeg | undefined,
): boolean {
  return leg?.kind === "historical_route" && leg.historical_claim;
}

export function revealJourneyPath(
  path: readonly JourneyCoordinate[],
  progress: number,
): JourneyCoordinate[] {
  if (path.length === 0) return [];
  const first = path[0] ?? [0, 0];
  if (path.length === 1) return [[first[0], first[1]]];

  const value = Math.max(0, Math.min(1, progress));
  if (value === 0) return [[first[0], first[1]], [first[0], first[1]]];
  if (value === 1) return path.map(([lon, lat]) => [lon, lat]);

  const scaled = value * (path.length - 1);
  const completedIndex = Math.floor(scaled);
  const localProgress = scaled - completedIndex;
  const visible = path
    .slice(0, completedIndex + 1)
    .map(([lon, lat]) => [lon, lat] as JourneyCoordinate);
  const start = path[completedIndex] ?? first;
  const end = path[Math.min(path.length - 1, completedIndex + 1)] ?? start;
  visible.push([
    start[0] + (end[0] - start[0]) * localProgress,
    start[1] + (end[1] - start[1]) * localProgress,
  ]);
  return visible;
}

export function routeTravelDurationMs(
  leg: Pick<JourneyLeg, "coords">,
  profile: EffectiveMotionProfile,
): number {
  const policy = getRouteMotionPolicy(profile);
  if (policy.bypassWaits) return 0;
  const [[startLon, startLat], [endLon, endLat]] = leg.coords;
  const distance = Math.hypot(endLon - startLon, endLat - startLat);
  const baseDuration = Math.max(3200, Math.min(5500, 3000 + distance * 88));
  return Math.round(baseDuration * policy.travelDurationScale);
}

export function remainingMotionDelayMs(
  remainingMs: number,
  startedAtMs: number,
  nowMs: number,
): number {
  const safeRemaining = Math.max(0, remainingMs);
  const elapsed = Math.max(0, nowMs - startedAtMs);
  return Math.max(0, safeRemaining - elapsed);
}
