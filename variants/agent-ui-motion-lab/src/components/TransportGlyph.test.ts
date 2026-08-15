import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { TransportGlyph } from "./TransportGlyph";
import type { RouteSegment } from "@/lib/types";

const modes: RouteSegment["transport_mode"][] = [
  "boat",
  "horse",
  "carriage",
  "walk",
  "journey",
];

describe("TransportGlyph", () => {
  it.each(modes)("renders a transparent Song-print %s glyph", (mode) => {
    const html = renderToStaticMarkup(createElement(TransportGlyph, {
      mode,
      moving: true,
      arrived: false,
    }));

    expect(html).toContain('viewBox="0 0 36 42"');
    expect(html).toContain(`data-mode="${mode}"`);
    expect(html).toContain('data-anchor="18,38"');
    expect(html).not.toMatch(/filter=|#fff|white/i);
  });

  it("marks arrival without adding an opaque container", () => {
    const html = renderToStaticMarkup(createElement(TransportGlyph, {
      mode: "journey",
      moving: false,
      arrived: true,
    }));

    expect(html).toContain('data-arrived="true"');
    expect(html).not.toContain("background");
  });
});
