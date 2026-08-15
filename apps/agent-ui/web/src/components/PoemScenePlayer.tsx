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

import type { PoetryScene, ScenePayload } from "@/lib/types";
import { scenePlaybackDelayMs } from "@/lib/workbench";
import { EmptyState } from "@/components/StateViews";

interface PoemScenePlayerProps {
  payload: ScenePayload;
  onSceneChange: (scene: PoetryScene) => void;
  onOpenKnowledge?: (poemId: string) => void;
}

export function PoemScenePlayer({ payload, onSceneChange, onOpenKnowledge }: PoemScenePlayerProps) {
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
    return <EmptyState title="没有可播放镜头" detail="当前诗人缺少可系年场景。" />;
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
            {scene.poem_lines.map((line, lineIndex) => (
              <p key={`${scene.id}-${lineIndex}`}>{line}</p>
            ))}
          </blockquote>
          <p className="scene-event">{scene.event}</p>
          {scene.source_poem_id && onOpenKnowledge ? (
            <button
              type="button"
              className="inline-knowledge-link"
              onClick={() => onOpenKnowledge(scene.source_poem_id)}
            >
              查看逐句分析
            </button>
          ) : null}
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
