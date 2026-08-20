"use client";

import { Globe, RotateCcw, Sparkles, X } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";

import { usePoemKnowledge } from "@/components/KnowledgeExplorer";
import { explainGlossarySelection } from "@/lib/knowledge";
import {
  codePointLength,
  codePointOffsetAtUtf16,
  isCurrentSelectionSession,
  placeFloatingElement,
  sliceCodePoints,
  trimCodePointSelection,
} from "@/lib/selection-ui";
import type { FloatingPlacement, RectLike } from "@/lib/selection-ui";
import type {
  KnowledgeGloss,
  KnowledgeGlossarySelectionPayload,
  KnowledgeGlossarySelectionRequest,
  KnowledgePoemPayload,
} from "@/lib/types";

interface InteractivePoemTextProps {
  lines: string[];
  poemId?: string | null;
  className?: string;
  ariaLabel?: string;
}

interface SelectionSession {
  id: string;
  contextKey: string;
  poemId: string | null;
  lineNo: number;
  startOffset: number;
  endOffset: number;
  text: string;
  initialRect: RectLike;
}

type ExplanationMode = KnowledgeGlossarySelectionRequest["mode"];

type ExplanationState =
  | { status: "idle" }
  | { status: "loading"; mode: ExplanationMode }
  | { status: "success"; payload: KnowledgeGlossarySelectionPayload }
  | { status: "error"; mode: ExplanationMode; message: string };

function glossKey(gloss: KnowledgeGloss): string {
  return `${gloss.termId}:${gloss.lineNo}:${gloss.startOffset}:${gloss.endOffset}`;
}

function glossDomId(key: string): string {
  return `poem-gloss-popover-${encodeURIComponent(key)}`;
}

function toRectLike(rect: DOMRect | DOMRectReadOnly): RectLike {
  return {
    left: rect.left,
    top: rect.top,
    right: rect.right,
    bottom: rect.bottom,
    width: rect.width,
    height: rect.height,
  };
}

function unionRects(rects: RectLike[]): RectLike | null {
  const visible = rects.filter((rect) => rect.width > 0 || rect.height > 0);
  if (!visible.length) return null;
  const left = Math.min(...visible.map((rect) => rect.left));
  const top = Math.min(...visible.map((rect) => rect.top));
  const right = Math.max(...visible.map((rect) => rect.right));
  const bottom = Math.max(...visible.map((rect) => rect.bottom));
  return { left, top, right, bottom, width: right - left, height: bottom - top };
}

function isDesktopSelectionPointer(): boolean {
  return typeof window !== "undefined"
    && window.matchMedia("(hover: hover) and (pointer: fine)").matches;
}

function renderSelectionFragment(
  text: string,
  absoluteStart: number,
  selection: SelectionSession | null,
): ReactNode {
  if (!selection) return text;
  const segmentLength = codePointLength(text);
  const absoluteEnd = absoluteStart + segmentLength;
  const selectedStart = Math.max(absoluteStart, selection.startOffset);
  const selectedEnd = Math.min(absoluteEnd, selection.endOffset);
  if (selectedStart >= selectedEnd) return text;
  const localStart = selectedStart - absoluteStart;
  const localEnd = selectedEnd - absoluteStart;
  return (
    <>
      {sliceCodePoints(text, 0, localStart)}
      <mark className="poem-selection-highlight" data-poem-selection-id={selection.id}>
        {sliceCodePoints(text, localStart, localEnd)}
      </mark>
      {sliceCodePoints(text, localEnd)}
    </>
  );
}

function renderLine(
  line: string,
  lineNo: number,
  glosses: KnowledgeGloss[],
  activeKey: string | null,
  selection: SelectionSession | null,
  onSelect: (key: string, trigger: HTMLButtonElement) => void,
) {
  const ranges = glosses
    .filter((gloss) => gloss.lineNo === lineNo)
    .sort((left, right) => left.startOffset - right.startOffset || right.endOffset - left.endOffset);
  const activeSelection = selection?.lineNo === lineNo ? selection : null;
  if (!ranges.length) return renderSelectionFragment(line, 0, activeSelection);

  const parts: ReactNode[] = [];
  const lineLength = codePointLength(line);
  let cursor = 0;
  ranges.forEach((gloss, index) => {
    const start = Math.max(cursor, Math.min(lineLength, gloss.startOffset));
    const end = Math.max(start, Math.min(lineLength, gloss.endOffset));
    if (start > cursor) {
      const plain = sliceCodePoints(line, cursor, start);
      parts.push(
        <span key={`plain-${cursor}-${start}`}>
          {renderSelectionFragment(plain, cursor, activeSelection)}
        </span>,
      );
    }
    if (end <= start) return;
    const key = glossKey(gloss);
    const termText = sliceCodePoints(line, start, end);
    parts.push(
      <button
        key={`${key}-${index}`}
        type="button"
        className="poem-gloss-term"
        aria-expanded={activeKey === key}
        aria-controls={activeKey === key ? glossDomId(key) : undefined}
        aria-label={`${gloss.term}：${gloss.definition}`}
        onClick={(event) => {
          if (window.getSelection()?.isCollapsed === false) return;
          onSelect(key, event.currentTarget);
        }}
        onKeyDown={(event) => {
          if (event.key !== "Enter" && event.key !== " ") return;
          event.preventDefault();
          onSelect(key, event.currentTarget);
        }}
      >
        {renderSelectionFragment(termText, start, activeSelection)}
      </button>,
    );
    cursor = end;
  });
  if (cursor < lineLength) {
    const plain = sliceCodePoints(line, cursor);
    parts.push(
      <span key={`plain-${cursor}-end`}>
        {renderSelectionFragment(plain, cursor, activeSelection)}
      </span>,
    );
  }
  return parts;
}

function PoemLine({
  line,
  lineNo,
  glosses,
  activeKey,
  selection,
  onSelect,
}: {
  line: string;
  lineNo: number;
  glosses: KnowledgeGloss[];
  activeKey: string | null;
  selection: SelectionSession | null;
  onSelect: (key: string, trigger: HTMLButtonElement) => void;
}) {
  return (
    <p data-line-no={lineNo}>
      {renderLine(line, lineNo, glosses, activeKey, selection, onSelect)}
    </p>
  );
}

function samePlacement(left: FloatingPlacement | null, right: FloatingPlacement): boolean {
  return Boolean(
    left
    && Math.abs(left.left - right.left) < 0.5
    && Math.abs(left.top - right.top) < 0.5
    && left.placement === right.placement,
  );
}

export function InteractivePoemText({
  lines,
  poemId,
  className = "",
  ariaLabel = "诗文正文",
}: InteractivePoemTextProps) {
  const rootRef = useRef<HTMLDivElement>(null);
  const selectionUiRef = useRef<HTMLDivElement>(null);
  const glossRef = useRef<HTMLElement>(null);
  const toolbarRef = useRef<HTMLDivElement>(null);
  const selectionCardRef = useRef<HTMLElement>(null);
  const glossCloseRef = useRef<HTMLButtonElement>(null);
  const requestRef = useRef<AbortController | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const activeSelectionIdRef = useRef<string | null>(null);
  const selectionCounterRef = useRef(0);
  const lastPointerTypeRef = useRef("mouse");
  const positionFrameRef = useRef<number | null>(null);
  const [portalHost, setPortalHost] = useState<HTMLElement | null>(null);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [selectedPoemId, setSelectedPoemId] = useState<string | null>(null);
  const [selectedPayload, setSelectedPayload] = useState<KnowledgePoemPayload>();
  const [trigger, setTrigger] = useState<HTMLButtonElement | null>(null);
  const [textSelection, setTextSelection] = useState<SelectionSession | null>(null);
  const [explanation, setExplanation] = useState<ExplanationState>({ status: "idle" });
  const [glossPosition, setGlossPosition] = useState<FloatingPlacement | null>(null);
  const [selectionPosition, setSelectionPosition] = useState<FloatingPlacement | null>(null);
  const { payload } = usePoemKnowledge(poemId);
  const renderLines = useMemo(
    () => payload?.lines?.length ? payload.lines.map((line) => line.text) : lines,
    [lines, payload],
  );
  const contextKey = `${poemId ?? ""}\n${renderLines.join("\n")}`;
  const glosses = useMemo(() => {
    if (!payload?.glosses?.length || !payload.lines?.length) return [];
    const lineTextByNo = new Map(payload.lines.map((line) => [line.lineNo, line.text]));
    return payload.glosses.filter((gloss) => {
      const lineText = lineTextByNo.get(gloss.lineNo);
      return Boolean(
        lineText
        && Number.isInteger(gloss.startOffset)
        && Number.isInteger(gloss.endOffset)
        && gloss.startOffset >= 0
        && gloss.endOffset > gloss.startOffset
        && gloss.endOffset <= codePointLength(lineText),
      );
    });
  }, [payload]);
  const glossByKey = useMemo(
    () => new Map(glosses.map((gloss) => [glossKey(gloss), gloss])),
    [glosses],
  );
  const activeKey = selectedKey
    && selectedPoemId === (poemId ?? null)
    && selectedPayload === payload
    && glossByKey.has(selectedKey)
    ? selectedKey
    : null;
  const activeGloss = activeKey ? glossByKey.get(activeKey) : undefined;
  const activeDomId = activeKey ? glossDomId(activeKey) : undefined;
  const activeTextSelection = textSelection?.contextKey === contextKey ? textSelection : null;

  const closePopover = useCallback((restoreFocus: boolean) => {
    const focusTarget = triggerRef.current;
    setSelectedKey(null);
    setSelectedPoemId(null);
    setSelectedPayload(undefined);
    setTrigger(null);
    setGlossPosition(null);
    triggerRef.current = null;
    if (restoreFocus && focusTarget?.isConnected) {
      window.requestAnimationFrame(() => focusTarget.focus({ preventScroll: true }));
    }
  }, []);

  const closeSelection = useCallback(() => {
    requestRef.current?.abort();
    requestRef.current = null;
    activeSelectionIdRef.current = null;
    setTextSelection(null);
    setSelectionPosition(null);
    setExplanation({ status: "idle" });
    window.getSelection()?.removeAllRanges();
  }, []);

  const closeAll = useCallback(() => {
    closePopover(false);
    closeSelection();
  }, [closePopover, closeSelection]);

  const handleSelect = useCallback((
    key: string,
    nextTrigger: HTMLButtonElement,
  ) => {
    closeSelection();
    setSelectedPoemId(poemId ?? null);
    setSelectedPayload(payload);
    setTrigger(nextTrigger);
    triggerRef.current = nextTrigger;
    setGlossPosition(null);
    setSelectedKey(key);
  }, [closeSelection, payload, poemId]);

  const captureNativeSelection = useCallback(() => {
    const selection = window.getSelection();
    if (!selection || selection.isCollapsed || selection.rangeCount !== 1) {
      if (explanation.status === "idle") closeSelection();
      return;
    }
    const range = selection.getRangeAt(0);
    const startElement = range.startContainer.nodeType === Node.ELEMENT_NODE
      ? range.startContainer as Element
      : range.startContainer.parentElement;
    const endElement = range.endContainer.nodeType === Node.ELEMENT_NODE
      ? range.endContainer as Element
      : range.endContainer.parentElement;
    const startLine = startElement?.closest<HTMLElement>("[data-line-no]");
    const endLine = endElement?.closest<HTMLElement>("[data-line-no]");
    if (!startLine || startLine !== endLine || !rootRef.current?.contains(startLine)) {
      if (explanation.status === "idle") closeSelection();
      return;
    }

    const prefix = document.createRange();
    prefix.selectNodeContents(startLine);
    prefix.setEnd(range.startContainer, range.startOffset);
    const lineText = startLine.textContent ?? "";
    const startOffset = codePointOffsetAtUtf16(lineText, prefix.toString().length);
    const endOffset = startOffset + codePointLength(range.toString());
    const trimmed = trimCodePointSelection(lineText, startOffset, endOffset);
    if (
      !trimmed
      || codePointLength(trimmed.text) > 32
      || !/[\p{L}\p{N}\p{Script=Han}]/u.test(trimmed.text)
    ) {
      if (explanation.status === "idle") closeSelection();
      return;
    }

    requestRef.current?.abort();
    closePopover(false);
    selectionCounterRef.current += 1;
    const id = `selection-${selectionCounterRef.current}`;
    const session: SelectionSession = {
      id,
      contextKey,
      poemId: poemId ?? null,
      lineNo: Number(startLine.dataset.lineNo),
      startOffset: trimmed.startOffset,
      endOffset: trimmed.endOffset,
      text: trimmed.text,
      initialRect: toRectLike(range.getBoundingClientRect()),
    };
    activeSelectionIdRef.current = id;
    setExplanation({ status: "idle" });
    setSelectionPosition(null);
    setTextSelection(session);
    window.requestAnimationFrame(() => window.getSelection()?.removeAllRanges());
  }, [closePopover, closeSelection, contextKey, explanation.status, poemId]);

  const requestExplanation = useCallback(async (mode: ExplanationMode) => {
    const session = activeTextSelection;
    if (!poemId || !session) return;
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    const sessionId = session.id;
    setExplanation({ status: "loading", mode });
    try {
      const response = await explainGlossarySelection({
        poemId,
        lineNo: session.lineNo,
        startOffset: session.startOffset,
        endOffset: session.endOffset,
        mode,
      }, controller.signal);
      if (!controller.signal.aborted && isCurrentSelectionSession(activeSelectionIdRef.current, sessionId)) {
        setExplanation({ status: "success", payload: response.payload });
      }
    } catch (error) {
      if (!controller.signal.aborted && isCurrentSelectionSession(activeSelectionIdRef.current, sessionId)) {
        setExplanation({
          status: "error",
          mode,
          message: error instanceof Error ? error.message : "解释请求失败，请稍后重试",
        });
      }
    }
  }, [activeTextSelection, poemId]);

  const updatePositions = useCallback(() => {
    const root = rootRef.current;
    if (!root) return;
    const viewport = { width: window.innerWidth, height: window.innerHeight };
    const containerElement = root.closest<HTMLElement>(".journey-poem-card, .scene-poem") ?? root;
    const container = toRectLike(containerElement.getBoundingClientRect());

    if (activeGloss && trigger?.isConnected && glossRef.current) {
      const next = placeFloatingElement({
        anchor: toRectLike(trigger.getBoundingClientRect()),
        element: toRectLike(glossRef.current.getBoundingClientRect()),
        viewport,
        container,
        dockWhenNeeded: true,
        gap: 10,
      });
      setGlossPosition((current) => samePlacement(current, next) ? current : next);
    }

    if (activeTextSelection) {
      const markers = Array.from(
        root.querySelectorAll<HTMLElement>(`[data-poem-selection-id="${activeTextSelection.id}"]`),
      );
      const anchor = unionRects(markers.map((marker) => toRectLike(marker.getBoundingClientRect())))
        ?? activeTextSelection.initialRect;
      const panel = explanation.status === "idle" ? toolbarRef.current : selectionCardRef.current;
      if (panel) {
        const next = placeFloatingElement({
          anchor,
          element: toRectLike(panel.getBoundingClientRect()),
          viewport,
          container,
          dockWhenNeeded: explanation.status !== "idle",
          gap: 8,
        });
        setSelectionPosition((current) => samePlacement(current, next) ? current : next);
      }
    }
  }, [activeGloss, activeTextSelection, explanation.status, trigger]);

  const schedulePositionUpdate = useCallback(() => {
    if (positionFrameRef.current !== null) window.cancelAnimationFrame(positionFrameRef.current);
    positionFrameRef.current = window.requestAnimationFrame(() => {
      positionFrameRef.current = null;
      updatePositions();
    });
  }, [updatePositions]);

  useEffect(() => {
    const mountFrame = window.requestAnimationFrame(() => setPortalHost(document.body));
    return () => {
      window.cancelAnimationFrame(mountFrame);
      if (positionFrameRef.current !== null) window.cancelAnimationFrame(positionFrameRef.current);
    };
  }, []);

  useLayoutEffect(() => {
    if (portalHost) schedulePositionUpdate();
  }, [activeGloss, activeTextSelection, explanation, portalHost, schedulePositionUpdate]);

  useEffect(() => {
    const onPointerDown = (event: PointerEvent) => {
      lastPointerTypeRef.current = event.pointerType;
      if (!activeTextSelection || explanation.status !== "idle") return;
      const target = event.target as Node;
      if (!selectionUiRef.current?.contains(target)) closeSelection();
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (activeTextSelection) {
        event.preventDefault();
        closeSelection();
      } else if (activeGloss) {
        event.preventDefault();
        closePopover(true);
      }
    };
    const onKeyUp = (event: KeyboardEvent) => {
      if (!event.shiftKey || !["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End"].includes(event.key)) return;
      if (!isDesktopSelectionPointer()) return;
      captureNativeSelection();
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    document.addEventListener("keyup", onKeyUp);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("keyup", onKeyUp);
    };
  }, [activeGloss, activeTextSelection, captureNativeSelection, closePopover, closeSelection, explanation.status]);

  useEffect(() => {
    const onScroll = () => {
      if (activeTextSelection && explanation.status === "idle") {
        closeSelection();
        return;
      }
      schedulePositionUpdate();
    };
    const onResize = () => {
      if (activeTextSelection && explanation.status === "idle") {
        closeSelection();
        return;
      }
      schedulePositionUpdate();
    };
    window.addEventListener("scroll", onScroll, true);
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("scroll", onScroll, true);
      window.removeEventListener("resize", onResize);
    };
  }, [activeTextSelection, closeSelection, explanation.status, schedulePositionUpdate]);

  useEffect(() => closeAll, [closeAll, contextKey]);

  useEffect(() => {
    if (activeKey) glossCloseRef.current?.focus({ preventScroll: true });
  }, [activeKey]);

  const portal = portalHost ? createPortal(
    <div ref={selectionUiRef} className="poem-selection-ui">
      {activeGloss ? (
        <aside
          id={activeDomId}
          ref={glossRef}
          className="poem-gloss-popover"
          role="dialog"
          aria-label={`${activeGloss.term}释义`}
          data-placement={glossPosition?.placement}
          style={{
            left: glossPosition?.left ?? 12,
            top: glossPosition?.top ?? 12,
            visibility: glossPosition ? "visible" : "hidden",
          }}
        >
          <div className="poem-gloss-popover-head">
            <strong>{activeGloss.term}</strong>
            <button
              type="button"
              className="poem-gloss-close"
              aria-label="关闭释义"
              title="关闭释义"
              ref={glossCloseRef}
              onClick={() => closePopover(true)}
            >
              <X size={14} aria-hidden="true" />
            </button>
          </div>
          <p>{activeGloss.definition}</p>
          {activeGloss.inContext ? <p><b>句中：</b>{activeGloss.inContext}</p> : null}
          {activeGloss.category ? <span>{activeGloss.category}</span> : null}
          {activeGloss.sourceNote ? <small>{activeGloss.sourceNote}</small> : null}
        </aside>
      ) : null}
      {activeTextSelection && explanation.status === "idle" ? (
        <div
          ref={toolbarRef}
          className="poem-selection-toolbar"
          role="toolbar"
          aria-label={`解释“${activeTextSelection.text}”`}
          data-placement={selectionPosition?.placement}
          style={{
            left: selectionPosition?.left ?? activeTextSelection.initialRect.left,
            top: selectionPosition?.top ?? activeTextSelection.initialRect.top,
            visibility: selectionPosition ? "visible" : "hidden",
          }}
        >
          <button type="button" onClick={() => void requestExplanation("model")}>
            <Sparkles size={14} aria-hidden="true" />
            AI 释义
          </button>
          <button
            type="button"
            className="poem-selection-icon-button"
            aria-label="联网查证"
            title="联网查证"
            onClick={() => void requestExplanation("web")}
          >
            <Globe size={14} aria-hidden="true" />
          </button>
          <button
            type="button"
            className="poem-selection-icon-button"
            aria-label="关闭解释工具"
            title="关闭"
            onClick={closeSelection}
          >
            <X size={14} aria-hidden="true" />
          </button>
        </div>
      ) : null}
      {activeTextSelection && explanation.status !== "idle" ? (
        <aside
          ref={selectionCardRef}
          className="poem-selection-card"
          role="dialog"
          aria-live="polite"
          aria-label={`“${activeTextSelection.text}”的释义`}
          data-placement={selectionPosition?.placement}
          style={{
            left: selectionPosition?.left ?? activeTextSelection.initialRect.left,
            top: selectionPosition?.top ?? activeTextSelection.initialRect.bottom,
            visibility: selectionPosition ? "visible" : "hidden",
          }}
        >
          <div className="poem-selection-card-head">
            <strong>{explanation.status === "success" ? explanation.payload.term || activeTextSelection.text : activeTextSelection.text}</strong>
            <button
              type="button"
              className="poem-gloss-close"
              aria-label="关闭解释结果"
              title="关闭解释结果"
              onClick={closeSelection}
            >
              <X size={14} aria-hidden="true" />
            </button>
          </div>
          {explanation.status === "loading" ? (
            <p>{explanation.mode === "web" ? "正在联网查证…" : "正在解释…"}</p>
          ) : explanation.status === "error" ? (
            <>
              <p className="is-error">{explanation.message}</p>
              <button
                type="button"
                className="poem-selection-retry"
                onClick={() => void requestExplanation(explanation.mode)}
              >
                <RotateCcw size={13} aria-hidden="true" />
                重试
              </button>
            </>
          ) : (
            <>
              <p>{explanation.payload.definition}</p>
              {explanation.payload.inContext ? <p><b>句中义：</b>{explanation.payload.inContext}</p> : null}
              <div className="poem-selection-meta">
                {explanation.payload.category ? <span>{explanation.payload.category}</span> : null}
                <span>{explanation.payload.method} · {explanation.payload.reviewStatus === "draft" ? "待审" : "已发布"}</span>
              </div>
              {explanation.payload.sourceNote ? <small>{explanation.payload.sourceNote}</small> : null}
              {explanation.payload.sources?.length ? (
                <ul>
                  {explanation.payload.sources.map((source) => (
                    <li key={source.url}><a href={source.url} target="_blank" rel="noreferrer">{source.title}</a></li>
                  ))}
                </ul>
              ) : null}
              {explanation.payload.draftId ? <small className="is-saved">已存入待审词库</small> : null}
            </>
          )}
        </aside>
      ) : null}
    </div>,
    portalHost,
  ) : null;

  return (
    <>
      <div
        ref={rootRef}
        className={`interactive-poem-text ${className}`}
        aria-label={ariaLabel}
        onPointerDown={(event) => { lastPointerTypeRef.current = event.pointerType; }}
        onMouseUp={(event) => {
          if (event.button !== 0 || lastPointerTypeRef.current !== "mouse" || !isDesktopSelectionPointer()) return;
          captureNativeSelection();
        }}
      >
        {renderLines.map((line, index) => (
          <PoemLine
            key={`${index}-${line}`}
            line={line}
            lineNo={index + 1}
            glosses={glosses}
            activeKey={activeKey}
            selection={activeTextSelection}
            onSelect={handleSelect}
          />
        ))}
      </div>
      {portal}
    </>
  );
}
