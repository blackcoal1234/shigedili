"use client";

import {
  ChevronLeft,
  ChevronRight,
  Pause,
  Play,
  RotateCcw,
  TimerReset,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { EmptyState } from "@/components/StateViews";
import { InteractivePoemText } from "@/components/InteractivePoemText";
import { PoemKnowledgeSummary } from "@/components/KnowledgeExplorer";
import type { AppreciationTarget } from "@/components/PoemAppreciationDrawer";
import type { PoetryScene, ScenePayload } from "@/lib/types";
import { scenePlaybackDelayMs } from "@/lib/workbench";

interface PoemScenePlayerProps {
  payload: ScenePayload;
  onSceneChange: (scene: PoetryScene) => void;
  onOpenKnowledge?: (poemId: string) => void;
  onOpenAppreciation?: (target: AppreciationTarget) => void;
}

export function PoemScenePlayer({
  payload,
  onSceneChange,
  onOpenKnowledge,
  onOpenAppreciation,
}: PoemScenePlayerProps) {
  const initialIndex = Math.min(payload.startIndex ?? 0, Math.max(payload.scenes.length - 1, 0));
  const [index, setIndex] = useState(initialIndex);
  const [playing, setPlaying] = useState(false);
  const scene = payload.scenes[index];

  useEffect(() => {
    if (scene) onSceneChange(scene);
  }, [onSceneChange, scene]);

  const delay = useMemo(
    () => scenePlaybackDelayMs(scene?.read_seconds),
    [scene?.read_seconds],
  );

  useEffect(() => {
    if (!playing || !scene) return;
    if (index >= payload.scenes.length - 1) return;
    const timer = window.setTimeout(() => {
      setIndex((current) => {
        const next = Math.min(payload.scenes.length - 1, current + 1);
        if (next === payload.scenes.length - 1) setPlaying(false);
        return next;
      });
    }, delay);
    return () => window.clearTimeout(timer);
  }, [delay, index, payload.scenes.length, playing, scene]);

  if (!scene) {
    return <EmptyState title="还没有可放映的画面" detail="这位诗人的场景尚未系年，资料补齐后会自动上新。" />;
  }

  const previous = () => {
    setPlaying(false);
    setIndex((current) => Math.max(0, current - 1));
  };
  const next = () => {
    setPlaying(false);
    setIndex((current) => Math.min(payload.scenes.length - 1, current + 1));
  };
  const restart = () => {
    setPlaying(false);
    setIndex(0);
  };

  return (
    <section className="scene-player" aria-labelledby="scene-title">
      <div className="scene-progress" aria-label={`第 ${index + 1} 幕，共 ${payload.sceneCount} 幕`}>
        <span style={{ width: `${((index + 1) / payload.sceneCount) * 100}%` }} />
      </div>
      <div className="scene-stage">
        <div className="scene-year-column">
          <span>第 {String(index + 1).padStart(2, "0")} 幕</span>
          <strong>{scene.year_label}</strong>
          <small>{scene.year_precision_display}</small>
          <div className="scene-location">
            <b>{scene.place_historical || "地点未定"}</b>
            <span>{scene.place_modern || "现代地名未记录"}</span>
          </div>
        </div>

        <article className="scene-poem">
          <p className="scene-poet">{scene.dynasty} · {scene.poet}</p>
          <h2 id="scene-title">《{scene.poem_title}》</h2>
          <blockquote className="poem-lines" tabIndex={0} aria-label={`${scene.poem_title}完整诗文`}>
            <InteractivePoemText
              lines={scene.poem_lines}
              poemId={scene.source_poem_id}
              ariaLabel={`${scene.poem_title}完整诗文`}
            />
          </blockquote>
          <p className="scene-event">{scene.event}</p>
          <PoemKnowledgeSummary
            poemId={scene.source_poem_id}
            onOpenKnowledge={onOpenKnowledge}
            onOpenAppreciation={onOpenAppreciation ? () => {
              setPlaying(false);
              onOpenAppreciation({
                poemId: scene.source_poem_id,
                title: scene.poem_title,
                poet: scene.poet,
                dynasty: scene.dynasty,
              });
            } : undefined}
          />
        </article>

        <aside className="scene-tone">
          <span>情绪标注</span>
          <strong>{scene.emotion_label || "未标注"}</strong>
          <p>{scene.emotion_evidence || "emotion evidence insufficient"}</p>
          <div>
            <TimerReset size={14} aria-hidden="true" />
            建议停驻 {scene.read_seconds} 秒
          </div>
        </aside>
      </div>

      <div className="player-controls">
        <button
          type="button"
          className="icon-button"
          onClick={restart}
          aria-label="重播"
          title="重播"
        >
          <RotateCcw size={18} aria-hidden="true" />
        </button>
        <button
          type="button"
          className="icon-button"
          onClick={previous}
          disabled={index === 0}
          aria-label="上一幕"
          title="上一幕"
        >
          <ChevronLeft size={20} aria-hidden="true" />
        </button>
        <button
          type="button"
          className="galaxy-play-button"
          onClick={() => {
            if (index === payload.scenes.length - 1) setIndex(0);
            setPlaying((current) => !current);
          }}
          aria-label={playing ? "暂停" : "播放"}
          title={playing ? "暂停" : "播放"}
        >
          {playing ? <Pause size={20} fill="currentColor" aria-hidden="true" /> : <Play size={20} fill="currentColor" aria-hidden="true" />}
        </button>
        <button
          type="button"
          className="icon-button"
          onClick={next}
          disabled={index === payload.scenes.length - 1}
          aria-label="下一幕"
          title="下一幕"
        >
          <ChevronRight size={20} aria-hidden="true" />
        </button>
        <span>{playing ? "连续播放" : "逐幕停驻"} · {index + 1}/{payload.sceneCount}</span>
      </div>
    </section>
  );
}
