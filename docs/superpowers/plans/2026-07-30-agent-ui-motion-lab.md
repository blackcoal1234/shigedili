# Agent UI Motion Lab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an isolated Agent UI animation lab with switchable restrained, cinematic, and experimental motion profiles for poet routes, poem scenes, and Tang–Song imagery comparisons.

**Architecture:** Copy only the Next.js front end into a timestamped baseline and a working variant, sharing the existing dependency tree through a directory junction and the existing backend through port 8123. A pure motion preference module and top-level controls provide one stable contract to three independently implemented component animations; each animation owns a separate CSS file so parallel workers do not edit shared files.

**Tech Stack:** Next.js 16, React 19, TypeScript 5.8, ECharts 6, CSS animations, requestAnimationFrame, Vitest, ESLint.

---

## File structure

- Create `D:\game存档\诗行万里2\诗行万里\variants\_baseline-agent-ui-20260809\`: immutable copy of the current original front-end source/config/public files used for final development.
- Create `D:\game存档\诗行万里2\诗行万里\variants\agent-ui-motion-lab\`: working copy.
- Create `src/lib/motion.ts`: profile types, normalization, storage helpers, reduced-motion helper.
- Create `src/lib/motion.test.ts`: pure preference tests.
- Create `src/components/MotionLabControls.tsx`: accessible profile switcher and master animation toggle.
- Create `src/app/motion/base.css`: shared control and profile tokens.
- Create `src/app/motion/route.css`: route-only motion.
- Create `src/app/motion/scenes.css`: scene-player-only motion.
- Create `src/app/motion/imagery.css`: imagery-only motion.
- Modify `src/app/layout.tsx`: import the four motion styles after existing global styles.
- Modify `src/components/PoetryWorkbench.tsx`: own the preference, render controls, expose root data attributes, pass motion props.
- Modify `src/components/PoetRouteMap.tsx`: arrival seal, camera state, ink trail and profile hooks.
- Create `src/lib/sceneMotion.ts` and `src/lib/sceneMotion.test.ts`: deterministic scene transition state.
- Modify `src/components/PoemScenePlayer.tsx`: cover/swap/reveal transition, direction, remaining dwell timer.
- Create `src/lib/imageryMotion.ts` and `src/lib/imageryMotion.test.ts`: counter interpolation and selection transition helpers.
- Modify `src/components/ImageryComparison.tsx`: animated counters, tide overlay, evidence reveal and keyboard term selection.

## Task 1: Create protected baseline and working copy

**Files:**
- Copy from: `D:\game存档\诗行万里2\诗行万里\apps\agent-ui\web`
- Create: `D:\game存档\诗行万里2\诗行万里\variants\_baseline-agent-ui-20260809`
- Create: `D:\game存档\诗行万里2\诗行万里\variants\agent-ui-motion-lab`

- [ ] Record SHA-256 for every original file under `apps\agent-ui\web\src`, plus `data` and `output\manifest.json`, into an in-memory verification result.
- [ ] Copy the front end twice with `robocopy`, excluding `node_modules`, `.next`, `coverage`, `playwright-report`, `test-results`, `tsconfig.tsbuildinfo`, and `.env.local`; accept Robocopy exit codes 0–7 only.
- [ ] Create a directory junction from the working copy's `node_modules` to the original `node_modules`; do not run `npm install` or `npm ci` while the junction exists.
- [ ] Confirm the baseline and working copy contain identical hashes before edits.
- [ ] Confirm neither copy contains `.next`, a runtime PID directory, or environment secrets.

## Task 2: Build the motion preference foundation with tests

**Files:**
- Create: `src/lib/motion.ts`
- Create: `src/lib/motion.test.ts`
- Create: `src/components/MotionLabControls.tsx`
- Create: `src/app/motion/base.css`
- Modify: `src/app/layout.tsx`
- Modify: `src/components/PoetryWorkbench.tsx`

- [ ] Write failing tests in `src/lib/motion.test.ts` for profile normalization, disabled state, storage serialization, and reduced-motion override:

```ts
import { describe, expect, it } from "vitest";
import { effectiveMotionProfile, normalizeMotionProfile, parseMotionPreference, serializeMotionPreference } from "./motion";

describe("motion preference", () => {
  it("normalizes unknown values to cinematic", () => {
    expect(normalizeMotionProfile("unknown")).toBe("cinematic");
  });
  it("round trips a persisted preference", () => {
    expect(parseMotionPreference(serializeMotionPreference({ enabled: true, profile: "experimental" })))
      .toEqual({ enabled: true, profile: "experimental" });
  });
  it("returns off when disabled or reduced motion is requested", () => {
    expect(effectiveMotionProfile({ enabled: false, profile: "cinematic" }, false)).toBe("off");
    expect(effectiveMotionProfile({ enabled: true, profile: "cinematic" }, true)).toBe("off");
  });
});
```

- [ ] Run `npm test -- motion.test.ts` in the working copy and verify failure because `motion.ts` does not exist.
- [ ] Implement `MotionProfile = "restrained" | "cinematic" | "experimental"`, `EffectiveMotionProfile = MotionProfile | "off"`, `MotionPreference`, `normalizeMotionProfile`, `parseMotionPreference`, `serializeMotionPreference`, and `effectiveMotionProfile` as pure exports. Invalid JSON must return `{ enabled: true, profile: "cinematic" }`.
- [ ] Re-run the focused test and verify it passes.
- [ ] Implement `MotionLabControls` as a 44px-minimum segmented control with a master checkbox; labels are `克制`, `电影`, `实验`, and `关闭动画`.
- [ ] In `PoetryWorkbench`, initialize the preference from `localStorage` after hydration, subscribe to `prefers-reduced-motion`, persist changes, set `data-motion-profile` on `.workbench-shell`, render the controls in the masthead, and pass `motionProfile` to `WorkbenchResult` and its three child components.
- [ ] Import `motion/base.css`, `route.css`, `scenes.css`, and `imagery.css` from `layout.tsx`; empty domain files are acceptable only until Tasks 3–5 begin.
- [ ] Run the focused test, full Vitest, and typecheck.

## Task 3: Enhance poet-route motion without changing route truth

**Files:**
- Modify: `src/components/PoetRouteMap.tsx`
- Create: `src/app/motion/route.css`
- Test: `src/lib/journey.test.ts`

- [ ] Add a failing journey test proving `interpolateRoute` clamps progress below 0 and above 1 to the segment endpoints; this protects marker motion from overshoot.
- [ ] Run `npm test -- journey.test.ts` and verify the new clamping assertions fail if the current helper extrapolates.
- [ ] Update `interpolateRoute` to clamp progress with `Math.max(0, Math.min(1, progress))`, then re-run journey tests.
- [ ] Add `motionProfile: EffectiveMotionProfile` to `PoetRouteMapProps` and add `data-motion-profile`, `data-phase`, and `data-transport` hooks to the player/stage.
- [ ] Add an arrival seal keyed by `scene.id`, containing only `place_historical`, and expose it only during `arrived`, `revealing`, or `waiting`.
- [ ] Add a separate ink-progress overlay whose width is the existing real `travelProgress`; do not create coordinates or segments.
- [ ] In cinematic mode, apply a small stage camera scale during travel and settle on arrival; in experimental mode, add node ripples and route glow; in restrained mode, retain only current marker travel and fades.
- [ ] When `motionProfile === "off"`, make `goToScene` call `arriveAt` immediately and reveal the complete poem without any timer; preserve the missing-segment notice.
- [ ] Ensure pause, replay, map roam, keyboard navigation, and `onSelectScene` retain their current contracts.
- [ ] Run journey tests and typecheck.

## Task 4: Build the cinematic scene transition state machine with tests

**Files:**
- Create: `src/lib/sceneMotion.ts`
- Create: `src/lib/sceneMotion.test.ts`
- Modify: `src/components/PoemScenePlayer.tsx`
- Create: `src/app/motion/scenes.css`

- [ ] Write failing tests for the pure transition reducer:

```ts
import { describe, expect, it } from "vitest";
import { initialSceneMotion, sceneMotionReducer } from "./sceneMotion";

describe("scene motion reducer", () => {
  it("covers, swaps once, reveals, and settles", () => {
    let state = initialSceneMotion(0);
    state = sceneMotionReducer(state, { type: "navigate", target: 1, direction: 1 });
    expect(state.phase).toBe("covering");
    state = sceneMotionReducer(state, { type: "covered" });
    expect(state).toMatchObject({ phase: "revealing", visibleIndex: 1 });
    state = sceneMotionReducer(state, { type: "revealed" });
    expect(state.phase).toBe("settled");
  });
  it("settles immediately when motion is off", () => {
    const state = sceneMotionReducer(initialSceneMotion(0), { type: "jump", target: 3 });
    expect(state).toMatchObject({ phase: "settled", visibleIndex: 3 });
  });
});
```

- [ ] Run `npm test -- sceneMotion.test.ts` and verify failure because the module does not exist.
- [ ] Implement `SceneMotionPhase`, `SceneMotionState`, `SceneMotionEvent`, `initialSceneMotion`, and `sceneMotionReducer`; the reducer must swap `visibleIndex` only on `covered` and ignore duplicate navigation outside `settled`.
- [ ] Re-run the focused test and verify it passes.
- [ ] Add `motionProfile` to `PoemScenePlayerProps`; drive the visible scene through the reducer rather than changing the visible index immediately.
- [ ] Add two inert warm-paper cover leaves, a direction data attribute, per-line reveal delays, a location stamp, and a dwell progress ring derived from real `read_seconds`.
- [ ] Start the dwell timer only after `revealed`; pause must preserve remaining milliseconds, and unmount/poet switch must clear every timer.
- [ ] For `motionProfile === "off"`, dispatch `jump`, reveal complete content immediately, and keep autoplay dwell semantics.
- [ ] On screens below 600px, use a vertical paper wipe with no 3D or page-wide horizontal translation.
- [ ] Ensure only the visible scene participates in the accessibility tree and call `onSceneChange` once at the swap point.
- [ ] Run scene motion tests, all Vitest tests, and typecheck.

## Task 5: Build the imagery tide transition with tests

**Files:**
- Create: `src/lib/imageryMotion.ts`
- Create: `src/lib/imageryMotion.test.ts`
- Modify: `src/components/ImageryComparison.tsx`
- Create: `src/app/motion/imagery.css`

- [ ] Write failing tests for numeric interpolation and profile-specific duration:

```ts
import { describe, expect, it } from "vitest";
import { counterValue, imageryMotionDuration } from "./imageryMotion";

describe("imagery motion", () => {
  it("clamps counter interpolation", () => {
    expect(counterValue(10, 20, -1)).toBe(10);
    expect(counterValue(10, 20, 0.5)).toBe(15);
    expect(counterValue(10, 20, 2)).toBe(20);
  });
  it("turns timing off for the off profile", () => {
    expect(imageryMotionDuration("off")).toBe(0);
    expect(imageryMotionDuration("cinematic")).toBeGreaterThan(0);
  });
});
```

- [ ] Run `npm test -- imageryMotion.test.ts` and verify failure because the module does not exist.
- [ ] Implement clamped linear `counterValue` and `imageryMotionDuration` with exact values: off 0ms, restrained 260ms, cinematic 620ms, experimental 780ms.
- [ ] Re-run the focused test and verify it passes.
- [ ] Add `motionProfile` to `ImageryComparison`; on term change animate displayed Tang/Song rates from the previous real values to the new real values with `requestAnimationFrame`, cancelling the prior frame on a new selection or unmount.
- [ ] Set ECharts `animationDurationUpdate` from the profile and enable `universalTransition` on both existing bar series; keep final values and colors unchanged.
- [ ] Add a semantic tide overlay with two decorative CSS lines driven only by normalized Tang/Song rates; mark it `aria-hidden` and never render particles per hit.
- [ ] Key the evidence list by selected word so real evidence cards reveal in dynasty groups; off mode displays them immediately.
- [ ] Make term tabs a roving keyboard group supporting ArrowLeft and ArrowRight, while preserving click selection.
- [ ] Run imagery tests, all Vitest tests, and typecheck.

## Task 6: Integrate, refine, and validate static code quality

**Files:**
- Modify only if needed: `src/components/PoetryWorkbench.tsx`
- Modify only if needed: `src/app/motion/*.css`
- Modify only if needed: `src/**/*.test.ts`

- [ ] Review all three component prop signatures and confirm `motionProfile` is the same `EffectiveMotionProfile` type everywhere.
- [ ] Confirm every color in motion CSS uses existing CSS variables or documented existing palette values; remove any rogue hue.
- [ ] Confirm no `scrollIntoView`, Framer Motion, GSAP, Lottie, new CDN, fabricated statistic, emoji icon, or new image/audio/video dependency exists.
- [ ] Run `npm run lint` and expect zero warnings.
- [ ] Run `npm run typecheck` and expect zero TypeScript errors.
- [ ] Run `npm run test` and expect all tests to pass.
- [ ] Run `npm run build` and expect Next.js production build success.
- [ ] Recompute original source/data/output hashes and prove they match the Task 1 snapshot.

## Task 7: Start the isolated variant and produce handoff

**Files:**
- Create: `D:\game存档\诗行万里2\诗行万里\variants\agent-ui-motion-lab\start-motion-lab.ps1`
- Create: `D:\game存档\诗行万里2\诗行万里\variants\agent-ui-motion-lab\README-MOTION-LAB.md`

- [ ] Create a PowerShell launcher that binds only `127.0.0.1:3011`, checks that `8123` is available, and starts `npm run dev -- --hostname 127.0.0.1 --port 3011` in a hidden window; it must never stop or reuse the original 3000 process.
- [ ] Document the lab URL, profile controls, shared backend requirement, dependency-junction rule, build/test commands, baseline path, and reset procedure (replace working files from baseline, never delete the original).
- [ ] Start the lab, request `http://127.0.0.1:3011/`, and verify HTTP 200 and presence of the Motion Lab labels in returned HTML or hydrated source.
- [ ] Leave the original services on 3000, 8123, and 8770 untouched.
