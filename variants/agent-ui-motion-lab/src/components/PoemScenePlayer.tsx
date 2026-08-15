"use client";

import {
  ChevronLeft,
  ChevronRight,
  Pause,
  Play,
  RotateCcw,
  TimerReset,
} from "lucide-react";
import type { CSSProperties } from "react";
import {
  useCallback,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
} from "react";

import { EmptyState } from "@/components/StateViews";
import type { EffectiveMotionProfile } from "@/lib/motion";
import {
  initialSceneMotion,
  remainingSceneTimerMs,
  sceneContentIsHidden,
  sceneDwellElapsedMs,
  sceneMotionReducer,
  type SceneMotionDirection,
  type SceneMotionPhase,
} from "@/lib/sceneMotion";
import type { PoetryScene, ScenePayload } from "@/lib/types";
import { scenePlaybackDelayMs } from "@/lib/workbench";

interface PoemScenePlayerProps {
  payload: ScenePayload;
  onSceneChange: (scene: PoetryScene) => void;
  motionProfile?: EffectiveMotionProfile;
}

interface SceneTiming {
  coverMs: number;
  revealMs: number;
  layerMs: number;
  stepMs: number;
}

const SCENE_TIMINGS: Record<EffectiveMotionProfile, SceneTiming> = {
  off: { coverMs: 0, revealMs: 0, layerMs: 0, stepMs: 0 },
  restrained: { coverMs: 160, revealMs: 280, layerMs: 120, stepMs: 20 },
  cinematic: { coverMs: 520, revealMs: 860, layerMs: 320, stepMs: 70 },
  experimental: { coverMs: 680, revealMs: 1_040, layerMs: 400, stepMs: 85 },
};

const PHASE_LABEL: Record<SceneMotionPhase, string> = {
  settled: "逐幕停驻",
  covering: "纸幕合拢",
  swapping: "场景换幕",
  revealing: "诗篇渐显",
};

const COVER_SETTLE_BUFFER_MS = 20;

function clampSceneIndex(index: number, sceneCount: number): number {
  return Math.max(0, Math.min(Math.max(sceneCount - 1, 0), index));
}

function sceneLayerStyle(order: number, stepMs: number): CSSProperties {
  return {
    "--scene-reveal-delay": `${Math.round(order * stepMs)}ms`,
  } as CSSProperties;
}

export function PoemScenePlayer({
  payload,
  onSceneChange,
  motionProfile = "cinematic",
}: PoemScenePlayerProps) {
  const sceneCount = payload.scenes.length;
  const initialIndex = clampSceneIndex(payload.startIndex ?? 0, sceneCount);
  const [motion, dispatch] = useReducer(
    sceneMotionReducer,
    initialIndex,
    initialSceneMotion,
  );
  const [playing, setPlaying] = useState(
    () => Boolean(payload.autoplay || payload.mode === "autoplay")
      && initialIndex < sceneCount - 1,
  );
  const [pageHidden, setPageHidden] = useState(false);
  const scene = payload.scenes[motion.visibleIndex];
  const activeMotionProfile: EffectiveMotionProfile = motionProfile === "off"
    || motion.phase === "settled"
    ? motionProfile
    : motion.transitionProfile;
  const timing = SCENE_TIMINGS[activeMotionProfile];
  const dwellMs = useMemo(
    () => scenePlaybackDelayMs(scene?.read_seconds),
    [scene?.read_seconds],
  );

  const transitionTimerRef = useRef<number | null>(null);
  const transitionDeadlineRef = useRef<number | null>(null);
  const remainingTransitionMsRef = useRef<number | null>(null);
  const transitionClockKeyRef = useRef("");
  const dwellTimerRef = useRef<number | null>(null);
  const dwellDeadlineRef = useRef<number | null>(null);
  const remainingDwellMsRef = useRef(dwellMs);
  const reportedSceneIndexRef = useRef<number | null>(null);
  const playerRef = useRef<HTMLElement | null>(null);
  const transitionStatusRef = useRef<HTMLSpanElement | null>(null);
  const dwellProgressRef = useRef<SVGCircleElement | null>(null);

  const clearTransitionTimer = useCallback((preserveRemaining = false) => {
    if (transitionTimerRef.current !== null) {
      window.clearTimeout(transitionTimerRef.current);
      transitionTimerRef.current = null;
    }
    if (preserveRemaining && remainingTransitionMsRef.current !== null) {
      remainingTransitionMsRef.current = remainingSceneTimerMs(
        transitionDeadlineRef.current,
        Date.now(),
        remainingTransitionMsRef.current,
      );
    }
    transitionDeadlineRef.current = null;
  }, []);

  const clearDwellTimer = useCallback((preserveRemaining: boolean) => {
    if (dwellTimerRef.current !== null) {
      window.clearTimeout(dwellTimerRef.current);
      dwellTimerRef.current = null;
    }
    if (preserveRemaining) {
      remainingDwellMsRef.current = remainingSceneTimerMs(
        dwellDeadlineRef.current,
        Date.now(),
        remainingDwellMsRef.current,
      );
    }
    dwellDeadlineRef.current = null;
  }, []);

  const updateDwellProgress = useCallback((remainingMs: number) => {
    dwellProgressRef.current?.style.setProperty(
      "--scene-dwell-delay",
      `-${sceneDwellElapsedMs(dwellMs, remainingMs)}ms`,
    );
  }, [dwellMs]);

  const connectDwellProgress = useCallback((node: SVGCircleElement | null) => {
    dwellProgressRef.current = node;
    if (!node) return;
    const remainingMs = remainingSceneTimerMs(
      dwellDeadlineRef.current,
      Date.now(),
      remainingDwellMsRef.current,
    );
    node.style.setProperty(
      "--scene-dwell-delay",
      `-${sceneDwellElapsedMs(dwellMs, remainingMs)}ms`,
    );
  }, [dwellMs]);

  const stabilizeTransitionFocus = useCallback(() => {
    const player = playerRef.current;
    const status = transitionStatusRef.current;
    const activeElement = document.activeElement;
    if (!player || !status || !activeElement || activeElement === status) return;
    if (player.contains(activeElement)) status.focus({ preventScroll: true });
  }, []);

  useEffect(() => {
    const syncVisibility = () => {
      const hidden = document.hidden;
      if (hidden) {
        clearTransitionTimer(true);
        clearDwellTimer(true);
      }
      setPageHidden(hidden);
    };

    document.addEventListener("visibilitychange", syncVisibility);
    const initialSyncTimer = window.setTimeout(syncVisibility, 0);
    return () => {
      window.clearTimeout(initialSyncTimer);
      document.removeEventListener("visibilitychange", syncVisibility);
    };
  }, [clearDwellTimer, clearTransitionTimer]);

  useEffect(() => {
    clearDwellTimer(false);
    remainingDwellMsRef.current = dwellMs;
  }, [clearDwellTimer, dwellMs, motion.transitionId, motion.visibleIndex]);

  useEffect(() => {
    if (!scene || reportedSceneIndexRef.current === motion.visibleIndex) return;
    reportedSceneIndexRef.current = motion.visibleIndex;
    onSceneChange(scene);
  }, [motion.visibleIndex, onSceneChange, scene]);

  useEffect(() => {
    const clockKey = `${motion.transitionId}:${motion.phase}:${activeMotionProfile}`;
    if (transitionClockKeyRef.current !== clockKey) {
      clearTransitionTimer(false);
      transitionClockKeyRef.current = clockKey;
      remainingTransitionMsRef.current = activeMotionProfile === "off"
        ? 0
        : motion.phase === "covering"
          ? timing.coverMs + COVER_SETTLE_BUFFER_MS
          : motion.phase === "revealing"
            ? timing.revealMs
            : 0;
    }

    if (motion.phase === "settled") {
      remainingTransitionMsRef.current = null;
      transitionDeadlineRef.current = null;
      return;
    }
    if (pageHidden || document.hidden) return;

    const remainingMs = Math.max(0, remainingTransitionMsRef.current ?? 0);
    transitionDeadlineRef.current = Date.now() + remainingMs;
    transitionTimerRef.current = window.setTimeout(() => {
      const deadlineMs = transitionDeadlineRef.current;
      transitionTimerRef.current = null;

      if (document.hidden) {
        remainingTransitionMsRef.current = remainingSceneTimerMs(
          deadlineMs,
          Date.now(),
          remainingMs,
        );
        transitionDeadlineRef.current = null;
        setPageHidden(true);
        return;
      }

      transitionDeadlineRef.current = null;
      remainingTransitionMsRef.current = null;
      if (activeMotionProfile === "off") {
        dispatch({
          type: "jump",
          target: motion.targetIndex ?? motion.visibleIndex,
          direction: motion.direction,
        });
      } else if (motion.phase === "covering") {
        dispatch({ type: "covered" });
      } else if (motion.phase === "swapping") {
        dispatch({ type: "swapped" });
      } else {
        dispatch({ type: "revealed" });
      }
    }, remainingMs);

    return () => clearTransitionTimer(true);
  }, [
    clearTransitionTimer,
    activeMotionProfile,
    motion.direction,
    motion.phase,
    motion.targetIndex,
    motion.transitionId,
    motion.visibleIndex,
    pageHidden,
    timing.coverMs,
    timing.revealMs,
  ]);

  useEffect(() => {
    const atLastScene = motion.visibleIndex >= sceneCount - 1;
    const remainingMs = Math.max(
      0,
      Math.min(dwellMs, remainingDwellMsRef.current),
    );
    updateDwellProgress(remainingMs);
    if (
      pageHidden
      || document.hidden
      || !playing
      || !scene
      || motion.phase !== "settled"
      || atLastScene
    ) return;

    dwellDeadlineRef.current = Date.now() + remainingMs;
    dwellTimerRef.current = window.setTimeout(() => {
      dwellTimerRef.current = null;

      if (document.hidden) {
        remainingDwellMsRef.current = remainingSceneTimerMs(
          dwellDeadlineRef.current,
          Date.now(),
          remainingMs,
        );
        dwellDeadlineRef.current = null;
        setPageHidden(true);
        return;
      }

      dwellDeadlineRef.current = null;
      remainingDwellMsRef.current = 0;

      const target = clampSceneIndex(motion.visibleIndex + 1, sceneCount);
      if (target === motion.visibleIndex) {
        setPlaying(false);
        return;
      }
      if (target === sceneCount - 1) setPlaying(false);

      stabilizeTransitionFocus();
      dispatch(motionProfile === "off"
        ? { type: "jump", target, direction: 1 }
        : { type: "navigate", target, direction: 1, profile: motionProfile });
    }, remainingMs);

    return () => clearDwellTimer(true);
  }, [
    clearDwellTimer,
    dwellMs,
    motion.phase,
    motion.visibleIndex,
    motionProfile,
    pageHidden,
    playing,
    scene,
    sceneCount,
    stabilizeTransitionFocus,
    updateDwellProgress,
  ]);

  useEffect(() => () => {
    clearTransitionTimer();
    clearDwellTimer(false);
  }, [clearDwellTimer, clearTransitionTimer]);

  const navigateTo = useCallback((
    target: number,
    direction: SceneMotionDirection,
  ) => {
    if (motion.phase !== "settled" || sceneCount === 0) return;
    const boundedTarget = clampSceneIndex(target, sceneCount);
    setPlaying(false);
    stabilizeTransitionFocus();
    dispatch(motionProfile === "off"
      ? { type: "jump", target: boundedTarget, direction }
      : { type: "navigate", target: boundedTarget, direction, profile: motionProfile });
  }, [motion.phase, motionProfile, sceneCount, stabilizeTransitionFocus]);

  const togglePlayback = useCallback(() => {
    if (motion.phase !== "settled" || sceneCount <= 1) return;
    if (playing) {
      setPlaying(false);
      return;
    }

    setPlaying(true);
    if (motion.visibleIndex < sceneCount - 1) return;

    stabilizeTransitionFocus();
    dispatch(motionProfile === "off"
      ? { type: "jump", target: 0, direction: 1 }
      : { type: "navigate", target: 0, direction: 1, profile: motionProfile });
  }, [
    motion.phase,
    motion.visibleIndex,
    motionProfile,
    playing,
    sceneCount,
    stabilizeTransitionFocus,
  ]);

  if (!scene) {
    return <EmptyState title="没有可播放镜头" detail="当前诗人缺少可系年场景。" />;
  }

  const controlsLocked = motion.phase !== "settled";
  const sceneContentHidden = sceneContentIsHidden(motion.phase);
  const directionLabel = motion.direction === 1 ? "forward" : "backward";
  const statusLabel = controlsLocked
    ? PHASE_LABEL[motion.phase]
    : playing ? "连续播放" : PHASE_LABEL.settled;
  const playerStyle = {
    "--scene-cover-duration": `${timing.coverMs}ms`,
    "--scene-layer-duration": `${timing.layerMs}ms`,
    "--scene-dwell-duration": `${dwellMs}ms`,
  } as CSSProperties;

  return (
    <section
      ref={playerRef}
      className="scene-player"
      aria-label={sceneContentHidden ? "场景换幕" : undefined}
      aria-labelledby={sceneContentHidden ? undefined : "scene-title"}
      data-motion-profile={activeMotionProfile}
      data-phase={motion.phase}
      data-direction={directionLabel}
      data-page-hidden={pageHidden}
      data-playing={playing}
      style={playerStyle}
    >
      <div
        className="scene-progress"
        aria-label={`第 ${motion.visibleIndex + 1} 幕，共 ${sceneCount} 幕`}
      >
        <span style={{ width: `${((motion.visibleIndex + 1) / sceneCount) * 100}%` }} />
      </div>

      <div
        className="scene-stage"
        aria-busy={controlsLocked}
        aria-hidden={sceneContentHidden || undefined}
      >
        <div className="scene-cover scene-cover-leading" aria-hidden="true" />
        <div className="scene-cover scene-cover-trailing" aria-hidden="true" />

        <div className="scene-year-column">
          <span className="scene-layer" style={sceneLayerStyle(0, timing.stepMs)}>
            第 {String(motion.visibleIndex + 1).padStart(2, "0")} 幕
          </span>
          <strong className="scene-layer" style={sceneLayerStyle(0.5, timing.stepMs)}>
            {scene.year_label}
          </strong>
          <small className="scene-layer" style={sceneLayerStyle(1, timing.stepMs)}>
            {scene.year_precision_display}
          </small>
          <div className="scene-location scene-layer" style={sceneLayerStyle(1.5, timing.stepMs)}>
            <b>{scene.place_historical || "地点未定"}</b>
            <span>{scene.place_modern || "现代地名未记录"}</span>
            <i className="scene-location-stamp" aria-hidden="true">
              {scene.place_historical || "未定"}
            </i>
          </div>
        </div>

        <article className="scene-poem">
          <p className="scene-poet scene-layer" style={sceneLayerStyle(1, timing.stepMs)}>
            {scene.dynasty} · {scene.poet}
          </p>
          <h2 id="scene-title" className="scene-layer" style={sceneLayerStyle(2, timing.stepMs)}>
            《{scene.poem_title}》
          </h2>
          <blockquote
            className="poem-lines"
            tabIndex={controlsLocked ? -1 : 0}
            aria-label={`${scene.poem_title}完整诗文`}
          >
            {scene.poem_lines.map((line, lineIndex) => (
              <p
                className="scene-layer"
                key={`${scene.id}-${motion.transitionId}-${lineIndex}`}
                style={sceneLayerStyle(3 + Math.min(lineIndex, 3) * 0.65, timing.stepMs)}
              >
                {line}
              </p>
            ))}
          </blockquote>
          <p className="scene-event scene-layer" style={sceneLayerStyle(6, timing.stepMs)}>
            {scene.event}
          </p>
        </article>

        <aside className="scene-tone">
          <span className="scene-layer" style={sceneLayerStyle(6.5, timing.stepMs)}>
            情绪标注
          </span>
          <strong className="scene-layer" style={sceneLayerStyle(7, timing.stepMs)}>
            {scene.emotion_label || "未标注"}
          </strong>
          <p className="scene-layer" style={sceneLayerStyle(7.5, timing.stepMs)}>
            {scene.emotion_evidence || "emotion evidence insufficient"}
          </p>
          <div className="scene-dwell-meta scene-layer" style={sceneLayerStyle(7.5, timing.stepMs)}>
            <svg
              className="scene-dwell-ring"
              key={`${scene.id}-${motion.transitionId}-${activeMotionProfile}`}
              viewBox="0 0 20 20"
              focusable="false"
              aria-hidden="true"
            >
              <circle className="scene-dwell-track" cx="10" cy="10" r="7" pathLength="1" />
              <circle
                ref={connectDwellProgress}
                className="scene-dwell-progress"
                cx="10"
                cy="10"
                r="7"
                pathLength="1"
              />
            </svg>
            <TimerReset size={14} aria-hidden="true" />
            建议停驻 {scene.read_seconds} 秒
          </div>
        </aside>
      </div>

      <div className="player-controls">
        <button
          type="button"
          className="icon-button"
          onClick={() => navigateTo(0, motion.visibleIndex === 0 ? 1 : -1)}
          disabled={controlsLocked}
          aria-label="重播"
          title="重播"
        >
          <RotateCcw size={18} aria-hidden="true" />
        </button>
        <button
          type="button"
          className="icon-button"
          onClick={() => navigateTo(motion.visibleIndex - 1, -1)}
          disabled={controlsLocked || motion.visibleIndex === 0}
          aria-label="上一幕"
          title="上一幕"
        >
          <ChevronLeft size={20} aria-hidden="true" />
        </button>
        <button
          type="button"
          className="galaxy-play-button"
          onClick={togglePlayback}
          disabled={controlsLocked || sceneCount <= 1}
          aria-label={playing ? "暂停" : "播放"}
          title={playing ? "暂停" : "播放"}
        >
          {playing
            ? <Pause size={20} fill="currentColor" aria-hidden="true" />
            : <Play size={20} fill="currentColor" aria-hidden="true" />}
        </button>
        <button
          type="button"
          className="icon-button"
          onClick={() => navigateTo(motion.visibleIndex + 1, 1)}
          disabled={controlsLocked || motion.visibleIndex === sceneCount - 1}
          aria-label="下一幕"
          title="下一幕"
        >
          <ChevronRight size={20} aria-hidden="true" />
        </button>
        <span ref={transitionStatusRef} tabIndex={-1} aria-live="polite">
          {statusLabel} · {motion.visibleIndex + 1}/{sceneCount}
        </span>
      </div>
    </section>
  );
}
