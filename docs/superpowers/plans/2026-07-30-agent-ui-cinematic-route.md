# Cinematic Poet Route Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore the Agent UI route view as a historically sourced cinematic journey in which the documented or explicitly unspecified travel mode moves only along Tool-provided segments, arrives, reveals the destination evidence, then types the poem before waiting for the user.

**Architecture:** Keep Python as the sole source of route, year, place, poem, transport evidence, and evidence facts. Python enriches each route segment with a transport profile derived only from explicit source phrases; React supports boat, horse, carriage, walking, and an unspecified journey marker. Add a pure TypeScript journey-state module, render the China map with locally bundled GeoJSON through ECharts, and position the active transport marker with `convertToPixel`. The route component owns the five playback phases and leaves unsupported scene transitions disconnected.

**Tech Stack:** FastAPI, deterministic Python cache, Next.js 16, React 19, TypeScript, ECharts 6, Vitest, Playwright.

---

### Task 1: Restore the authoritative route generator

**Files:**
- Preserve: `数据可视化脚本/viz_33_year759_legacy.py`
- Restore: `数据可视化脚本/viz_33_year759.py`
- Regenerate: `output/33_平行时空759.html`
- Regenerate: `output/assets/competition/year759_data.json`
- Refresh: `apps/agent-ui/.cache/year759_data.json`

- [ ] Preserve the current six-node legacy generator under the explicit legacy filename.
- [ ] Restore `viz_33_year759_codex_backup.py` as the active `auto-story/3.0` generator.
- [ ] Run `python 数据可视化脚本/viz_33_year759.py` and expect `6卷 / 122节点 / 3组同年碰撞`.
- [ ] Instantiate `PoetryDataService` and assert `generate_poet_route("李白")` returns `status=ok`, 27 scenes, and 10 segments.

### Task 2: Specify the journey state machine with failing tests

**Files:**
- Modify: `apps/agent-ui/agent/poetry_agent/service.py`
- Modify: `apps/agent-ui/agent/tests/test_service.py`
- Create: `apps/agent-ui/web/src/lib/journey.ts`
- Create: `apps/agent-ui/web/src/lib/journey.test.ts`

- [ ] Write Python tests proving explicit phrases map to boat, horse, carriage, or walk; unrelated poem wording does not affect a segment; missing evidence returns `journey/unspecified`.
- [ ] Enrich every Tool route segment with `transport_mode`, `transport_label`, `transport_basis`, and `transport_certainty` without changing the authoritative coordinates.
- [ ] Write tests proving that a scene transition is travelable only when an explicit `RouteSegment` connects the two scene IDs.
- [ ] Write tests for punctuation-aware reveal delays: commas and enumeration punctuation pause longer than ordinary characters; sentence punctuation pauses longest.
- [ ] Write tests proving that next/previous index helpers clamp at the route bounds.
- [ ] Run `npm --prefix apps/agent-ui/web test -- journey.test.ts` and verify the tests fail because the module does not exist.
- [ ] Implement these pure exports:

```ts
export type JourneyPhase = "idle" | "travelling" | "arrived" | "revealing" | "waiting";
export function findRouteSegment(segments: RouteSegment[], fromId: string, toId: string): RouteSegment | undefined;
export function revealDelayMs(character: string): number;
export function clampSceneIndex(index: number, sceneCount: number): number;
export function interpolateRoute(coords: [[number, number], [number, number]], progress: number): [number, number];
```

- [ ] Re-run the focused tests and expect all journey tests to pass.

### Task 3: Bundle and register the offline map

**Files:**
- Create: `apps/agent-ui/web/public/assets/china-city-prefecture.geojson`
- Modify: `apps/agent-ui/web/src/components/PoetRouteMap.tsx`

- [ ] Copy `output/assets/maps/china_city_prefecture.geojson` into the Agent UI public assets directory.
- [ ] Fetch the local asset once, register it as `poetry-china`, and expose a readable loading/error state.
- [ ] Configure ECharts `geo` with muted paper provinces, thin borders, Tool-provided route lines, and clickable Tool-provided scene points.

### Task 4: Build the cinematic route player

**Files:**
- Modify: `apps/agent-ui/web/src/components/PoetRouteMap.tsx`

- [ ] Drive the component through `idle -> travelling -> arrived -> revealing -> waiting`.
- [ ] Keep the poem and evidence card hidden during `travelling`.
- [ ] Animate the Tool-selected boat, horse, carriage, walker, or generic traveller with `requestAnimationFrame` only across `findRouteSegment(...)` results; unsupported transitions jump to the node with a visible “史料未形成连续路线” notice.
- [ ] Convert interpolated geographic coordinates to pixels with ECharts `convertToPixel({ geoIndex: 0 }, coord)` on every animation frame and resize.
- [ ] At arrival, fade in year/place/source, then title, then reveal `poem_lines.join("。\n")` character by character.
- [ ] Pause indefinitely in `waiting`; advance only from `下一站`, a timeline-node click, or keyboard ArrowRight.
- [ ] Add `上一站`, `播放/暂停`, `下一站`, and `重播`; autoplay may begin the next voyage only after the scene read time.
- [ ] Under `prefers-reduced-motion`, travel and reveal complete immediately while retaining all content and controls.

### Task 5: Restore the wide Claude/editorial composition

**Files:**
- Modify: `apps/agent-ui/web/src/components/PoetryWorkbench.tsx`
- Modify: `apps/agent-ui/web/src/components/PoetSelector.tsx`
- Modify: `apps/agent-ui/web/src/app/globals.css`

- [ ] Replace the permanent desktop sidebar with a compact top poet selector for route and scene modes.
- [ ] Keep imagery mode, CopilotKit popup, OpenGenerativeUI toggle, evidence panel, and Tool request contracts unchanged.
- [ ] Use warm paper, Anthropic terracotta, near-black, indigo/jade data accents, thin borders, 4-8px radii, and KaiTi for poems.
- [ ] Make the journey stage the dominant first-viewport surface at desktop and stack map, arrival card, controls, and timeline cleanly at 390px.
- [ ] Ensure all touch controls are at least 44px and no text overlaps or horizontal page overflow appears.

### Task 6: Verify and serve

**Files:**
- Update only if needed: `apps/agent-ui/web/src/**/*.test.ts`
- Generate acceptance evidence under: `output/playwright/`

- [ ] Run backend tests: `apps/agent-ui/agent/.venv/Scripts/python.exe -m pytest apps/agent-ui/agent/tests -q`.
- [ ] Run frontend lint, typecheck, Vitest, and production build.
- [ ] Run `python tools/check_all.py --offline --keep-going` to ensure stable offline exhibits remain green.
- [ ] Start the production Agent UI and API with `apps/agent-ui/start-dev.ps1 -Production`.
- [ ] In Playwright at 1440x900 and 390x844, exercise initial reveal, next-station voyage, arrival card, typed poem, pause, previous, replay, poet switch, and unsupported-route transition.
- [ ] Capture screenshots and confirm zero actionable console errors and zero page-level horizontal overflow.
