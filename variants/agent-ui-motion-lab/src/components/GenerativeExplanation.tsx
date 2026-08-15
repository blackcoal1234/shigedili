import { Sparkles } from "lucide-react";
import { useMemo } from "react";

import { createExplanationModel } from "@/lib/explanation";
import type { WorkbenchMode, WorkbenchPayload } from "@/lib/types";

export function GenerativeExplanation({
  mode,
  payload,
}: {
  mode: WorkbenchMode;
  payload: WorkbenchPayload;
}) {
  const model = useMemo(() => createExplanationModel(mode, payload), [mode, payload]);
  const pointCount = Math.max(model.points.length, 1);

  return (
    <section className="generative-panel" aria-labelledby="generative-title">
      <div className="section-heading">
        <div>
          <Sparkles size={17} aria-hidden="true" />
          <h2 id="generative-title">临时解释图</h2>
        </div>
        <span>payload only · SVG</span>
      </div>
      <svg
        className="explanation-svg"
        viewBox="0 0 760 230"
        role="img"
        aria-label={`${model.title}，${model.metricLabel}${model.metric}`}
      >
        <title>{model.title}</title>
        <rect x="1" y="1" width="758" height="228" rx="3" className="svg-paper" />
        <text x="34" y="44" className="svg-kicker">OPEN GENERATIVE UI · CURRENT PAYLOAD</text>
        <text x="34" y="80" className="svg-title">{model.title}</text>
        <text x="34" y="143" className="svg-metric">{model.metric}</text>
        <text x="36" y="169" className="svg-label">{model.metricLabel}</text>
        <text x="36" y="198" className="svg-note">{model.notes[0]}</text>
        <text x="36" y="216" className="svg-note">{model.notes[1]}</text>
        <line x1="260" y1="172" x2="720" y2="172" className="svg-axis" />
        {model.points.map((point, index) => {
          const x = 280 + (index * 420) / Math.max(pointCount - 1, 1);
          const y = 154 - point.value * 76;
          return (
            <g key={`${point.label}-${index}`}>
              {index > 0 ? (
                <line
                  x1={280 + ((index - 1) * 420) / Math.max(pointCount - 1, 1)}
                  y1={154 - (model.points[index - 1]?.value ?? 0) * 76}
                  x2={x}
                  y2={y}
                  className="svg-route"
                />
              ) : null}
              <circle cx={x} cy={y} r="6" className="svg-point" />
              <text x={x} y="198" textAnchor="middle" className="svg-point-label">{point.label}</text>
            </g>
          );
        })}
      </svg>
      <p className="generative-boundary">由当前已返回 payload 临时派生；原数据、排序与证据保持不变。</p>
    </section>
  );
}
