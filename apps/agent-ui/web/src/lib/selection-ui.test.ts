import { describe, expect, it } from "vitest";

import {
  codePointLength,
  codePointOffsetAtUtf16,
  isCurrentSelectionSession,
  placeFloatingElement,
  sliceCodePoints,
  trimCodePointSelection,
  utf16OffsetAtCodePoint,
} from "./selection-ui";

describe("selection ui helpers", () => {
  it("keeps offsets in Unicode code points", () => {
    const text = "明𠮷月";
    expect(codePointLength(text)).toBe(3);
    expect(sliceCodePoints(text, 1, 2)).toBe("𠮷");
    expect(codePointOffsetAtUtf16(text, 3)).toBe(2);
    expect(utf16OffsetAtCodePoint(text, 2)).toBe(3);
  });

  it("trims surrounding whitespace while preserving offsets", () => {
    expect(trimCodePointSelection("山  明月  海", 1, 7)).toEqual({
      startOffset: 3,
      endOffset: 5,
      text: "明月",
    });
  });

  it("rejects a response from a replaced selection session", () => {
    expect(isCurrentSelectionSession("selection-2", "selection-1")).toBe(false);
    expect(isCurrentSelectionSession("selection-2", "selection-2")).toBe(true);
    expect(isCurrentSelectionSession(null, "selection-2")).toBe(false);
  });

  it("places a compact toolbar above its anchor", () => {
    expect(placeFloatingElement({
      anchor: { left: 100, top: 120, right: 180, bottom: 145, width: 80, height: 25 },
      element: { width: 120, height: 36 },
      viewport: { width: 800, height: 600 },
    })).toEqual({ left: 80, top: 76, placement: "above" });
  });

  it("moves below the anchor when the top edge is crowded", () => {
    expect(placeFloatingElement({
      anchor: { left: 20, top: 10, right: 80, bottom: 30, width: 60, height: 20 },
      element: { width: 100, height: 36 },
      viewport: { width: 320, height: 480 },
    })).toEqual({ left: 12, top: 38, placement: "below" });
  });

  it("docks a persistent result when its anchor leaves the poem card", () => {
    const placement = placeFloatingElement({
      anchor: { left: 40, top: -80, right: 100, bottom: -50, width: 60, height: 30 },
      element: { width: 220, height: 160 },
      viewport: { width: 800, height: 600 },
      container: { left: 24, top: 100, right: 394, bottom: 500, width: 370, height: 400 },
      dockWhenNeeded: true,
    });
    expect(placement).toEqual({ left: 166, top: 108, placement: "docked" });
  });
});
