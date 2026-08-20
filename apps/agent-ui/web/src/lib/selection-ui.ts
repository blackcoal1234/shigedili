export interface RectLike {
  left: number;
  top: number;
  right: number;
  bottom: number;
  width: number;
  height: number;
}

export interface FloatingPlacement {
  left: number;
  top: number;
  placement: "above" | "below" | "docked";
}

interface FloatingPlacementInput {
  anchor: RectLike;
  element: Pick<RectLike, "width" | "height">;
  viewport: { width: number; height: number };
  container?: RectLike | null;
  dockWhenNeeded?: boolean;
  gap?: number;
  margin?: number;
}

function clamp(value: number, minimum: number, maximum: number): number {
  if (maximum < minimum) return minimum;
  return Math.min(Math.max(value, minimum), maximum);
}

export function codePointLength(value: string): number {
  return Array.from(value).length;
}

export function sliceCodePoints(value: string, start: number, end?: number): string {
  return Array.from(value).slice(start, end).join("");
}

export function codePointOffsetAtUtf16(value: string, utf16Offset: number): number {
  return codePointLength(value.slice(0, utf16Offset));
}

export function utf16OffsetAtCodePoint(value: string, codePointOffset: number): number {
  return sliceCodePoints(value, 0, codePointOffset).length;
}

export function isCurrentSelectionSession(
  activeSessionId: string | null,
  responseSessionId: string,
): boolean {
  return activeSessionId === responseSessionId;
}

export function trimCodePointSelection(
  line: string,
  startOffset: number,
  endOffset: number,
): { startOffset: number; endOffset: number; text: string } | null {
  const characters = Array.from(line);
  let start = Math.max(0, Math.min(characters.length, startOffset));
  let end = Math.max(start, Math.min(characters.length, endOffset));
  while (start < end && /\s/u.test(characters[start] ?? "")) start += 1;
  while (end > start && /\s/u.test(characters[end - 1] ?? "")) end -= 1;
  if (start === end) return null;
  return { startOffset: start, endOffset: end, text: characters.slice(start, end).join("") };
}

export function isRectVisible(anchor: RectLike, container?: RectLike | null): boolean {
  if (anchor.right <= 0 || anchor.bottom <= 0) return false;
  if (!container) return true;
  return anchor.right > container.left
    && anchor.left < container.right
    && anchor.bottom > container.top
    && anchor.top < container.bottom;
}

export function placeFloatingElement({
  anchor,
  element,
  viewport,
  container,
  dockWhenNeeded = false,
  gap = 8,
  margin = 12,
}: FloatingPlacementInput): FloatingPlacement {
  const maxLeft = Math.max(margin, viewport.width - element.width - margin);
  const left = clamp(anchor.left + (anchor.width - element.width) / 2, margin, maxLeft);
  const above = anchor.top - element.height - gap;
  const below = anchor.bottom + gap;
  const anchorVisible = isRectVisible(anchor, container)
    && anchor.left < viewport.width
    && anchor.top < viewport.height;

  if (anchorVisible && above >= margin) return { left, top: above, placement: "above" };
  if (anchorVisible && below + element.height <= viewport.height - margin) {
    return { left, top: below, placement: "below" };
  }
  if (!dockWhenNeeded) {
    return {
      left,
      top: clamp(below, margin, Math.max(margin, viewport.height - element.height - margin)),
      placement: "below",
    };
  }

  const boundary = container ?? {
    left: margin,
    top: margin,
    right: viewport.width - margin,
    bottom: viewport.height - margin,
    width: viewport.width - margin * 2,
    height: viewport.height - margin * 2,
  };
  const visibleLeft = clamp(boundary.left, margin, viewport.width - margin);
  const visibleRight = clamp(boundary.right, margin, viewport.width - margin);
  const visibleTop = clamp(boundary.top, margin, viewport.height - margin);
  const visibleBottom = clamp(boundary.bottom, margin, viewport.height - margin);
  const dockLeft = clamp(
    visibleRight - element.width - gap,
    margin,
    Math.max(margin, viewport.width - element.width - margin),
  );
  let dockTop: number;
  if (anchor.bottom <= visibleTop) {
    dockTop = visibleTop + gap;
  } else if (anchor.top >= visibleBottom) {
    dockTop = visibleBottom - element.height - gap;
  } else {
    const roomBelow = visibleBottom - anchor.bottom;
    const roomAbove = anchor.top - visibleTop;
    dockTop = roomBelow >= roomAbove
      ? visibleBottom - element.height - gap
      : visibleTop + gap;
  }
  return {
    left: Number.isFinite(dockLeft) ? dockLeft : visibleLeft,
    top: clamp(dockTop, margin, Math.max(margin, viewport.height - element.height - margin)),
    placement: "docked",
  };
}
