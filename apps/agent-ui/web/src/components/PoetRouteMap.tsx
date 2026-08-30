"use client";

import * as echarts from "echarts";
import type { EChartsOption, EChartsType } from "echarts";
import ReactECharts from "echarts-for-react";
import {
  BookOpen,
  ChevronLeft,
  ChevronRight,
  CircleHelp,
  MapPin,
  Navigation,
  Pause,
  Play,
  RotateCcw,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { EmptyState } from "@/components/StateViews";
import { InteractivePoemText } from "@/components/InteractivePoemText";
import { PoemKnowledgeSummary } from "@/components/KnowledgeExplorer";
import type { AppreciationTarget } from "@/components/PoemAppreciationDrawer";
import { TransportGlyph } from "@/components/TransportGlyph";
import {
  clampSceneIndex,
  easeInOutCubic,
  interpolateJourneyPath,
  resolveJourneyLeg,
  revealDelayMs,
  sampleJourneyPath,
  type JourneyLeg,
  type JourneyPhase,
} from "@/lib/journey";
import type {
  PoetryScene,
  RoutePayload,
} from "@/lib/types";

interface PoetRouteMapProps {
  payload: RoutePayload;
  selectedSceneId?: string;
  onSelectScene: (scene: PoetryScene) => void;
  onOpenKnowledge?: (poemId: string) => void;
  onOpenAppreciation?: (target: AppreciationTarget) => void;
}

interface MapPoint {
  sceneId: string;
  sceneIndex: number;
  scene: PoetryScene;
  value: [number, number];
}

const MAP_NAME = "poetry-china";
const MAP_ASSET = "/assets/china-city-prefecture.geojson";
const PHASE_LABEL: Record<JourneyPhase, string> = {
  idle: "准备启程",
  travelling: "正在行旅",
  arrived: "抵达",
  revealing: "诗篇渐显",
  waiting: "驻留赏读",
};

let mapLoadPromise: Promise<void> | null = null;

function loadChinaMap(): Promise<void> {
  if (echarts.getMap(MAP_NAME)) return Promise.resolve();
  if (!mapLoadPromise) {
    mapLoadPromise = fetch(MAP_ASSET)
      .then((response) => {
        if (!response.ok) throw new Error(`地图资源读取失败（${response.status}）`);
        return response.json();
      })
      .then((geoJson) => {
        echarts.registerMap(
          MAP_NAME,
          geoJson as Parameters<typeof echarts.registerMap>[1],
        );
      })
      .catch((error) => {
        mapLoadPromise = null;
        throw error;
      });
  }
  return mapLoadPromise;
}

function fullPoemText(scene: PoetryScene): string {
  const text = scene.poem_lines.join("。\n");
  return text && !/[。！？]$/u.test(text) ? `${text}。` : text;
}

function travelDuration(segment: JourneyLeg): number {
  const [[startLon, startLat], [endLon, endLat]] = segment.coords;
  const distance = Math.hypot(endLon - startLon, endLat - startLat);
  return Math.round(Math.max(3200, Math.min(5500, 3000 + distance * 88)));
}

export function PoetRouteMap({
  payload,
  selectedSceneId,
  onSelectScene,
  onOpenKnowledge,
  onOpenAppreciation,
}: PoetRouteMapProps) {
  const mappedScenes = useMemo(
    () => payload.scenes.filter(
      (scene) => scene.map_eligible && typeof scene.lon === "number" && typeof scene.lat === "number",
    ),
    [payload.scenes],
  );
  const initialIndex = useMemo(() => {
    const selected = payload.scenes.findIndex((scene) => scene.id === selectedSceneId);
    if (selected >= 0) return selected;
    const firstMapped = payload.scenes.findIndex((scene) => scene.map_eligible);
    return firstMapped >= 0 ? firstMapped : 0;
  }, [payload.scenes, selectedSceneId]);

  const [mapReady, setMapReady] = useState(Boolean(echarts.getMap(MAP_NAME)));
  const [mapError, setMapError] = useState("");
  const [sceneIndex, setSceneIndex] = useState(initialIndex);
  const [pendingIndex, setPendingIndex] = useState<number | null>(null);
  const [phase, setPhase] = useState<JourneyPhase>("arrived");
  const [paused, setPaused] = useState(false);
  const [revealCount, setRevealCount] = useState(0);
  const [activeLeg, setActiveLeg] = useState<JourneyLeg>();
  const [lastLeg, setLastLeg] = useState<JourneyLeg>();
  const [travelProgress, setTravelProgress] = useState(0);
  const [boatPixel, setBoatPixel] = useState<[number, number] | null>(null);
  const [transitionNotice, setTransitionNotice] = useState("");
  const [reducedMotion, setReducedMotion] = useState(false);
  const chartRef = useRef<EChartsType | null>(null);
  const boatCoordRef = useRef<[number, number] | null>(null);
  const travelProgressRef = useRef(0);
  const animationFrameRef = useRef<number | null>(null);
  const travelRunRef = useRef(0);

  const scene = payload.scenes[sceneIndex];
  const poemText = scene ? fullPoemText(scene) : "";
  const poemVisible = phase === "arrived" || phase === "revealing" || phase === "waiting";
  const controlsLocked = phase === "travelling" || phase === "revealing";
  const transport = activeLeg ?? lastLeg;
  const activePath = useMemo(
    () => activeLeg ? sampleJourneyPath(activeLeg) : [],
    [activeLeg],
  );

  const syncBoatPixel = useCallback((coordinate?: [number, number] | null) => {
    const chart = chartRef.current;
    const current = coordinate ?? boatCoordRef.current;
    if (!chart || !current) {
      setBoatPixel(null);
      return;
    }
    const pixel = chart.convertToPixel({ geoIndex: 0 }, current);
    if (
      Array.isArray(pixel)
      && typeof pixel[0] === "number"
      && typeof pixel[1] === "number"
      && Number.isFinite(pixel[0])
      && Number.isFinite(pixel[1])
    ) {
      setBoatPixel([pixel[0], pixel[1]]);
    }
  }, []);

  const positionAtScene = useCallback((target: PoetryScene) => {
    if (typeof target.lon !== "number" || typeof target.lat !== "number") {
      boatCoordRef.current = null;
      setBoatPixel(null);
      return;
    }
    const coordinate: [number, number] = [target.lon, target.lat];
    boatCoordRef.current = coordinate;
    syncBoatPixel(coordinate);
  }, [syncBoatPixel]);

  const arriveAt = useCallback((targetIndex: number, leg?: JourneyLeg) => {
    const nextIndex = clampSceneIndex(targetIndex, payload.scenes.length);
    const target = payload.scenes[nextIndex];
    if (!target) return;
    setSceneIndex(nextIndex);
    setPendingIndex(null);
    setTravelProgress(1);
    travelProgressRef.current = 1;
    setActiveLeg(undefined);
    if (leg) setLastLeg(leg);
    setRevealCount(reducedMotion ? fullPoemText(target).length : 0);
    setPaused(false);
    setPhase(reducedMotion ? "waiting" : "arrived");
    positionAtScene(target);
    onSelectScene(target);
  }, [onSelectScene, payload.scenes, positionAtScene, reducedMotion]);

  const goToScene = useCallback((targetIndex: number) => {
    const nextIndex = clampSceneIndex(targetIndex, payload.scenes.length);
    if (nextIndex === sceneIndex || controlsLocked) return;
    const current = payload.scenes[sceneIndex];
    const target = payload.scenes[nextIndex];
    if (!current || !target) return;

    const leg = resolveJourneyLeg(
      payload.routeSegments,
      payload.visualTransitions ?? [],
      current,
      target,
    );
    setTransitionNotice("");
    setRevealCount(0);
    setPaused(false);

    if (!leg || reducedMotion) {
      if (!leg) {
        const coordinateMissing = !current.map_eligible || !target.map_eligible
          || typeof current.lon !== "number" || typeof current.lat !== "number"
          || typeof target.lon !== "number" || typeof target.lat !== "number";
        setTransitionNotice(
          coordinateMissing
            ? "地点坐标未定，已切换到目标诗篇。"
            : "这两幕之间还没有转场资料，已直接切到目标诗篇。",
        );
      }
      arriveAt(nextIndex, leg);
      return;
    }

    setActiveLeg(leg);
    setPendingIndex(nextIndex);
    setTravelProgress(0);
    travelProgressRef.current = 0;
    boatCoordRef.current = leg.coords[0];
    syncBoatPixel(leg.coords[0]);
    setPhase("travelling");
  }, [arriveAt, controlsLocked, payload.routeSegments, payload.scenes, payload.visualTransitions, reducedMotion, sceneIndex, syncBoatPixel]);

  useEffect(() => {
    let cancelled = false;
    loadChinaMap()
      .then(() => {
        if (!cancelled) {
          setMapReady(true);
          setMapError("");
        }
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setMapError(error instanceof Error ? error.message : "地图资源读取失败");
        }
      });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReducedMotion(query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);

  useEffect(() => {
    if (phase !== "arrived") return;
    const timer = window.setTimeout(() => setPhase("revealing"), 460);
    return () => window.clearTimeout(timer);
  }, [phase, sceneIndex]);

  useEffect(() => {
    if (phase !== "revealing" || paused || !scene) return;
    if (revealCount >= poemText.length) {
      const completionTimer = window.setTimeout(() => setPhase("waiting"), 0);
      return () => window.clearTimeout(completionTimer);
    }
    const nextCharacter = poemText[revealCount] ?? "";
    const timer = window.setTimeout(
      () => setRevealCount((current) => Math.min(poemText.length, current + 1)),
      reducedMotion ? 0 : revealDelayMs(nextCharacter),
    );
    return () => window.clearTimeout(timer);
  }, [paused, phase, poemText, reducedMotion, revealCount, scene]);

  useEffect(() => {
    if (phase !== "travelling" || paused || !activeLeg || activePath.length === 0 || pendingIndex === null) return;
    const runId = travelRunRef.current + 1;
    travelRunRef.current = runId;
    const startProgress = travelProgressRef.current;
    const duration = travelDuration(activeLeg);
    const startedAt = performance.now();

    const tick = (now: number) => {
      if (travelRunRef.current !== runId) return;
      const elapsedProgress = (now - startedAt) / duration;
      const progress = Math.min(1, startProgress + elapsedProgress);
      travelProgressRef.current = progress;
      setTravelProgress(progress);
      const coordinate = interpolateJourneyPath(activePath, easeInOutCubic(progress));
      boatCoordRef.current = coordinate;
      syncBoatPixel(coordinate);
      if (progress >= 1) {
        animationFrameRef.current = null;
        arriveAt(pendingIndex, activeLeg);
        return;
      }
      animationFrameRef.current = window.requestAnimationFrame(tick);
    };

    animationFrameRef.current = window.requestAnimationFrame(tick);
    return () => {
      if (travelRunRef.current === runId) travelRunRef.current += 1;
      if (animationFrameRef.current !== null) {
        window.cancelAnimationFrame(animationFrameRef.current);
        animationFrameRef.current = null;
      }
    };
  }, [activeLeg, activePath, arriveAt, paused, pendingIndex, phase, syncBoatPixel]);

  useEffect(() => {
    if (!mapReady || phase === "travelling" || !scene) return;
    const timer = window.setTimeout(() => positionAtScene(scene), 40);
    return () => window.clearTimeout(timer);
  }, [mapReady, phase, positionAtScene, scene]);

  const option = useMemo<EChartsOption>(() => {
    const sceneOrder = new Map(payload.scenes.map((item, index) => [item.id, index]));
    const longitudeRange = mappedScenes.map((item) => item.lon as number);
    const latitudeRange = mappedScenes.map((item) => item.lat as number);
    const center: [number, number] = longitudeRange.length
      ? [
          (Math.min(...longitudeRange) + Math.max(...longitudeRange)) / 2,
          (Math.min(...latitudeRange) + Math.max(...latitudeRange)) / 2,
        ]
      : [105, 34];
    const span = longitudeRange.length
      ? Math.max(
          Math.max(...longitudeRange) - Math.min(...longitudeRange),
          (Math.max(...latitudeRange) - Math.min(...latitudeRange)) * 1.3,
        )
      : 20;
    const zoom = span > 22 ? 1.12 : span > 13 ? 1.4 : span > 7 ? 1.72 : 2.15;
    const isComplete = (segment: { from_id: string; to_id: string }) => {
      const from = sceneOrder.get(segment.from_id) ?? Number.MAX_SAFE_INTEGER;
      const to = sceneOrder.get(segment.to_id) ?? Number.MAX_SAFE_INTEGER;
      return Math.max(from, to) <= sceneIndex;
    };
    const historicalGuides = payload.routeSegments.map((segment) => ({
      coords: sampleJourneyPath(segment),
    }));
    const visualGuides = (payload.visualTransitions ?? []).map((segment) => ({
      coords: sampleJourneyPath(segment),
    }));
    const completedGuides = [
      ...payload.routeSegments.filter(isComplete),
      ...(payload.visualTransitions ?? []).filter(isComplete),
    ].map((segment) => ({ coords: sampleJourneyPath(segment) }));
    const activeRoute = activePath.length > 1 ? [{ coords: activePath }] : [];
    const points: MapPoint[] = mappedScenes.map((item) => ({
      sceneId: item.id,
      sceneIndex: sceneOrder.get(item.id) ?? 0,
      scene: item,
      value: [item.lon as number, item.lat as number],
    }));

    return {
      animationDuration: 520,
      animationDurationUpdate: 420,
      aria: {
        enabled: true,
        decal: { show: false },
        label: {
          description: `${payload.poet}行旅图，共${payload.sceneCount}幕、${payload.routeSegments.length}条史料路线、${payload.visualTransitions?.length ?? 0}条路径未载的镜头转场。交通方式只取来源文字。`,
        },
      },
      tooltip: {
        trigger: "item",
        confine: true,
        backgroundColor: "rgba(13,19,30,.96)",
        borderColor: "rgba(217,168,78,.45)",
        padding: [9, 11],
        textStyle: { color: "#e9e6da", fontFamily: "Microsoft YaHei", fontSize: 12 },
        extraCssText: "backdrop-filter:blur(8px);box-shadow:0 10px 26px rgba(4,7,13,.5);",
        formatter: (params: unknown) => {
          const point = (params as { data?: MapPoint }).data;
          if (!point?.scene) return "史料路线或路径未载的镜头转场";
          const item = point.scene;
          return `${item.year_label} · ${item.place_historical}<br/>《${item.poem_title}》<br/>${item.source_status} ${item.source_grade}级`;
        },
      },
      geo: {
        map: MAP_NAME,
        roam: true,
        center,
        zoom,
        scaleLimit: { min: 0.85, max: 6 },
        itemStyle: {
          areaColor: "#162033",
          borderColor: "#2e4064",
          borderWidth: 0.75,
        },
        emphasis: { itemStyle: { areaColor: "#1d2b47" }, label: { show: false } },
        select: { disabled: true },
        label: { show: false },
      },
      series: [
        {
          id: "route-historical-guides",
          type: "lines",
          coordinateSystem: "geo",
          silent: true,
          polyline: true,
          z: 2,
          lineStyle: { color: "#5b86ad", width: 2.4, type: "solid", opacity: 0.8 },
          data: historicalGuides,
        },
        {
          id: "route-visual-guides",
          type: "lines",
          coordinateSystem: "geo",
          silent: true,
          polyline: true,
          z: 2,
          lineStyle: { color: "#8a7346", width: 1.7, type: "dashed", opacity: 0.66 },
          data: visualGuides,
        },
        {
          id: "route-complete",
          type: "lines",
          coordinateSystem: "geo",
          silent: true,
          polyline: true,
          z: 3,
          lineStyle: { color: payload.color ?? "#b98f45", width: 3, opacity: 0.88 },
          data: completedGuides,
        },
        {
          id: "route-active-halo",
          type: "lines",
          coordinateSystem: "geo",
          silent: true,
          polyline: true,
          z: 4,
          lineStyle: { color: "rgba(239,203,125,.28)", width: 9, opacity: 0.9 },
          data: activeRoute,
        },
        {
          id: "route-active-main",
          type: "lines",
          coordinateSystem: "geo",
          silent: true,
          polyline: true,
          z: 5,
          lineStyle: { color: "#efcb7d", width: 5, opacity: 0.98 },
          data: activeRoute,
        },
        {
          id: "route-scenes",
          name: "编年诗篇",
          type: "scatter",
          coordinateSystem: "geo",
          z: 6,
          label: {
            show: true,
            position: "right",
            distance: 8,
            color: "#c9c2ad",
            fontFamily: "Microsoft YaHei",
            fontSize: 10,
            textShadowColor: "rgba(5,8,14,.9)",
            textShadowBlur: 4,
            formatter: (params: unknown) => {
              const point = (params as { data?: MapPoint }).data;
              return point?.sceneIndex === sceneIndex
                ? `${point.scene.place_historical} · ${point.scene.year_label}`
                : "";
            },
          },
          emphasis: { scale: 1.16, label: { show: true } },
          data: points.map((point) => ({
            ...point,
            symbolSize: point.sceneIndex === sceneIndex ? 16 : point.sceneIndex < sceneIndex ? 9 : 7,
            itemStyle: {
              color: point.sceneIndex === sceneIndex
                ? "#efcb7d"
                : point.sceneIndex < sceneIndex
                  ? payload.color ?? "#b98f45"
                  : "#131b2a",
              borderColor: point.sceneIndex === sceneIndex ? "#0a0e16" : payload.color ?? "#b98f45",
              borderWidth: 2,
              shadowBlur: point.sceneIndex === sceneIndex ? 14 : 0,
              shadowColor: "rgba(239,203,125,.4)",
            },
          })),
        },
      ],
    };
  }, [activePath, mappedScenes, payload, sceneIndex]);

  const chartEvents = useMemo(() => ({
    click: (params: unknown) => {
      const point = (params as { data?: MapPoint }).data;
      if (typeof point?.sceneIndex === "number") goToScene(point.sceneIndex);
    },
    georoam: () => syncBoatPixel(),
    finished: () => syncBoatPixel(),
  }), [goToScene, syncBoatPixel]);

  if (!scene || mappedScenes.length === 0) {
    return <EmptyState title="这个地点还定不了位" detail="镜头先留在证据列表里，坐标补上后会自动落图。" />;
  }

  if (mapError) {
    return (
      <section className="journey-map-error">
        <CircleHelp size={24} aria-hidden="true" />
        <div><strong>本地地图没有载入</strong><p>{mapError}</p></div>
        <button type="button" className="text-button" onClick={() => window.location.reload()}>重新载入</button>
      </section>
    );
  }

  return (
    <section
      className="journey-player"
      data-phase={phase}
      aria-labelledby="journey-title"
      tabIndex={0}
      onKeyDown={(event) => {
        if ((event.target as HTMLElement).closest("button, a, input, select, textarea, summary")) return;
        if (event.key === "ArrowRight") goToScene(sceneIndex + 1);
        if (event.key === "ArrowLeft") goToScene(sceneIndex - 1);
        if (event.key === " " && controlsLocked) {
          event.preventDefault();
          setPaused((current) => !current);
        }
      }}
    >
      <div className="journey-heading">
        <div>
          <span className="journey-kicker">史料自动成片 · {payload.dynasty}</span>
          <h2 id="journey-title">{payload.poet}的诗路，抵达一处才展开一篇</h2>
        </div>
        <div className="journey-heading-meta">
          <strong>{String(sceneIndex + 1).padStart(2, "0")}</strong>
          <span>/ {payload.sceneCount} 幕</span>
          <i style={{ width: `${((sceneIndex + 1) / payload.sceneCount) * 100}%` }} />
        </div>
      </div>

      <div className="journey-stage" aria-busy={!mapReady || phase === "travelling"}>
        {!mapReady ? (
          <div className="journey-map-loading">
            <Navigation className="spin-slow" size={24} aria-hidden="true" />
            <span>正在展开本地山河图</span>
          </div>
        ) : (
          <ReactECharts
            option={option}
            onEvents={chartEvents}
            onChartReady={(chart: EChartsType) => {
              chartRef.current = chart;
              window.setTimeout(() => syncBoatPixel(), 0);
            }}
            className="journey-map-chart"
            style={{ height: "100%", width: "100%" }}
            opts={{ renderer: "canvas" }}
          />
        )}

        {boatPixel && mapReady ? (
          <div
            className="travel-marker"
            data-mode={transport?.transport_mode ?? "journey"}
            data-moving={phase === "travelling"}
            data-arrived={phase === "arrived"}
            data-leg-kind={transport?.kind ?? "camera_transition"}
            style={{ transform: `translate3d(${boatPixel[0]}px, ${boatPixel[1]}px, 0)` }}
            role="img"
            aria-label={transport?.kind === "historical_route"
              ? `${transport.transport_label}史料行旅刻符`
              : "路径未载的镜头转场刻符"}
          >
            <TransportGlyph
              mode={transport?.transport_mode ?? "journey"}
              moving={phase === "travelling"}
              arrived={phase === "arrived"}
            />
          </div>
        ) : null}

        <div className="route-legend" aria-label="地图线路图例">
          <span><i data-kind="historical" />史料路线</span>
          <span><i data-kind="visual" />镜头转场 · 路径未载</span>
        </div>

        {phase === "travelling" && activeLeg && pendingIndex !== null ? (
          <div className="travel-status" aria-live="polite">
            <span>
              {activeLeg.kind === "historical_route"
                ? `${activeLeg.transport_label} · ${activeLeg.transport_certainty === "documented" ? "史料有据" : "方式未载"}`
                : "镜头转场 · 路径未载"}
            </span>
            <strong>{scene.place_historical} → {payload.scenes[pendingIndex]?.place_historical}</strong>
            <small>{activeLeg.transport_basis}</small>
            <b>{Math.round(travelProgress * 100)}%</b>
          </div>
        ) : null}

        <article className="arrival-card" data-visible={poemVisible} aria-hidden={!poemVisible}>
          <span>{scene.year_label} · {scene.year_precision_display}</span>
          <h3>{scene.place_historical || "创作地未定"}</h3>
          <p>{scene.place_modern ? `今 ${scene.place_modern}` : "现代地点未定位"}</p>
          <div>
            <MapPin size={14} aria-hidden="true" />
            <b>{scene.source_status} {scene.source_grade}级</b>
          </div>
        </article>

        <article className="journey-poem-card" data-visible={phase === "revealing" || phase === "waiting"}>
          <div className="poem-card-meta">
            <BookOpen size={15} aria-hidden="true" />
            <span>{scene.dynasty} · {scene.poet}</span>
          </div>
          <h3>《{scene.poem_title}》</h3>
          {phase === "waiting" ? (
            <InteractivePoemText
              lines={scene.poem_lines}
              poemId={scene.source_poem_id}
              className="journey-interactive-poem"
              ariaLabel={`${scene.poem_title}完整诗文`}
            />
          ) : (
            <pre aria-hidden="true">
              {poemText.slice(0, revealCount)}
              {phase === "revealing" ? <i className="reveal-cursor" /> : null}
            </pre>
          )}
          <PoemKnowledgeSummary
            poemId={scene.source_poem_id}
            onOpenKnowledge={onOpenKnowledge}
            onOpenAppreciation={onOpenAppreciation ? () => {
              setPaused(true);
              onOpenAppreciation({
                poemId: scene.source_poem_id,
                title: scene.poem_title,
                poet: scene.poet,
                dynasty: scene.dynasty,
              });
            } : undefined}
            compact
          />
        </article>

        <aside className="journey-evidence-card" data-visible={poemVisible}>
          <span>{PHASE_LABEL[phase]}</span>
          <p>{scene.event}</p>
          <details>
            <summary>史料依据</summary>
            <p>{scene.source_name}</p>
            <small>{scene.source_note}</small>
          </details>
        </aside>

        {transitionNotice ? <p className="route-gap-notice">{transitionNotice}</p> : null}
      </div>

      <div className="journey-controls" aria-label="行旅播放控制">
        <button
          type="button"
          className="icon-button"
          onClick={() => {
            if (animationFrameRef.current !== null) {
              window.cancelAnimationFrame(animationFrameRef.current);
              animationFrameRef.current = null;
            }
            travelRunRef.current += 1;
            setTransitionNotice("");
            setPendingIndex(null);
            setActiveLeg(undefined);
            setLastLeg(undefined);
            setPaused(false);
            setTravelProgress(0);
            travelProgressRef.current = 0;
            setSceneIndex(0);
            setRevealCount(reducedMotion ? fullPoemText(payload.scenes[0] as PoetryScene).length : 0);
            setPhase(reducedMotion ? "waiting" : "arrived");
            const first = payload.scenes[0];
            if (first) {
              positionAtScene(first);
              onSelectScene(first);
            }
          }}
          aria-label="重播本卷"
          title="重播本卷"
        >
          <RotateCcw size={18} aria-hidden="true" />
        </button>
        <button
          type="button"
          className="journey-command secondary"
          onClick={() => goToScene(sceneIndex - 1)}
          disabled={sceneIndex === 0 || controlsLocked}
        >
          <ChevronLeft size={18} aria-hidden="true" />
          上一站
        </button>
        <button
          type="button"
          className="journey-pause"
          onClick={() => setPaused((current) => !current)}
          disabled={!controlsLocked}
          aria-label={paused ? "继续当前动画" : "暂停当前动画"}
          title={paused ? "继续" : "暂停"}
        >
          {paused ? <Play size={19} fill="currentColor" aria-hidden="true" /> : <Pause size={19} fill="currentColor" aria-hidden="true" />}
        </button>
        <button
          type="button"
          className="journey-command primary"
          onClick={() => goToScene(sceneIndex + 1)}
          disabled={sceneIndex >= payload.scenes.length - 1 || controlsLocked}
        >
          下一站
          <ChevronRight size={18} aria-hidden="true" />
        </button>
        <span className="journey-control-status" aria-live="polite">
          {paused ? "动画已暂停" : PHASE_LABEL[phase]}
        </span>
      </div>

      <div className="journey-timeline" aria-label="诗篇编年节点">
        {payload.scenes.map((item, index) => (
          <button
            type="button"
            data-active={index === sceneIndex}
            data-mapped={item.map_eligible}
            onClick={() => goToScene(index)}
            disabled={controlsLocked}
            key={item.id}
            title={`${item.year_label} · ${item.place_historical} · 《${item.poem_title}》`}
          >
            <i />
            <span>{String(index + 1).padStart(2, "0")}</span>
            <strong>{item.year_label}</strong>
            <small>{item.place_historical || "地点未定"}</small>
          </button>
        ))}
      </div>

      <details className="journey-route-method">
        <summary>路线口径</summary>
        <p>
          靛青实线来自编年史料连线；灰金点线只连接相邻作品节点，明确标为“路径未载”。
          视觉转场不表示真实道路、交通工具或旅行速度；任一地点缺少坐标时直接切幕。
        </p>
      </details>
    </section>
  );
}
