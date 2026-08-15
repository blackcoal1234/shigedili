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
import { TransportGlyph } from "@/components/TransportGlyph";
import "@/app/motion/route.css";
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
import type { EffectiveMotionProfile } from "@/lib/motion";
import {
  freezeRouteArrival,
  getRouteMotionPolicy,
  remainingMotionDelayMs,
  revealJourneyPath,
  routeArrivalMotionProfile,
  routeTravelDurationMs,
  shouldAnimateJourneyLeg,
} from "@/lib/routeMotion";
import type {
  PoetryScene,
  RoutePayload,
} from "@/lib/types";

interface PoetRouteMapProps {
  payload: RoutePayload;
  selectedSceneId?: string;
  onSelectScene: (scene: PoetryScene) => void;
  motionProfile?: EffectiveMotionProfile;
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

export function PoetRouteMap({
  payload,
  selectedSceneId,
  onSelectScene,
  motionProfile = "cinematic",
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
  const [documentVisible, setDocumentVisible] = useState(true);
  const [arrivalMotion, setArrivalMotion] = useState(
    () => freezeRouteArrival(motionProfile),
  );
  const playerRef = useRef<HTMLElement | null>(null);
  const statusRef = useRef<HTMLSpanElement | null>(null);
  const chartRef = useRef<EChartsType | null>(null);
  const boatCoordRef = useRef<[number, number] | null>(null);
  const travelProgressRef = useRef(0);
  const animationFrameRef = useRef<number | null>(null);
  const travelRunRef = useRef(0);
  const arrivalRemainingRef = useRef(0);
  const arrivalStartedAtRef = useRef<number | null>(null);

  const scene = payload.scenes[sceneIndex];
  const poemText = scene ? fullPoemText(scene) : "";
  const effectiveMotionProfile = reducedMotion ? "off" : motionProfile;
  const renderedMotionProfile = routeArrivalMotionProfile(
    effectiveMotionProfile,
    arrivalMotion,
    phase === "arrived",
  );
  const liveMotionPolicy = getRouteMotionPolicy(effectiveMotionProfile);
  const motionPolicy = getRouteMotionPolicy(renderedMotionProfile);
  const poemVisible = phase === "arrived" || phase === "revealing" || phase === "waiting";
  const controlsLocked = phase === "travelling" || phase === "revealing";
  const transport = activeLeg ?? lastLeg;
  const activePath = useMemo(
    () => activeLeg ? sampleJourneyPath(activeLeg) : [],
    [activeLeg],
  );
  const visualTravelProgress = easeInOutCubic(travelProgress);
  const visibleActivePath = useMemo(
    () => revealJourneyPath(activePath, visualTravelProgress),
    [activePath, visualTravelProgress],
  );

  const stabilizeJourneyFocus = useCallback(() => {
    const player = playerRef.current;
    const status = statusRef.current;
    const activeElement = document.activeElement;
    if (
      !player
      || !status
      || !activeElement
      || activeElement === status
      || !player.contains(activeElement)
    ) return;
    status.focus({ preventScroll: true });
  }, []);

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
      const nextPixel: [number, number] = [pixel[0], pixel[1]];
      setBoatPixel((current) => (
        current
        && Math.abs(current[0] - nextPixel[0]) < 0.25
        && Math.abs(current[1] - nextPixel[1]) < 0.25
          ? current
          : nextPixel
      ));
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

  const arriveAt = useCallback((
    targetIndex: number,
    leg?: JourneyLeg,
    forceImmediate = false,
  ) => {
    const nextIndex = clampSceneIndex(targetIndex, payload.scenes.length);
    const target = payload.scenes[nextIndex];
    if (!target) return;
    const frozenArrival = freezeRouteArrival(effectiveMotionProfile);
    const immediate = forceImmediate || liveMotionPolicy.bypassWaits;
    stabilizeJourneyFocus();
    setArrivalMotion(frozenArrival);
    setSceneIndex(nextIndex);
    setPendingIndex(null);
    setTravelProgress(1);
    travelProgressRef.current = 1;
    setActiveLeg(undefined);
    setLastLeg(leg);
    setRevealCount(immediate ? fullPoemText(target).length : 0);
    setPaused(false);
    setPhase(immediate ? "waiting" : "arrived");
    positionAtScene(target);
    onSelectScene(target);
  }, [effectiveMotionProfile, liveMotionPolicy.bypassWaits, onSelectScene, payload.scenes, positionAtScene, stabilizeJourneyFocus]);

  const goToScene = useCallback((targetIndex: number) => {
    const nextIndex = clampSceneIndex(targetIndex, payload.scenes.length);
    if (nextIndex === sceneIndex || controlsLocked) return;
    const current = payload.scenes[sceneIndex];
    const target = payload.scenes[nextIndex];
    if (!current || !target) return;
    stabilizeJourneyFocus();

    const leg = resolveJourneyLeg(
      payload.routeSegments,
      payload.visualTransitions ?? [],
      current,
      target,
    );
    setTransitionNotice("");
    setRevealCount(0);
    setPaused(false);

    if (!leg) {
      const coordinateMissing = !current.map_eligible || !target.map_eligible
        || typeof current.lon !== "number" || typeof current.lat !== "number"
        || typeof target.lon !== "number" || typeof target.lat !== "number";
      setTransitionNotice(
        coordinateMissing
          ? "地点坐标未定，已切换到目标诗篇。"
          : "两幕之间没有可用的相邻转场数据，已切换到目标诗篇。",
      );
      arriveAt(nextIndex);
      return;
    }

    if (!shouldAnimateJourneyLeg(leg)) {
      setTransitionNotice(`${leg.transport_basis}已直接切换到目标诗篇。`);
      arriveAt(nextIndex, leg);
      return;
    }

    if (liveMotionPolicy.bypassWaits) {
      arriveAt(nextIndex, leg, true);
      return;
    }

    setActiveLeg(leg);
    setPendingIndex(nextIndex);
    setTravelProgress(0);
    travelProgressRef.current = 0;
    boatCoordRef.current = leg.coords[0];
    syncBoatPixel(leg.coords[0]);
    setPhase("travelling");
  }, [arriveAt, controlsLocked, liveMotionPolicy.bypassWaits, payload.routeSegments, payload.scenes, payload.visualTransitions, sceneIndex, stabilizeJourneyFocus, syncBoatPixel]);

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
    const update = () => setDocumentVisible(!document.hidden);
    update();
    document.addEventListener("visibilitychange", update);
    return () => document.removeEventListener("visibilitychange", update);
  }, []);

  useEffect(() => {
    if (!motionPolicy.bypassWaits) return;
    if (phase === "travelling" && pendingIndex !== null) {
      travelRunRef.current += 1;
      if (animationFrameRef.current !== null) {
        window.cancelAnimationFrame(animationFrameRef.current);
        animationFrameRef.current = null;
      }
      const settleTimer = window.setTimeout(
        () => arriveAt(pendingIndex, activeLeg, true),
        0,
      );
      return () => window.clearTimeout(settleTimer);
    }
    if ((phase === "arrived" || phase === "revealing") && scene) {
      const settleTimer = window.setTimeout(() => {
        if (phase === "revealing") stabilizeJourneyFocus();
        setRevealCount(poemText.length);
        setPaused(false);
        setPhase("waiting");
      }, 0);
      return () => window.clearTimeout(settleTimer);
    }
  }, [activeLeg, arriveAt, motionPolicy.bypassWaits, pendingIndex, phase, poemText, scene, stabilizeJourneyFocus]);

  useEffect(() => {
    arrivalRemainingRef.current = phase === "arrived" && !motionPolicy.bypassWaits
      ? arrivalMotion.delayMs
      : 0;
    arrivalStartedAtRef.current = null;
  }, [arrivalMotion, motionPolicy.bypassWaits, phase, sceneIndex]);

  useEffect(() => {
    if (phase !== "arrived" || !documentVisible || motionPolicy.bypassWaits) return;
    const delay = arrivalRemainingRef.current;
    const startedAt = performance.now();
    arrivalStartedAtRef.current = startedAt;
    const timer = window.setTimeout(
      () => {
        arrivalRemainingRef.current = 0;
        arrivalStartedAtRef.current = null;
        stabilizeJourneyFocus();
        setPhase("revealing");
      },
      delay,
    );
    return () => {
      window.clearTimeout(timer);
      if (arrivalStartedAtRef.current === startedAt) {
        arrivalRemainingRef.current = remainingMotionDelayMs(
          delay,
          startedAt,
          performance.now(),
        );
        arrivalStartedAtRef.current = null;
      }
    };
  }, [arrivalMotion, documentVisible, motionPolicy.bypassWaits, phase, sceneIndex, stabilizeJourneyFocus]);

  useEffect(() => {
    if (
      phase !== "revealing"
      || paused
      || !scene
      || !documentVisible
      || motionPolicy.bypassWaits
    ) return;
    if (motionPolicy.characterDelayScale === 0) {
      const completionTimer = window.setTimeout(() => {
        stabilizeJourneyFocus();
        setRevealCount(poemText.length);
        setPhase("waiting");
      }, 0);
      return () => window.clearTimeout(completionTimer);
    }
    if (revealCount >= poemText.length) {
      const completionTimer = window.setTimeout(() => {
        stabilizeJourneyFocus();
        setPhase("waiting");
      }, 0);
      return () => window.clearTimeout(completionTimer);
    }
    const nextCharacter = poemText[revealCount] ?? "";
    const timer = window.setTimeout(
      () => setRevealCount((current) => Math.min(poemText.length, current + 1)),
      Math.round(revealDelayMs(nextCharacter) * motionPolicy.characterDelayScale),
    );
    return () => window.clearTimeout(timer);
  }, [documentVisible, motionPolicy.bypassWaits, motionPolicy.characterDelayScale, paused, phase, poemText, revealCount, scene, stabilizeJourneyFocus]);

  useEffect(() => {
    if (
      phase !== "travelling"
      || paused
      || !documentVisible
      || motionPolicy.bypassWaits
      || !activeLeg
      || !shouldAnimateJourneyLeg(activeLeg)
      || activePath.length === 0
      || pendingIndex === null
    ) return;
    const runId = travelRunRef.current + 1;
    travelRunRef.current = runId;
    const startProgress = travelProgressRef.current;
    const duration = routeTravelDurationMs(activeLeg, effectiveMotionProfile);
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
  }, [activeLeg, activePath, arriveAt, documentVisible, effectiveMotionProfile, motionPolicy.bypassWaits, paused, pendingIndex, phase, syncBoatPixel]);

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
    const canFocusScene = motionPolicy.focusOnArrival
      && (phase === "arrived" || phase === "revealing")
      && typeof scene?.lon === "number"
      && typeof scene.lat === "number";
    const mapCenter: [number, number] = canFocusScene
      ? [scene.lon as number, scene.lat as number]
      : center;
    const mapZoom = canFocusScene
      ? Math.min(4.2, zoom * motionPolicy.focusZoomScale)
      : zoom;
    const isComplete = (segment: { from_id: string; to_id: string }) => {
      const from = sceneOrder.get(segment.from_id) ?? Number.MAX_SAFE_INTEGER;
      const to = sceneOrder.get(segment.to_id) ?? Number.MAX_SAFE_INTEGER;
      return Math.max(from, to) <= sceneIndex;
    };
    const historicalSegments = payload.routeSegments.filter(
      (segment) => segment.kind === "chronology"
        && segment.certainty === "strict"
        && segment.historical_claim !== false,
    );
    const historicalGuides = historicalSegments.map((segment) => ({
      coords: sampleJourneyPath(segment),
    }));
    const visualGuides = (payload.visualTransitions ?? []).map((segment) => ({
      coords: sampleJourneyPath(segment),
    }));
    const completedGuides = [
      ...historicalSegments.filter(isComplete),
    ].map((segment) => ({ coords: sampleJourneyPath(segment) }));
    const points: MapPoint[] = mappedScenes.map((item) => ({
      sceneId: item.id,
      sceneIndex: sceneOrder.get(item.id) ?? 0,
      scene: item,
      value: [item.lon as number, item.lat as number],
    }));

    return {
      animation: renderedMotionProfile !== "off",
      animationDuration: motionPolicy.mapAnimationMs,
      animationDurationUpdate: phase === "travelling" ? 0 : motionPolicy.mapAnimationMs,
      aria: {
        enabled: true,
        decal: { show: false },
        label: {
          description: `${payload.poet}行旅图，共${payload.sceneCount}幕、${historicalSegments.length}条史料路线、${payload.visualTransitions?.length ?? 0}条路径未载的镜头转场。交通方式只取来源文字。`,
        },
      },
      tooltip: {
        trigger: "item",
        confine: true,
        backgroundColor: "rgba(255,253,247,.97)",
        borderColor: "rgba(37,43,39,.22)",
        padding: [9, 11],
        textStyle: { color: "#252b27", fontFamily: "Microsoft YaHei", fontSize: 12 },
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
        center: mapCenter,
        zoom: mapZoom,
        scaleLimit: { min: 0.85, max: 6 },
        itemStyle: {
          areaColor: "#edf0e9",
          borderColor: "#cbd1ca",
          borderWidth: 0.75,
        },
        emphasis: { itemStyle: { areaColor: "#e7ebe5" }, label: { show: false } },
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
          lineStyle: { color: "#315f7d", width: 2.4, type: "solid", opacity: 0.78 },
          data: historicalGuides,
        },
        {
          id: "route-visual-guides",
          type: "lines",
          coordinateSystem: "geo",
          silent: true,
          polyline: true,
          z: 2,
          lineStyle: { color: "#93846b", width: 1.7, type: "dashed", opacity: 0.62 },
          data: visualGuides,
        },
        {
          id: "route-complete",
          type: "lines",
          coordinateSystem: "geo",
          silent: true,
          polyline: true,
          z: 3,
          lineStyle: { color: payload.color ?? "#426f94", width: 3, opacity: 0.82 },
          data: completedGuides,
        },
        {
          id: "route-active-halo",
          type: "lines",
          coordinateSystem: "geo",
          silent: true,
          polyline: true,
          z: 4,
          lineStyle: {
            color: "#fff5e6",
            width: motionPolicy.activeHaloWidth,
            opacity: motionPolicy.activeHaloWidth > 0 ? 0.9 : 0,
          },
          data: [],
        },
        {
          id: "route-active-ink-spread",
          type: "lines",
          coordinateSystem: "geo",
          silent: true,
          polyline: true,
          z: 4,
          lineStyle: {
            color: "#252b27",
            width: 12,
            opacity: 0.12,
            shadowBlur: 7,
            shadowColor: "rgba(37,43,39,.28)",
          },
          data: [],
        },
        {
          id: "route-active-main",
          type: "lines",
          coordinateSystem: "geo",
          silent: true,
          polyline: true,
          z: 5,
          lineStyle: {
            color: payload.color ?? "#426f94",
            width: motionPolicy.activeStrokeWidth,
            opacity: 0.96,
          },
          data: [],
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
            color: "#4b514c",
            fontFamily: "Microsoft YaHei",
            fontSize: 10,
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
                ? "#b64b3f"
                : point.sceneIndex < sceneIndex
                  ? payload.color ?? "#426f94"
                  : "#fffdf7",
              borderColor: point.sceneIndex === sceneIndex ? "#fffdf7" : payload.color ?? "#426f94",
              borderWidth: 2,
              shadowBlur: point.sceneIndex === sceneIndex ? 12 : 0,
              shadowColor: "rgba(182,75,63,.28)",
            },
          })),
        },
      ],
    };
  }, [mappedScenes, motionPolicy, payload, phase, renderedMotionProfile, scene, sceneIndex]);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || !mapReady) return;
    const activeRoute = visibleActivePath.length > 1
      ? [{ coords: visibleActivePath }]
      : [];
    chart.setOption({
      series: [
        {
          id: "route-active-halo",
          data: motionPolicy.activeHaloWidth > 0 ? activeRoute : [],
        },
        {
          id: "route-active-ink-spread",
          data: motionPolicy.showInkSpread ? activeRoute : [],
        },
        {
          id: "route-active-main",
          data: activeRoute,
        },
      ],
    }, { lazyUpdate: true });
  }, [mapReady, motionPolicy.activeHaloWidth, motionPolicy.showInkSpread, visibleActivePath]);

  const chartEvents = useMemo(() => ({
    click: (params: unknown) => {
      const point = (params as { data?: MapPoint }).data;
      if (typeof point?.sceneIndex === "number") goToScene(point.sceneIndex);
    },
    georoam: () => syncBoatPixel(),
    rendered: () => syncBoatPixel(),
    finished: () => syncBoatPixel(),
  }), [goToScene, syncBoatPixel]);

  if (!scene || mappedScenes.length === 0) {
    return <EmptyState title="没有可落图坐标" detail="镜头仍保留在证据列表中。" />;
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
      ref={playerRef}
      className="journey-player"
      data-phase={phase}
      data-motion-profile={renderedMotionProfile}
      data-document-visible={documentVisible}
      data-transport={transport?.transport_mode ?? "none"}
      aria-labelledby="journey-title"
      tabIndex={0}
      onKeyDown={(event) => {
        if (event.target !== event.currentTarget) return;
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

      <div
        className="journey-stage"
        data-focus={motionPolicy.focusOnArrival && (phase === "arrived" || phase === "revealing")}
        data-transport={transport?.transport_mode ?? "none"}
        aria-busy={!mapReady || phase === "travelling"}
      >
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
              syncBoatPixel();
            }}
            className="journey-map-chart"
            style={{ height: "100%", width: "100%" }}
            opts={{ renderer: "canvas" }}
          />
        )}

        <div
          className="journey-paper-veil"
          data-visible={motionPolicy.showPaperVeil && phase === "arrived"}
          aria-hidden="true"
        />

        {boatPixel && motionPolicy.showNodeRipple ? (
          <div
            className="journey-node-ripple"
            data-visible={phase === "arrived" || phase === "revealing"}
            style={{ transform: `translate3d(${boatPixel[0]}px, ${boatPixel[1]}px, 0)` }}
            aria-hidden="true"
          >
            <i />
            <i />
          </div>
        ) : null}

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

        {scene.place_historical ? (
          <div
            className="journey-arrival-seal"
            data-visible={motionPolicy.showArrivalSeal && poemVisible}
            aria-hidden="true"
            key={scene.id}
          >
            <span>{scene.place_historical}</span>
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

        <article
          className="journey-poem-card"
          data-visible={phase === "revealing" || phase === "waiting"}
          aria-hidden={phase !== "revealing" && phase !== "waiting"}
        >
          <div className="poem-card-meta">
            <BookOpen size={15} aria-hidden="true" />
            <span>{scene.dynasty} · {scene.poet}</span>
          </div>
          <h3>《{scene.poem_title}》</h3>
          <p className="sr-only">{poemText}</p>
          <pre aria-hidden="true">
            {poemText.slice(0, revealCount)}
            {phase === "revealing" ? <i className="reveal-cursor" /> : null}
          </pre>
        </article>

        <aside
          className="journey-evidence-card"
          data-visible={poemVisible}
          aria-hidden={!poemVisible}
          inert={!poemVisible}
        >
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
            const frozenArrival = freezeRouteArrival(effectiveMotionProfile);
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
            setArrivalMotion(frozenArrival);
            setSceneIndex(0);
            setRevealCount(liveMotionPolicy.bypassWaits ? fullPoemText(payload.scenes[0] as PoetryScene).length : 0);
            setPhase(liveMotionPolicy.bypassWaits ? "waiting" : "arrived");
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
        <span
          ref={statusRef}
          className="journey-control-status"
          tabIndex={-1}
          aria-live="polite"
        >
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
