import type { RouteSegment } from "./types";

export type JourneyPhase =
  | "idle"
  | "travelling"
  | "arrived"
  | "revealing"
  | "waiting";

export type JourneyCoordinate = [number, number];

export interface JourneyScenePoint {
  id: string;
  lon: number | null;
  lat: number | null;
  map_eligible: boolean;
}

export interface JourneyLeg
  extends Omit<RouteSegment, "kind" | "certainty" | "historical_claim"> {
  kind: "historical_route" | "camera_transition";
  certainty: "strict" | "not_asserted";
  historical_claim: boolean;
  source:
    | "historical_segment"
    | "tool_visual_transition"
    | "reverse_history_view"
    | "reverse_visual_view";
}

interface JourneyPayloadIdentity {
  poet: string;
  scenes: ReadonlyArray<{ id: string }>;
  routeSegments: ReadonlyArray<{ from_id: string; to_id: string }>;
  visualTransitions: ReadonlyArray<{ from_id: string; to_id: string }>;
}

export function journeyPayloadKey(payload: JourneyPayloadIdentity): string {
  const sceneIds = payload.scenes.map((scene) => scene.id).join(",");
  const historicalIds = payload.routeSegments
    .map((segment) => `${segment.from_id}>${segment.to_id}`)
    .join(",");
  const visualIds = payload.visualTransitions
    .map((segment) => `${segment.from_id}>${segment.to_id}`)
    .join(",");
  return `${payload.poet}::${sceneIds}::h:${historicalIds}::v:${visualIds}`;
}

function isLocatable(scene: JourneyScenePoint): boolean {
  return scene.map_eligible
    && typeof scene.lon === "number"
    && Number.isFinite(scene.lon)
    && typeof scene.lat === "number"
    && Number.isFinite(scene.lat);
}

function cloneCoords(
  coords: [[number, number], [number, number]],
  reverse = false,
): [[number, number], [number, number]] {
  const start: JourneyCoordinate = [...coords[reverse ? 1 : 0]];
  const end: JourneyCoordinate = [...coords[reverse ? 0 : 1]];
  return [start, end];
}

function historicalLeg(segment: RouteSegment): JourneyLeg {
  return {
    ...segment,
    coords: cloneCoords(segment.coords),
    kind: "historical_route",
    certainty: "strict",
    historical_claim: true,
    source: "historical_segment",
  };
}

function cameraLeg(
  segment: RouteSegment,
  source: JourneyLeg["source"],
  reverse = false,
): JourneyLeg {
  const isReverseHistory = source === "reverse_history_view";
  return {
    ...segment,
    from_id: reverse ? segment.to_id : segment.from_id,
    to_id: reverse ? segment.from_id : segment.to_id,
    coords: cloneCoords(segment.coords, reverse),
    kind: "camera_transition",
    certainty: "not_asserted",
    historical_claim: false,
    source,
    transport_mode: "journey",
    transport_label: "山径行旅",
    transport_basis: isReverseHistory
      ? "反向查看仅连接作品节点；正向史料不作为返程依据，路径未载。"
      : segment.transport_basis,
    transport_certainty: "unspecified",
  };
}

export function resolveJourneyLeg(
  historicalSegments: readonly RouteSegment[],
  visualTransitions: readonly RouteSegment[],
  fromScene: JourneyScenePoint,
  toScene: JourneyScenePoint,
): JourneyLeg | undefined {
  if (!isLocatable(fromScene) || !isLocatable(toScene)) return undefined;

  const directHistorical = historicalSegments.find(
    (segment) => segment.from_id === fromScene.id && segment.to_id === toScene.id,
  );
  if (directHistorical) return historicalLeg(directHistorical);

  const directVisual = visualTransitions.find(
    (segment) => segment.from_id === fromScene.id && segment.to_id === toScene.id,
  );
  if (directVisual) {
    return cameraLeg(directVisual, "tool_visual_transition");
  }

  const reverseHistorical = historicalSegments.find(
    (segment) => segment.from_id === toScene.id && segment.to_id === fromScene.id,
  );
  if (reverseHistorical) {
    return cameraLeg(reverseHistorical, "reverse_history_view", true);
  }

  const reverseVisual = visualTransitions.find(
    (segment) => segment.from_id === toScene.id && segment.to_id === fromScene.id,
  );
  if (reverseVisual) {
    return cameraLeg(reverseVisual, "reverse_visual_view", true);
  }

  return undefined;
}

function stableHash(value: string): number {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

export function sampleJourneyPath(
  leg: Pick<JourneyLeg, "from_id" | "to_id" | "coords">,
  sampleCount = 28,
): JourneyCoordinate[] {
  const count = Math.max(2, Math.floor(sampleCount));
  const [start, end] = leg.coords;
  const deltaX = end[0] - start[0];
  const deltaY = end[1] - start[1];
  const distance = Math.hypot(deltaX, deltaY);
  if (distance === 0) {
    return Array.from({ length: count }, () => [...start] as JourneyCoordinate);
  }

  const canonicalIds = [leg.from_id, leg.to_id].sort();
  const baseSign = stableHash(canonicalIds.join("|")) % 2 === 0 ? 1 : -1;
  const directionSign = leg.from_id <= leg.to_id ? 1 : -1;
  const bend = distance * 0.12 * baseSign * directionSign;
  const control: JourneyCoordinate = [
    (start[0] + end[0]) / 2 + (-deltaY / distance) * bend,
    (start[1] + end[1]) / 2 + (deltaX / distance) * bend,
  ];

  return Array.from({ length: count }, (_, index) => {
    if (index === 0) return [...start] as JourneyCoordinate;
    if (index === count - 1) return [...end] as JourneyCoordinate;
    const progress = index / (count - 1);
    const inverse = 1 - progress;
    return [
      inverse * inverse * start[0]
        + 2 * inverse * progress * control[0]
        + progress * progress * end[0],
      inverse * inverse * start[1]
        + 2 * inverse * progress * control[1]
        + progress * progress * end[1],
    ];
  });
}

export function interpolateJourneyPath(
  path: readonly JourneyCoordinate[],
  progress: number,
): JourneyCoordinate {
  if (path.length === 0) return [0, 0];
  const first = path[0] ?? [0, 0];
  const last = path[path.length - 1] ?? first;
  if (path.length === 1) return [first[0], first[1]];
  const value = Math.max(0, Math.min(1, progress));
  if (value === 0) return [first[0], first[1]];
  if (value === 1) return [last[0], last[1]];
  const scaled = value * (path.length - 1);
  const startIndex = Math.floor(scaled);
  const endIndex = Math.min(path.length - 1, startIndex + 1);
  const local = scaled - startIndex;
  const start = path[startIndex] ?? first;
  const end = path[endIndex] ?? last;
  return [
    start[0] + (end[0] - start[0]) * local,
    start[1] + (end[1] - start[1]) * local,
  ];
}

export function easeInOutCubic(progress: number): number {
  const value = Math.max(0, Math.min(1, progress));
  return value < 0.5
    ? 4 * value * value * value
    : 1 - Math.pow(-2 * value + 2, 3) / 2;
}

export function revealDelayMs(character: string): number {
  if (character === "\n") return 160;
  if (/[。！？；]/u.test(character)) return 230;
  if (/[，、：]/u.test(character)) return 115;
  return 38;
}

export function clampSceneIndex(index: number, sceneCount: number): number {
  if (sceneCount <= 0) return 0;
  return Math.max(0, Math.min(sceneCount - 1, index));
}
