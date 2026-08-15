# Song-print Journey Animation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox ('- [ ]') syntax for tracking.

**Goal:** Replace the white bubble traveller with five transparent Song-print glyphs and make every adjacent locatable poem scene move continuously over clearly differentiated historical and non-historical route layers.

**Architecture:** Python remains the factual boundary: it preserves strict historical 'routeSegments' and emits a separate 'visualTransitions' array for adjacent coordinate-complete gaps, always marked 'historical_claim: false'. React resolves both arrays into playback legs, samples one deterministic quadratic curve for both ECharts lines and marker motion, and renders transparent inline SVG glyphs.

**Tech Stack:** FastAPI/Python, React 19, Next.js 16, TypeScript, ECharts 6, Vitest, pytest, Playwright.

---

### Task 1: Python visual-transition contract

**Files:**
- Modify: 'apps/agent-ui/agent/poetry_agent/service.py'
- Test: 'apps/agent-ui/agent/tests/test_service.py'

- [ ] **Step 1: Write failing Tool-contract tests**

Add tests named:

~~~python
def test_route_adds_visual_transition_for_coordinate_complete_gap(self):
    result = self.service.generate_poet_route("李白")["payload"]
    a, b = result["scenes"][0:2]
    transition = next(
        row for row in result["visualTransitions"]
        if row["from_id"] == a["id"] and row["to_id"] == b["id"]
    )
    self.assertEqual("visual_transition", transition["kind"])
    self.assertEqual("not_asserted", transition["certainty"])
    self.assertFalse(transition["historical_claim"])
    self.assertEqual("journey", transition["transport_mode"])
    self.assertEqual([[a["lon"], a["lat"]], [b["lon"], b["lat"]]], transition["coords"])

def test_route_skips_visual_transition_when_endpoint_is_unmapped(self):
    result = self.service.generate_poet_route("白居易")["payload"]
    pairs = {(row["from_id"], row["to_id"]) for row in result["visualTransitions"]}
    for a, b in zip(result["scenes"], result["scenes"][1:]):
        if not a["map_eligible"] or not b["map_eligible"]:
            self.assertNotIn((a["id"], b["id"]), pairs)

def test_historical_segment_prevents_duplicate_visual_transition(self):
    result = self.service.generate_poet_route("李清照")["payload"]
    historical = {(row["from_id"], row["to_id"]) for row in result["routeSegments"]}
    visual = {(row["from_id"], row["to_id"]) for row in result["visualTransitions"]}
    self.assertTrue(historical.isdisjoint(visual))
~~~

- [ ] **Step 2: Run the focused tests and verify RED**

Run: 'apps\agent-ui\agent\.venv\Scripts\python.exe -m pytest apps\agent-ui\agent\tests\test_service.py -q'

Expected: failures because 'visualTransitions' does not exist.

- [ ] **Step 3: Implement the visual transition builder**

Add:

~~~python
def build_visual_transitions(
    scenes: list[dict[str, Any]],
    historical_segments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    historical_pairs = {
        (row["from_id"], row["to_id"]) for row in historical_segments
    }
    rows: list[dict[str, Any]] = []
    for start, end in zip(scenes, scenes[1:]):
        pair = (start["id"], end["id"])
        if pair in historical_pairs:
            continue
        if not start.get("map_eligible") or not end.get("map_eligible"):
            continue
        rows.append({
            "from_id": start["id"],
            "to_id": end["id"],
            "coords": [[start["lon"], start["lat"]], [end["lon"], end["lat"]]],
            "kind": "visual_transition",
            "certainty": "not_asserted",
            "historical_claim": False,
            "gap_reason": "adjacent_locatable_scene_gap",
            "transport_mode": "journey",
            "transport_label": "山径行旅",
            "transport_basis": "两幕均有作品节点坐标；实际行路与交通方式未载，仅作镜头转场。",
            "transport_certainty": "unspecified",
        })
    return rows
~~~

Call it after '_select_scenes()' and after historical segments are filtered. Return it as payload key 'visualTransitions'.

- [ ] **Step 4: Verify GREEN and count coverage**

Expected default counts: 49 visual transitions total; per poet 16/8/4/6/8/7 for 李白/杜甫/白居易/苏轼/陆游/李清照.

---

### Task 2: Journey-leg geometry and priority

**Files:**
- Modify: 'apps/agent-ui/web/src/lib/types.ts'
- Modify: 'apps/agent-ui/web/src/lib/journey.ts'
- Test: 'apps/agent-ui/web/src/lib/journey.test.ts'

- [ ] **Step 1: Write failing Vitest cases**

Cover:

~~~ts
it("prefers a forward historical segment over a visual transition")
it("uses a Tool visual transition when history has no direct edge")
it("turns reverse history navigation into a camera transition")
it("samples a deterministic curved path with exact endpoints")
it("uses easeInOutCubic without overshooting")
~~~

- [ ] **Step 2: Run and verify RED**

Run: 'npm --prefix apps/agent-ui/web run test -- journey.test.ts'

- [ ] **Step 3: Define the contract**

Add 'visualTransitions: RouteSegment[]' to 'RoutePayload'. Narrow:

~~~ts
kind: "chronology" | "visual_transition";
certainty: "strict" | "not_asserted";
historical_claim?: boolean;
gap_reason?: "adjacent_locatable_scene_gap";
~~~

Export 'JourneyLeg', 'resolveJourneyLeg', 'easeInOutCubic', 'sampleJourneyPath', and 'interpolateJourneyPath'. Historical direct edges win; direct visual edges are second; reverse history becomes a visual camera leg; missing coordinates return undefined.

- [ ] **Step 4: Implement deterministic curve sampling**

Use 28 quadratic Bézier samples. Derive bend sign from the endpoint IDs, cap perpendicular bend to 12% of geographic distance, and preserve exact first/last coordinates.

- [ ] **Step 5: Verify GREEN**

Run the focused test and the full Vitest suite.

---

### Task 3: Song-print transport glyphs

**Files:**
- Create: 'apps/agent-ui/web/src/components/TransportGlyph.tsx'
- Modify: 'apps/agent-ui/web/src/components/PoetRouteMap.tsx'
- Modify: 'apps/agent-ui/web/src/app/globals.css'

- [ ] **Step 1: Create one transparent inline SVG component**

The component accepts 'mode' and 'moving'. Its 36×42 viewBox anchors location at '(18,38)' and renders five distinct groups:

- boat: indigo hull, sail and one 1px wave accent.
- horse: cinnabar horse/rider side profile.
- carriage: ink canopy, two wheels, cinnabar hubs.
- walk: jade robe, staff and ground point.
- journey: ink mountain notch, curved path and cinnabar endpoint.

Do not render a white disc, rounded container, V tail or blur shadow.

- [ ] **Step 2: Replace Lucide marker icons**

Remove 'CarFront', 'Footprints', 'PersonStanding', and 'Sailboat' imports from 'PoetRouteMap.tsx'. Render 'TransportGlyph' and set 'data-arrived' for the one-shot landing seal.

- [ ] **Step 3: Replace marker CSS**

Use a 36×42 positioning box with 'margin: -38px 0 0 -18px'. Add only a 1px paper-colored SVG outline via paint order, mode-specific micro-motion ≤1px, and a 220ms arrival ring. Preserve 'prefers-reduced-motion'.

---

### Task 4: Route layers and continuous animation

**Files:**
- Modify: 'apps/agent-ui/web/src/components/PoetRouteMap.tsx'
- Modify: 'apps/agent-ui/web/src/app/globals.css'

- [ ] **Step 1: Resolve every click to a JourneyLeg**

Replace 'findRouteSegment' in 'goToScene()' with 'resolveJourneyLeg'. If a leg exists, animate it; if neither endpoint is locatable, arrive directly with '地点坐标未定，已切换到目标诗篇。'

- [ ] **Step 2: Use eased path motion**

Keep raw progress for the percentage. Pass 'easeInOutCubic(rawProgress)' to 'interpolateJourneyPath'. Duration must be clamped to 3200–5500ms. Pause/resume and replay cancellation retain existing behavior.

- [ ] **Step 3: Draw five ECharts line series**

All line data uses 'sampleJourneyPath' and 'polyline: true':

1. Historical guides: indigo solid, 2.4px, 0.78.
2. Visual guides: gray-gold dashed, 1.7px, 0.62.
3. Completed historical/visual legs: theme color, 3px, 0.82.
4. Active paper halo: paper, 7px, 0.9.
5. Active main line: cinnabar, 5px, 0.96.

Add a compact legend for '史料路线' and '镜头转场·路径未载'.

- [ ] **Step 4: Update status and ARIA**

Historical status retains transport evidence. Visual status reads '镜头转场 · 路径未载'. ARIA reports historical and visual counts separately. Method copy states that visual lines connect nodes only and do not assert roads, transport, or speed.

---

### Task 5: Integration review

**Files:**
- Review: all files modified in Tasks 1–4

- [ ] **Step 1: Run static and unit checks in parallel**

~~~powershell
npm --prefix apps/agent-ui/web run lint
npm --prefix apps/agent-ui/web run typecheck
npm --prefix apps/agent-ui/web run test
apps\agent-ui\agent\.venv\Scripts\python.exe -m pytest apps\agent-ui\agent\tests -q
~~~

- [ ] **Step 2: Run production build and offline regression**

~~~powershell
npm --prefix apps/agent-ui/web run build
python tools\check_all.py --offline --keep-going
~~~

Expected: zero failures.

---

### Task 6: Browser acceptance

**Files:**
- Write evidence: 'output/playwright/agent_ui_song_print_*.png'
- Write report: 'output/playwright/agent_ui_song_print_acceptance.json'

- [ ] **Step 1: Start production**

Run: '.\apps\agent-ui\start-dev.ps1 -Production'

- [ ] **Step 2: Validate core journeys**

- 李白 01→02: travelling, journey glyph, visual-transition label, no teleport.
- 李清照 13→14: boat glyph and documented boat evidence.
- 白居易 unmapped adjacency: direct cut and coordinate-gap notice.
- Reverse navigation: camera transition, not false historical evidence.
- Replay during travel: no stale frame writes.

- [ ] **Step 3: Validate visual thresholds**

At 1440×900, 700×900 and 390×844:

- no page-level horizontal overflow;
- console/page errors zero;
- transparent marker background;
- marker anchor within 2px of the interpolated path;
- historical, visual and active lines remain visible;
- active/main RGB distance from guide ≥45;
- screenshots saved under 'output/playwright/'.

## Plan self-review

- Spec coverage: Python contract, icons, path geometry, route layers, copy, accessibility, responsive/browser checks all have tasks.
- Placeholder scan: no TBD/TODO or deferred implementation.
- Type consistency: 'visualTransitions', 'JourneyLeg', 'visual_transition', 'not_asserted' and transport fields are consistent throughout.
- Git note: the workspace has no '.git' metadata, so commit steps are intentionally omitted.
