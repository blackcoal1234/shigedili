import { describe, expect, it } from "vitest";

import {
  buildToolBody,
  isImageryPayload,
  isRoutePayload,
  isScenePayload,
  payloadError,
  scenePlaybackDelayMs,
} from "./workbench";
import type { ToolResponse, WorkbenchPayload } from "./types";

describe("workbench tool contracts", () => {
  it("builds deterministic request bodies for all three tools", () => {
    expect(buildToolBody("route", "李白")).toEqual({
      poet: "李白",
      include_approximate: true,
      include_disputed: true,
    });
    expect(buildToolBody("scenes", "杜甫")).toEqual({ poet: "杜甫", autoplay: false });
    expect(buildToolBody("imagery", "")).toEqual({ limit: 8 });
  });

  it("clamps scene playback duration and supplies a stable default", () => {
    expect(scenePlaybackDelayMs(undefined)).toBe(12_000);
    expect(scenePlaybackDelayMs(0.2)).toBe(1_000);
    expect(scenePlaybackDelayMs(90)).toBe(60_000);
  });

  it("distinguishes route, scene, and imagery payloads by contract fields", () => {
    const route = { scenes: [], routeSegments: [] } as unknown as WorkbenchPayload;
    const scenes = { mode: "manual_step", scenes: [] } as unknown as WorkbenchPayload;
    const imagery = { comparisons: [] } as unknown as WorkbenchPayload;
    expect(isRoutePayload(route)).toBe(true);
    expect(isScenePayload(route)).toBe(false);
    expect(isScenePayload(scenes)).toBe(true);
    expect(isImageryPayload(imagery)).toBe(true);
  });

  it("keeps evidence insufficiency renderable while surfacing hard failures", () => {
    const base = {
      schemaVersion: "1",
      sourceHashes: {},
      methodNote: "fixture",
    };
    const insufficient = {
      ...base,
      status: "insufficient_evidence",
      payload: { missingFacts: ["year"] },
    } as unknown as ToolResponse<WorkbenchPayload>;
    const invalid = {
      ...base,
      status: "invalid_request",
      payload: { error: "poet is required" },
    } as unknown as ToolResponse<WorkbenchPayload>;
    expect(payloadError(insufficient)).toBeNull();
    expect(payloadError(invalid)).toBe("poet is required");
  });
});
