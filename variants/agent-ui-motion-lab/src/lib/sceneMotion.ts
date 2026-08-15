export type SceneMotionPhase =
  | "settled"
  | "covering"
  | "swapping"
  | "revealing";

export type SceneMotionDirection = -1 | 1;
export type SceneTransitionProfile = "restrained" | "cinematic" | "experimental";

export interface SceneMotionState {
  phase: SceneMotionPhase;
  visibleIndex: number;
  targetIndex: number | null;
  direction: SceneMotionDirection;
  transitionProfile: SceneTransitionProfile;
  transitionId: number;
}

export type SceneMotionEvent =
  | {
      type: "navigate";
      target: number;
      direction: SceneMotionDirection;
      profile: SceneTransitionProfile;
    }
  | { type: "covered" }
  | { type: "swapped" }
  | { type: "revealed" }
  | {
      type: "jump";
      target: number;
      direction: SceneMotionDirection;
    };

export function initialSceneMotion(index: number): SceneMotionState {
  return {
    phase: "settled",
    visibleIndex: index,
    targetIndex: null,
    direction: 1,
    transitionProfile: "cinematic",
    transitionId: 0,
  };
}

export function remainingSceneTimerMs(
  deadlineMs: number | null,
  nowMs: number,
  fallbackMs: number,
): number {
  const remainingMs = deadlineMs === null ? fallbackMs : deadlineMs - nowMs;
  return Math.max(0, remainingMs);
}

export function sceneContentIsHidden(phase: SceneMotionPhase): boolean {
  return phase === "swapping";
}

export function sceneDwellElapsedMs(totalMs: number, remainingMs: number): number {
  const boundedTotalMs = Math.max(0, totalMs);
  const boundedRemainingMs = Math.max(0, Math.min(boundedTotalMs, remainingMs));
  return boundedTotalMs - boundedRemainingMs;
}

export function sceneMotionReducer(
  state: SceneMotionState,
  event: SceneMotionEvent,
): SceneMotionState {
  switch (event.type) {
    case "navigate":
      if (state.phase !== "settled") return state;
      return {
        ...state,
        phase: "covering",
        targetIndex: event.target,
        direction: event.direction,
        transitionProfile: event.profile,
        transitionId: state.transitionId + 1,
      };

    case "covered":
      if (state.phase !== "covering" || state.targetIndex === null) return state;
      return {
        ...state,
        phase: "swapping",
        visibleIndex: state.targetIndex,
        targetIndex: null,
      };

    case "swapped":
      if (state.phase !== "swapping") return state;
      return {
        ...state,
        phase: "revealing",
      };

    case "revealed":
      if (state.phase !== "revealing") return state;
      return {
        ...state,
        phase: "settled",
      };

    case "jump":
      return {
        phase: "settled",
        visibleIndex: event.target,
        targetIndex: null,
        direction: event.direction,
        transitionProfile: state.transitionProfile,
        transitionId: state.transitionId + 1,
      };
  }
}
