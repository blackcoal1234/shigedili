"use client";

import type { EChartsOption } from "echarts";
import ReactECharts from "echarts-for-react";
import { BarChart3, BookOpenText } from "lucide-react";
import { useMemo, useState } from "react";

import { EmptyState } from "@/components/StateViews";
import type { ImageryPayload } from "@/lib/types";

export function ImageryComparison({
  payload,
  onOpenKnowledge,
}: {
  payload: ImageryPayload;
  onOpenKnowledge?: (poemId: string) => void;
}) {
  const [selectedWord, setSelectedWord] = useState(payload.comparisons[0]?.word ?? "");
  const selected = payload.comparisons.find((row) => row.word === selectedWord)
    ?? payload.comparisons[0];

  const option = useMemo<EChartsOption>(() => ({
    animationDuration: 480,
    aria: { enabled: true, decal: { show: false } },
    color: ["#344f43", "#a33a2b"],
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
        name: "唐",
        type: "bar",
        barMaxWidth: 22,
        itemStyle: { borderRadius: [2, 2, 0, 0] },
        data: payload.comparisons.map((row) => row.tang.ratePer10k),
      },
      {
        name: "宋",
        type: "bar",
        barMaxWidth: 22,
        itemStyle: { borderRadius: [2, 2, 0, 0] },
        data: payload.comparisons.map((row) => row.song.ratePer10k),
      },
    ],
  }), [payload.comparisons]);

  const chartEvents = useMemo(() => ({
    click: (params: { name?: string }) => {
      if (params.name) setSelectedWord(params.name);
    },
  }), []);

  if (!selected) {
    return <EmptyState title="这位诗人暂无比对数据" detail="词表里还没有他可比较的意象记录，换一位诗人试试。" />;
  }

  return (
    <section className="imagery-layout" aria-labelledby="imagery-title">
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
        <ReactECharts
          option={option}
          onEvents={chartEvents}
          className="imagery-chart"
          style={{ height: 400, width: "100%" }}
          opts={{ renderer: "canvas" }}
        />
        <div className="term-tabs" aria-label="选择意象词">
          {payload.comparisons.map((row) => (
            <button
              type="button"
              data-active={row.word === selected.word}
              onClick={() => setSelectedWord(row.word)}
              key={row.word}
            >
              {row.word}
            </button>
          ))}
        </div>
      </div>

      <aside className="imagery-detail">
        <div className="imagery-term-heading">
          <span>{selected.category}</span>
          <h2>{selected.word}</h2>
          <small>{selected.higherIn}代每万字率更高</small>
        </div>
        <div className="rate-pair">
          <div data-dynasty="tang">
            <span>唐</span>
            <strong>{selected.tang.ratePer10k.toFixed(2)}</strong>
            <small>{selected.tang.rawHits} 次命中</small>
          </div>
          <div data-dynasty="song">
            <span>宋</span>
            <strong>{selected.song.ratePer10k.toFixed(2)}</strong>
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
          <div className="evidence-sentences">
            {selected.corpusEvidence.map((evidence, index) => (
              <article key={`${evidence.dynasty}-${evidence.poet}-${evidence.title}-${index}`}>
                <span>{evidence.dynasty}</span>
                <blockquote>{evidence.sentence}</blockquote>
                <p>{evidence.poet} · 《{evidence.title}》</p>
                {evidence.sourcePoemId && onOpenKnowledge ? (
                  <button
                    type="button"
                    className="inline-knowledge-link"
                    onClick={() => onOpenKnowledge(evidence.sourcePoemId as string)}
                  >
                    查看逐句分析
                  </button>
                ) : null}
              </article>
            ))}
          </div>
        ) : <EmptyState title="原句证据 insufficient" detail="该词当前统计命中为零。" />}
      </section>
    </section>
  );
}
