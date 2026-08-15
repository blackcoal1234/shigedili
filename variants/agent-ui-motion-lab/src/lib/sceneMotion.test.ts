import { describe, expect, it } from "vitest";

import {
  initialSceneMotion,
  remainingSceneTimerMs,
  sceneContentIsHidden,
  sceneDwellElapsedMs,
  sceneMotionReducer,
} from "./sceneMotion";

describe("scene motion reducer", () => {
  it("holds the old scene until full cover, swaps once, and locks re-entry", () => {
    let state = initialSceneMotion(0);

    state = sceneMotionReducer(state, {
      type: "navigate",
      target: 1,
      direction: 1,
      profile: "experimental",
    });
    expect(state).toMatchObject({
      phase: "covering",
      visibleIndex: 0,
      targetIndex: 1,
      direction: 1,
      transitionProfile: "experimental",
    });

    expect(sceneMotionReducer(state, {
      type: "navigate",
      target: 2,
      direction: 1,
      profile: "restrained",
    })).toEqual(state);

    state = sceneMotionReducer(state, { type: "covered" });
    expect(state).toMatchObject({
      phase: "swapping",
      visibleIndex: 1,
      targetIndex: null,
    });
    expect(sceneMotionReducer(state, { type: "covered" })).toEqual(state);
    expect(sceneMotionReducer(state, {
      type: "navigate",
      target: 2,
      direction: 1,
      profile: "restrained",
    })).toEqual(state);

    state = sceneMotionReducer(state, { type: "swapped" });
    expect(state.phase).toBe("revealing");
    expect(sceneMotionReducer(state, {
      type: "navigate",
      target: 2,
      direction: 1,
      profile: "restrained",
    })).toEqual(state);

    state = sceneMotionReducer(state, { type: "revealed" });
    expect(state.phase).toBe("settled");
  });

  it("preserves backward direction for the mirrored transition", () => {
    const state = sceneMotionReducer(initialSceneMotion(3), {
      type: "navigate",
      target: 2,
      direction: -1,
      profile: "restrained",
    });

    expect(state).toMatchObject({
      phase: "covering",
      visibleIndex: 3,
      targetIndex: 2,
      direction: -1,
      transitionProfile: "restrained",
    });
  });

  it("jumps immediately when motion is off or reduced", () => {
    const covering = sceneMotionReducer(initialSceneMotion(0), {
      type: "navigate",
      target: 1,
      direction: 1,
      profile: "cinematic",
    });
    const state = sceneMotionReducer(covering, {
      type: "jump",
      target: 3,
      direction: 1,
    });

    expect(state).toMatchObject({
      phase: "settled",
      visibleIndex: 3,
      targetIndex: null,
      direction: 1,
    });
  });
});

describe("scene visibility pause", () => {
  it("preserves a running timer's remaining duration while the page is hidden", () => {
    expect(remainingSceneTimerMs(2_600, 1_000, 5_000)).toBe(1_600);
    expect(remainingSceneTimerMs(null, 1_000, 750)).toBe(750);
    expect(remainingSceneTimerMs(900, 1_000, 750)).toBe(0);
  });

  it("hides swapped content from assistive technology until reveal begins", () => {
    expect(sceneContentIsHidden("covering")).toBe(false);
    expect(sceneContentIsHidden("swapping")).toBe(true);
    expect(sceneContentIsHidden("revealing")).toBe(false);
    expect(sceneContentIsHidden("settled")).toBe(false);
  });

  it("derives the dwell-ring offset from the real JS timer remainder", () => {
    expect(sceneDwellElapsedMs(12_000, 4_500)).toBe(7_500);
    expect(sceneDwellElapsedMs(12_000, 13_000)).toBe(0);
    expect(sceneDwellElapsedMs(12_000, -100)).toBe(12_000);
  });
});
