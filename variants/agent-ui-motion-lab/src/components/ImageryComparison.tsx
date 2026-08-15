"use client";

import type { EChartsOption } from "echarts";
import ReactECharts from "echarts-for-react";
import { BarChart3, BookOpenText } from "lucide-react";
import type { CSSProperties, KeyboardEvent } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { EmptyState } from "@/components/StateViews";
import {
  counterValue,
  imageryMotionDuration,
  shouldChangeImagerySelection,
  shouldSettleImageryCounterImmediately,
} from "../lib/imageryMotion";
import type { EffectiveMotionProfile } from "../lib/motion";
import type { ImageryEvidence, ImageryPayload } from "@/lib/types";

interface ImageryComparisonProps {
  payload: ImageryPayload;
  motionProfile?: EffectiveMotionProfile;
}

interface DisplayedRates {
  tang: number;
  song: number;
}

interface EvidenceGroup {
  dynasty: string;
  evidence: ImageryEvidence[];
  startIndex: number;
}

type TideStyle = CSSProperties & {
  "--imagery-motion-duration": string;
  "--tang-tide-level": string;
  "--song-tide-level": string;
};

type EvidenceStyle = CSSProperties & {
  "--imagery-evidence-order": number;
};

const TANG_COLOR = "#344f43";
const SONG_COLOR = "#a33a2b";

function dynastyTone(dynasty: string): "tang" | "song" | "other" {
  if (dynasty.includes("唐")) return "tang";
  if (dynasty.includes("宋")) return "song";
  return "other";
}

function groupEvidence(evidence: ImageryEvidence[]): EvidenceGroup[] {
  const groups = new Map<string, ImageryEvidence[]>();
  for (const item of evidence) {
    const dynastyItems = groups.get(item.dynasty) ?? [];
    dynastyItems.push(item);
    groups.set(item.dynasty, dynastyItems);
  }

  let startIndex = 0;
  return Array.from(groups, ([dynasty, dynastyEvidence]) => {
    const group = { dynasty, evidence: dynastyEvidence, startIndex };
    startIndex += dynastyEvidence.length;
    return group;
  });
}

function tideLevel(value: number, maximum: number): string {
  if (maximum <= 0) return "0%";
  return `${Math.round((Math.max(0, value) / maximum) * 72)}%`;
}

export function ImageryComparison({
  payload,
  motionProfile = "cinematic",
}: ImageryComparisonProps) {
  const initialSelection = payload.comparisons[0];
  const [selectedWord, setSelectedWord] = useState(initialSelection?.word ?? "");
  const selected = payload.comparisons.find((row) => row.word === selectedWord)
    ?? initialSelection;
  const selectedIndex = selected
    ? Math.max(0, payload.comparisons.findIndex((row) => row.word === selected.word))
    : 0;
  const motionDuration = imageryMotionDuration(motionProfile);
  const [displayedRates, setDisplayedRates] = useState<DisplayedRates>(() => ({
    tang: initialSelection?.tang.ratePer10k ?? 0,
    song: initialSelection?.song.ratePer10k ?? 0,
  }));
  const [documentVisible, setDocumentVisible] = useState(true);
  const [settledMotionKey, setSettledMotionKey] = useState<string | null>(null);
  const displayedRatesRef = useRef(displayedRates);
  const animationFrameRef = useRef<number | null>(null);
  const termButtonRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const selectionMotionKey = `${selected?.word ?? ""}:${motionProfile}`;
  const selectionMotionSettled = settledMotionKey === selectionMotionKey;
  const visualMotionEnabled = motionDuration > 0
    && documentVisible
    && !selectionMotionSettled;

  const cancelCounterAnimation = useCallback(() => {
    if (animationFrameRef.current !== null && typeof window !== "undefined") {
      window.cancelAnimationFrame(animationFrameRef.current);
      animationFrameRef.current = null;
    }
  }, []);

  const publishRates = useCallback((rates: DisplayedRates) => {
    displayedRatesRef.current = rates;
    setDisplayedRates(rates);
  }, []);

  const selectWord = useCallback((word: string) => {
    const nextSelection = payload.comparisons.find((row) => row.word === word);
    if (!nextSelection || !shouldChangeImagerySelection(selectedWord, word)) return;

    cancelCounterAnimation();
    if (motionProfile === "off") {
      publishRates({
        tang: nextSelection.tang.ratePer10k,
        song: nextSelection.song.ratePer10k,
      });
    }
    setSelectedWord(word);
  }, [cancelCounterAnimation, motionProfile, payload.comparisons, publishRates, selectedWord]);

  useEffect(() => {
    if (!selected) return;

    cancelCounterAnimation();
    const from = displayedRatesRef.current;
    const target = {
      tang: selected.tang.ratePer10k,
      song: selected.song.ratePer10k,
    };
    const animationSupported = typeof window !== "undefined"
      && typeof window.requestAnimationFrame === "function";
    const visibilityState = typeof document === "undefined"
      ? "hidden"
      : document.visibilityState;

    if (
      shouldSettleImageryCounterImmediately(
        motionDuration,
        animationSupported,
        visibilityState,
      )
      || (from.tang === target.tang && from.song === target.song)
    ) {
      if (from.tang !== target.tang || from.song !== target.song) publishRates(target);
      return;
    }

    let startedAt: number | null = null;
    const tick = (timestamp: number) => {
      if (document.visibilityState === "hidden") {
        publishRates(target);
        animationFrameRef.current = null;
        return;
      }

      startedAt ??= timestamp;
      const progress = Math.min(1, (timestamp - startedAt) / motionDuration);
      publishRates({
        tang: counterValue(from.tang, target.tang, progress),
        song: counterValue(from.song, target.song, progress),
      });

      if (progress < 1) {
        animationFrameRef.current = window.requestAnimationFrame(tick);
      } else {
        animationFrameRef.current = null;
      }
    };

    animationFrameRef.current = window.requestAnimationFrame(tick);
    return cancelCounterAnimation;
  }, [
    cancelCounterAnimation,
    motionDuration,
    publishRates,
    selected,
  ]);

  useEffect(() => {
    if (!selected || typeof document === "undefined") return;

    const syncDocumentVisibility = () => {
      const nextDocumentVisible = document.visibilityState !== "hidden";
      setDocumentVisible(nextDocumentVisible);
      if (nextDocumentVisible) return;

      setSettledMotionKey(selectionMotionKey);
      cancelCounterAnimation();
      publishRates({
        tang: selected.tang.ratePer10k,
        song: selected.song.ratePer10k,
      });
    };

    syncDocumentVisibility();
    document.addEventListener("visibilitychange", syncDocumentVisibility);
    return () => document.removeEventListener("visibilitychange", syncDocumentVisibility);
  }, [cancelCounterAnimation, publishRates, selected, selectionMotionKey]);

  const option = useMemo<EChartsOption>(() => {
    const activeWord = selected?.word ?? "";
    const tangData = payload.comparisons.map((row) => ({
      id: `tang-${row.word}`,
      value: row.tang.ratePer10k,
      itemStyle: {
        borderRadius: [2, 2, 0, 0],
        opacity: row.word === activeWord ? 1 : 0.26,
      },
    }));
    const songData = payload.comparisons.map((row) => ({
      id: `song-${row.word}`,
      value: row.song.ratePer10k,
      itemStyle: {
        borderRadius: [2, 2, 0, 0],
        opacity: row.word === activeWord ? 1 : 0.26,
      },
    }));

    return {
      animation: visualMotionEnabled,
      animationDuration: visualMotionEnabled ? motionDuration : 0,
      animationDurationUpdate: visualMotionEnabled ? motionDuration : 0,
      animationEasing: "cubicOut",
      animationEasingUpdate: "cubicInOut",
      aria: { enabled: true, decal: { show: false } },
      color: [TANG_COLOR, SONG_COLOR],
      legend: {
        top: 2,
        right: 12,
        textStyle: { color: "#5f594f", fontSize: 11 },
        itemWidth: 14,
        itemHeight: 8,
      },
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "shadow" },
        valueFormatter: (value) => `${Number(value).toFixed(2)} 次 / 万字`,
        backgroundColor: "#fffdf7",
        borderColor: "rgba(52,45,35,.25)",
        textStyle: { color: "#211f1a", fontFamily: "Microsoft YaHei", fontSize: 12 },
      },
      grid: { left: 46, right: 22, top: 48, bottom: 44, containLabel: true },
      xAxis: {
        type: "category",
        data: payload.comparisons.map((row) => row.word),
        axisTick: { show: false },
        axisLine: { lineStyle: { color: "#b8ae9c" } },
        axisLabel: { color: "#4d493f", fontFamily: "Microsoft YaHei", fontSize: 12 },
      },
      yAxis: {
        type: "value",
        name: "每万字率",
        nameTextStyle: { color: "#777064", fontSize: 11 },
        axisLabel: { color: "#777064", fontSize: 10 },
        splitLine: { lineStyle: { color: "rgba(73,64,50,.09)" } },
      },
      series: [
        {
          id: "imagery-tang",
          name: "唐",
          type: "bar",
          barMaxWidth: 22,
          universalTransition: visualMotionEnabled,
          data: tangData,
        },
        {
          id: "imagery-song",
          name: "宋",
          type: "bar",
          barMaxWidth: 22,
          universalTransition: visualMotionEnabled,
          data: songData,
        },
      ],
    };
  }, [motionDuration, payload.comparisons, selected?.word, visualMotionEnabled]);

  const chartEvents = useMemo(() => ({
    click: (params: { name?: string }) => {
      if (params.name) selectWord(params.name);
    },
  }), [selectWord]);

  const evidenceGroups = useMemo(
    () => groupEvidence(selected?.corpusEvidence ?? []),
    [selected?.corpusEvidence],
  );
  const tideMaximum = selected
    ? Math.max(selected.tang.ratePer10k, selected.song.ratePer10k)
    : 0;
  const tideStyle: TideStyle = {
    "--imagery-motion-duration": `${motionDuration}ms`,
    "--tang-tide-level": tideLevel(selected?.tang.ratePer10k ?? 0, tideMaximum),
    "--song-tide-level": tideLevel(selected?.song.ratePer10k ?? 0, tideMaximum),
  };

  const handleTermKeyDown = useCallback((
    event: KeyboardEvent<HTMLButtonElement>,
    index: number,
  ) => {
    const termCount = payload.comparisons.length;
    if (termCount === 0) return;

    let nextIndex: number | null = null;
    if (event.key === "ArrowLeft") nextIndex = (index - 1 + termCount) % termCount;
    if (event.key === "ArrowRight") nextIndex = (index + 1) % termCount;
    if (event.key === "Home") nextIndex = 0;
    if (event.key === "End") nextIndex = termCount - 1;
    if (nextIndex === null) return;

    event.preventDefault();
    selectWord(payload.comparisons[nextIndex]?.word ?? "");
    termButtonRefs.current[nextIndex]?.focus();
  }, [payload.comparisons, selectWord]);

  if (!selected) {
    return <EmptyState title="没有意象比较结果" detail="审核词表未返回可比较记录。" />;
  }

  return (
    <section
      className="imagery-layout"
      aria-labelledby="imagery-title"
      data-document-visible={documentVisible}
      data-motion-profile={motionProfile}
      data-visibility-settled={selectionMotionSettled}
      style={tideStyle}
    >
      <div className="visualization-panel imagery-chart-panel">
        <div className="visualization-heading">
          <div>
            <BarChart3 size={18} aria-hidden="true" />
            <div>
              <h2 id="imagery-title">唐宋意象每万字率</h2>
              <p>{payload.comparisons.length} 个实际率差较高的审核词</p>
            </div>
          </div>
          <span>× 10,000 字</span>
        </div>
        <div className="imagery-chart-stage">
          <ReactECharts
            option={option}
            onEvents={chartEvents}
            className="imagery-chart"
            style={{ height: 400, width: "100%" }}
            opts={{ renderer: "canvas" }}
          />
          <div
            className="imagery-tide-overlay"
            aria-hidden="true"
            key={`${selected.word}-${motionProfile}`}
          >
            <span className="imagery-tide-line" data-dynasty="tang" />
            <span className="imagery-tide-line" data-dynasty="song" />
            <span className="imagery-word-echo">{selected.word}</span>
          </div>
        </div>
        <div className="term-tabs" aria-label="选择意象词" role="tablist">
          {payload.comparisons.map((row, index) => {
            const isActive = row.word === selected.word;
            return (
              <button
                type="button"
                id={`imagery-term-${index}`}
                role="tab"
                aria-controls="imagery-detail-panel"
                aria-selected={isActive}
                data-active={isActive}
                tabIndex={isActive ? 0 : -1}
                onClick={() => selectWord(row.word)}
                onKeyDown={(event) => handleTermKeyDown(event, index)}
                ref={(button) => {
                  termButtonRefs.current[index] = button;
                }}
                key={row.word}
              >
                {row.word}
              </button>
            );
          })}
        </div>
      </div>

      <aside
        className="imagery-detail"
        id="imagery-detail-panel"
        role="tabpanel"
        aria-labelledby={`imagery-term-${selectedIndex}`}
        aria-live="polite"
      >
        <div className="imagery-term-heading">
          <span>{selected.category}</span>
          <h2>{selected.word}</h2>
          <small>{selected.higherIn}代每万字率更高</small>
        </div>
        <div className="rate-pair">
          <div data-dynasty="tang">
            <span>唐</span>
            <strong>
              <span aria-hidden="true">{displayedRates.tang.toFixed(2)}</span>
              <span className="sr-only">{selected.tang.ratePer10k.toFixed(2)}</span>
            </strong>
            <small>{selected.tang.rawHits} 次命中</small>
          </div>
          <div data-dynasty="song">
            <span>宋</span>
            <strong>
              <span aria-hidden="true">{displayedRates.song.toFixed(2)}</span>
              <span className="sr-only">{selected.song.ratePer10k.toFixed(2)}</span>
            </strong>
            <small>{selected.song.rawHits} 次命中</small>
          </div>
        </div>
        <p className="rate-delta">
          宋减唐 <strong>{selected.deltaSongMinusTang > 0 ? "+" : ""}{selected.deltaSongMinusTang.toFixed(2)}</strong>
        </p>
        <dl className="denominator-list">
          <div><dt>唐代分母</dt><dd>{selected.tang.chineseCharDenominator.toLocaleString()} 字</dd></div>
          <div><dt>宋代分母</dt><dd>{selected.song.chineseCharDenominator.toLocaleString()} 字</dd></div>
        </dl>
      </aside>

      <section className="imagery-evidence" aria-labelledby="imagery-evidence-title">
        <div className="section-heading">
          <div>
            <BookOpenText size={17} aria-hidden="true" />
            <h2 id="imagery-evidence-title">“{selected.word}”原句证据</h2>
          </div>
          <span>{selected.corpusEvidence.length} 条</span>
        </div>
        {selected.corpusEvidence.length > 0 ? (
          <div className="evidence-sentences" key={selected.word}>
            {evidenceGroups.map((group) => (
              <section
                className="imagery-evidence-group"
                data-dynasty={dynastyTone(group.dynasty)}
                aria-label={`${group.dynasty}证据`}
                key={group.dynasty}
              >
                <header>
                  <h3>{group.dynasty}</h3>
                  <span>{group.evidence.length} 条</span>
                </header>
                <div className="imagery-evidence-group-grid">
                  {group.evidence.map((evidence, index) => (
                    <article
                      className="imagery-evidence-card"
                      style={{
                        "--imagery-evidence-order": group.startIndex + index,
                      } as EvidenceStyle}
                      key={`${selected.word}-${evidence.dynasty}-${evidence.poet}-${evidence.title}-${index}`}
                    >
                      <span>{evidence.dynasty}</span>
                      <blockquote>{evidence.sentence}</blockquote>
                      <p>{evidence.poet} · 《{evidence.title}》</p>
                    </article>
                  ))}
                </div>
              </section>
            ))}
          </div>
        ) : <EmptyState title="原句证据 insufficient" detail="该词当前统计命中为零。" />}
      </section>
    </section>
  );
}
