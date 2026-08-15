"use client";

import { CopilotKit } from "@copilotkit/react-core";
import { CopilotPopup } from "@copilotkit/react-ui";
import {
  Bot,
  Clapperboard,
  Map,
  Play,
  RefreshCw,
  Scale,
  Server,
  Sparkles,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";

import { EvidencePanel } from "@/components/EvidencePanel";
import { GenerativeExplanation } from "@/components/GenerativeExplanation";
import { ImageryComparison } from "@/components/ImageryComparison";
import { MotionLabControls } from "@/components/MotionLabControls";
import { PoemScenePlayer } from "@/components/PoemScenePlayer";
import { PoetRouteMap } from "@/components/PoetRouteMap";
import { PoetSelector } from "@/components/PoetSelector";
import {
  EmptyState,
  ErrorState,
  GalaxyLoader,
  InsufficientState,
} from "@/components/StateViews";
import { journeyPayloadKey } from "@/lib/journey";
import {
  DEFAULT_MOTION_PREFERENCE,
  MOTION_PREFERENCE_EVENT,
  MOTION_STORAGE_KEY,
  effectiveMotionProfile,
  parseMotionPreference,
  serializeMotionPreference,
  type EffectiveMotionProfile,
  type MotionPreference,
} from "@/lib/motion";
import type {
  PoetCatalog,
  PoetryScene,
  ToolResponse,
  WorkbenchMode,
  WorkbenchPayload,
} from "@/lib/types";
import {
  fetchCatalog,
  fetchWorkbenchMode,
  isImageryPayload,
  isRoutePayload,
  isScenePayload,
  MODE_LABEL,
  payloadError,
} from "@/lib/workbench";

const GENERATIVE_COOKIE = "poetry-open-generative-ui";
const GENERATIVE_PREFERENCE_EVENT = "poetry-generative-preference";
const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";
const DEFAULT_MOTION_SERIALIZED = serializeMotionPreference(DEFAULT_MOTION_PREFERENCE);
let volatileMotionPreference = DEFAULT_MOTION_SERIALIZED;
let preferVolatileMotionPreference = false;

function subscribeMotionPreference(listener: () => void) {
  window.addEventListener(MOTION_PREFERENCE_EVENT, listener);
  window.addEventListener("storage", listener);
  return () => {
    window.removeEventListener(MOTION_PREFERENCE_EVENT, listener);
    window.removeEventListener("storage", listener);
  };
}

function getMotionPreferenceSnapshot(): string {
  if (preferVolatileMotionPreference) return volatileMotionPreference;
  try {
    return window.localStorage.getItem(MOTION_STORAGE_KEY) ?? DEFAULT_MOTION_SERIALIZED;
  } catch {
    preferVolatileMotionPreference = true;
    return volatileMotionPreference;
  }
}

function getServerMotionPreferenceSnapshot(): string {
  return DEFAULT_MOTION_SERIALIZED;
}

function subscribeReducedMotion(listener: () => void) {
  if (typeof window.matchMedia !== "function") return () => undefined;
  const media = window.matchMedia(REDUCED_MOTION_QUERY);
  media.addEventListener("change", listener);
  return () => media.removeEventListener("change", listener);
}

function getReducedMotionSnapshot(): boolean {
  return typeof window.matchMedia === "function"
    ? window.matchMedia(REDUCED_MOTION_QUERY).matches
    : false;
}

function getServerReducedMotionSnapshot(): boolean {
  return false;
}

const GENERATIVE_SKILL = [
  "只读取当前工具已经返回的 payload。",
  "仅生成临时解释 SVG 或解释控件。",
  "保持所有历史数据、数值、排序、证据等级与来源不变。",
  "不提供写入或变更数据的交互。",
].join(" ");

const MODE_ITEMS: Array<{
  id: WorkbenchMode;
  label: string;
  shortLabel: string;
  icon: typeof Map;
}> = [
  { id: "route", label: "诗人行迹", shortLabel: "行迹", icon: Map },
  { id: "scenes", label: "逐幕诗篇", shortLabel: "逐幕", icon: Clapperboard },
  { id: "imagery", label: "唐宋意象", shortLabel: "意象", icon: Scale },
];

type Phase = "idle" | "loading" | "success" | "error";

interface ToolState {
  phase: Phase;
  response: ToolResponse<WorkbenchPayload> | null;
  error: string;
}

function useGenerativePreference() {
  const subscribe = useCallback((listener: () => void) => {
    window.addEventListener(GENERATIVE_PREFERENCE_EVENT, listener);
    return () => window.removeEventListener(GENERATIVE_PREFERENCE_EVENT, listener);
  }, []);
  const getSnapshot = useCallback(() => {
    const value = document.cookie
      .split("; ")
      .find((item) => item.startsWith(`${GENERATIVE_COOKIE}=`))
      ?.split("=")[1];
    return value === "1";
  }, []);
  const enabled = useSyncExternalStore(subscribe, getSnapshot, () => false);

  const setEnabled = useCallback((next: boolean) => {
    document.cookie = `${GENERATIVE_COOKIE}=${next ? "1" : "0"}; Path=/; Max-Age=31536000; SameSite=Lax`;
    window.dispatchEvent(new Event(GENERATIVE_PREFERENCE_EVENT));
  }, []);

  return [enabled, setEnabled] as const;
}

function useMotionPreference() {
  const serializedPreference = useSyncExternalStore(
    subscribeMotionPreference,
    getMotionPreferenceSnapshot,
    getServerMotionPreferenceSnapshot,
  );
  const reducedMotion = useSyncExternalStore(
    subscribeReducedMotion,
    getReducedMotionSnapshot,
    getServerReducedMotionSnapshot,
  );
  const preference = useMemo(
    () => parseMotionPreference(serializedPreference),
    [serializedPreference],
  );

  const updatePreference = useCallback((next: MotionPreference) => {
    const serialized = serializeMotionPreference(next);
    volatileMotionPreference = serialized;
    try {
      window.localStorage.setItem(MOTION_STORAGE_KEY, serialized);
      preferVolatileMotionPreference = false;
    } catch {
      preferVolatileMotionPreference = true;
      // The in-memory preference remains usable when storage is unavailable.
    }
    window.dispatchEvent(new Event(MOTION_PREFERENCE_EVENT));
  }, []);

  return [preference, effectiveMotionProfile(preference, reducedMotion), updatePreference] as const;
}

export function PoetryWorkbench() {
  const [generativeEnabled, setGenerativeEnabled] = useGenerativePreference();

  return (
    <CopilotKit
      runtimeUrl={process.env.NEXT_PUBLIC_COPILOTKIT_RUNTIME_URL ?? "/api/copilotkit"}
      agent="poetry_evidence_agent"
      useSingleEndpoint
      showDevConsole={false}
      enableInspector={false}
      openGenerativeUI={generativeEnabled ? { designSkill: GENERATIVE_SKILL } : undefined}
    >
      <WorkbenchBody
        generativeEnabled={generativeEnabled}
        onGenerativeChange={setGenerativeEnabled}
      />
      <CopilotPopup
        labels={{
          title: "诗史问答",
          initial: "请选择一位诗人，或直接询问行迹、逐幕诗篇与唐宋意象。",
          placeholder: "询问诗人、诗篇或意象…",
        }}
        clickOutsideToClose
      />
    </CopilotKit>
  );
}

function WorkbenchBody({
  generativeEnabled,
  onGenerativeChange,
}: {
  generativeEnabled: boolean;
  onGenerativeChange: (next: boolean) => void;
}) {
  const [motionPreference, motionProfile, setMotionPreference] = useMotionPreference();
  const [catalog, setCatalog] = useState<ToolResponse<PoetCatalog> | null>(null);
  const [catalogPhase, setCatalogPhase] = useState<Phase>("loading");
  const [catalogError, setCatalogError] = useState("");
  const [selectedPoet, setSelectedPoet] = useState("");
  const [mode, setMode] = useState<WorkbenchMode>("route");
  const [toolState, setToolState] = useState<ToolState>({
    phase: "idle",
    response: null,
    error: "",
  });
  const [activeScene, setActiveScene] = useState<PoetryScene>();
  const catalogAbort = useRef<AbortController | null>(null);
  const toolAbort = useRef<AbortController | null>(null);
  const requestSequence = useRef(0);

  const executeMode = useCallback(async (nextMode: WorkbenchMode, poet: string) => {
    if (nextMode !== "imagery" && !poet) return;
    toolAbort.current?.abort();
    const controller = new AbortController();
    const requestId = ++requestSequence.current;
    toolAbort.current = controller;
    setToolState({ phase: "loading", response: null, error: "" });
    setActiveScene(undefined);

    try {
      const response = await fetchWorkbenchMode(nextMode, poet, controller.signal);
      if (requestId !== requestSequence.current) return;
      const error = payloadError(response);
      if (error) {
        setToolState({ phase: "error", response, error });
        return;
      }
      if (!isImageryPayload(response.payload)) {
        setActiveScene(response.payload.scenes[0]);
      }
      setToolState({ phase: "success", response, error: "" });
    } catch (error) {
      if (controller.signal.aborted || requestId !== requestSequence.current) return;
      setToolState({
        phase: "error",
        response: null,
        error: error instanceof Error ? error.message : "请求未完成",
      });
    }
  }, []);

  const loadCatalog = useCallback(async () => {
    catalogAbort.current?.abort();
    const controller = new AbortController();
    catalogAbort.current = controller;
    setCatalogPhase("loading");
    setCatalogError("");
    try {
      const response = await fetchCatalog(controller.signal);
      if (response.status !== "ok") {
        const payload = response.payload as PoetCatalog & { error?: string };
        throw new Error(payload.error ?? "目录数据状态异常");
      }
      setCatalog(response);
      setCatalogPhase("success");
      const initialPoet = response.payload.poets.find((row) => row.poet === "李白")
        ?? response.payload.poets.find((row) => row.routeStatus === "available")
        ?? response.payload.poets[0];
      if (initialPoet) {
        setSelectedPoet(initialPoet.poet);
        void executeMode("route", initialPoet.poet);
      }
    } catch (error) {
      if (controller.signal.aborted) return;
      setCatalogPhase("error");
      setCatalogError(error instanceof Error ? error.message : "诗人目录读取失败");
    }
  }, [executeMode]);

  useEffect(() => {
    const timer = window.setTimeout(() => void loadCatalog(), 0);
    return () => {
      window.clearTimeout(timer);
      catalogAbort.current?.abort();
      toolAbort.current?.abort();
    };
  }, [loadCatalog]);

  const selectedCatalogRow = catalog?.payload.poets.find((row) => row.poet === selectedPoet);
  const imageryEvidenceCount = useMemo(() => {
    const payload = toolState.response?.payload;
    return payload && isImageryPayload(payload)
      ? payload.comparisons.reduce((sum, row) => sum + row.corpusEvidence.length, 0)
      : undefined;
  }, [toolState.response]);

  const choosePoet = (poet: string) => {
    setSelectedPoet(poet);
    if (mode !== "imagery") void executeMode(mode, poet);
  };

  const chooseMode = (nextMode: WorkbenchMode) => {
    setMode(nextMode);
    void executeMode(nextMode, selectedPoet);
  };

  const retryTool = () => void executeMode(mode, selectedPoet);

  return (
    <main className="workbench-shell" data-motion-profile={motionProfile}>
      <header className="masthead">
        <div className="brand-lockup">
          <div className="seal" aria-hidden="true">诗</div>
          <div>
            <p className="eyebrow">唐宋诗歌证据工作台</p>
            <h1>诗行万里</h1>
          </div>
        </div>
        <div className="header-actions">
          <MotionLabControls
            preference={motionPreference}
            effectiveProfile={motionProfile}
            onChange={setMotionPreference}
          />
          <span className="service-status">
            <Server size={14} aria-hidden="true" />
            <i />
            确定性数据源
          </span>
          <label className="generative-control">
            <span className="generative-copy">
              <SparkleLabel />
              <span>OpenGenerativeUI</span>
            </span>
            <input
              className="sr-only"
              type="checkbox"
              checked={generativeEnabled}
              onChange={(event) => onGenerativeChange(event.target.checked)}
            />
            <span className="galaxy-toggle" aria-hidden="true"><i /></span>
          </label>
        </div>
      </header>

      <nav className="mode-tabs" aria-label="查看模式">
        {MODE_ITEMS.map((item) => {
          const Icon = item.icon;
          return (
            <button
              type="button"
              aria-current={mode === item.id ? "page" : undefined}
              data-active={mode === item.id}
              onClick={() => chooseMode(item.id)}
              key={item.id}
            >
              <Icon size={16} aria-hidden="true" />
              <span className="mode-label-long">{item.label}</span>
              <span className="mode-label-short">{item.shortLabel}</span>
            </button>
          );
        })}
      </nav>

      {catalogPhase === "loading" ? (
        <div className="catalog-state"><GalaxyLoader label="正在建立 88 位诗人目录" /></div>
      ) : catalogPhase === "error" || !catalog ? (
        <div className="catalog-state">
          <ErrorState message={catalogError || "目录为空"} onRetry={() => void loadCatalog()} />
        </div>
      ) : (
        <div className="workbench-grid">
          <div className="poet-dock" data-visible={mode !== "imagery"}>
            {mode !== "imagery" ? (
              <PoetSelector
                poets={catalog.payload.poets}
                selectedPoet={selectedPoet}
                onSelect={choosePoet}
              />
            ) : (
              <div className="corpus-dock-copy">
                <Scale size={17} aria-hidden="true" />
                <div><strong>唐宋全库对读</strong><span>诗人选择在意象模式中不参与计算</span></div>
              </div>
            )}
            <div className="catalog-summary">
              <div><strong>{catalog.payload.poetCount}</strong><span>诗人</span></div>
              <div><strong>{catalog.payload.routeAvailableCount}</strong><span>路线可用</span></div>
              <div><strong>{catalog.payload.insufficientEvidenceCount}</strong><span>证据待补</span></div>
            </div>
          </div>

          <section className="workspace" aria-labelledby="workspace-title">
            <div className="workspace-toolbar">
              <div>
                <span className="workspace-kicker">{MODE_LABEL[mode]}</span>
                <h2 id="workspace-title">
                  {mode === "imagery" ? "全库唐宋对读" : selectedPoet || "未选择诗人"}
                </h2>
                <p>
                  {mode === "imagery"
                    ? "审核意象词 · 每万汉字率"
                    : `${selectedCatalogRow?.dynasty ?? ""} · 语料 ${selectedCatalogRow?.workCount ?? 0} 篇`}
                </p>
              </div>
              <button
                type="button"
                className="primary-command"
                onClick={retryTool}
                disabled={toolState.phase === "loading"}
              >
                {toolState.phase === "loading"
                  ? <RefreshCw size={16} className="spin" aria-hidden="true" />
                  : mode === "scenes"
                    ? <Play size={16} aria-hidden="true" />
                    : <RefreshCw size={16} aria-hidden="true" />}
                {mode === "route" ? "生成行迹" : mode === "scenes" ? "载入逐幕" : "比较意象"}
              </button>
            </div>

            <div className="data-surface" aria-live="polite">
              {toolState.phase === "loading" ? <GalaxyLoader /> : null}
              {toolState.phase === "error" ? (
                <ErrorState message={toolState.error} onRetry={retryTool} />
              ) : null}
              {toolState.phase === "idle" ? (
                <EmptyState title="尚未调用数据工具" detail="选择模式以读取对应证据。" />
              ) : null}
              {toolState.phase === "success" && toolState.response ? (
                <WorkbenchResult
                  mode={mode}
                  response={toolState.response}
                  activeScene={activeScene}
                  onSceneChange={setActiveScene}
                  motionProfile={motionProfile}
                />
              ) : null}
            </div>

            {toolState.response ? (
              <>
                <EvidencePanel
                  response={toolState.response}
                  activeScene={activeScene}
                  imageryEvidenceCount={imageryEvidenceCount}
                />
                {generativeEnabled && toolState.response.status === "ok" ? (
                  <GenerativeExplanation mode={mode} payload={toolState.response.payload} />
                ) : null}
              </>
            ) : null}
          </section>
        </div>
      )}

      <footer className="app-footer">
        <span><Bot size={14} aria-hidden="true" /> CopilotKit remote agent</span>
        <span>数据由 Python 生成管线提供</span>
      </footer>
    </main>
  );
}

function WorkbenchResult({
  mode,
  response,
  activeScene,
  onSceneChange,
  motionProfile,
}: {
  mode: WorkbenchMode;
  response: ToolResponse<WorkbenchPayload>;
  activeScene?: PoetryScene;
  onSceneChange: (scene: PoetryScene) => void;
  motionProfile: EffectiveMotionProfile;
}) {
  const payload = response.payload;
  if (response.status === "insufficient_evidence") {
    const missingFacts = "missingFacts" in payload ? payload.missingFacts : undefined;
    return <InsufficientState missingFacts={missingFacts} />;
  }

  if (mode === "route" && isRoutePayload(payload)) {
    if (payload.scenes.length === 0) return <EmptyState title="路线为空" />;
    return (
      <PoetRouteMap
        key={journeyPayloadKey(payload)}
        payload={payload}
        selectedSceneId={activeScene?.id}
        onSelectScene={onSceneChange}
        motionProfile={motionProfile}
      />
    );
  }

  if (mode === "scenes" && isScenePayload(payload)) {
    return (
      <PoemScenePlayer
        key={`${payload.poet}-${payload.startSceneId ?? "start"}-${payload.sceneCount}`}
        payload={payload}
        onSceneChange={onSceneChange}
        motionProfile={motionProfile}
      />
    );
  }

  if (mode === "imagery" && isImageryPayload(payload)) {
    return (
      <ImageryComparison
        key={payload.terms.join("|")}
        payload={payload}
        motionProfile={motionProfile}
      />
    );
  }

  return <EmptyState title="返回结构与当前模式不匹配" />;
}

function SparkleLabel() {
  return <Sparkles className="sparkle-mark" size={14} aria-hidden="true" />;
}
