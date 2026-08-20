"use client";

import { ArrowLeft, BookOpen, ChevronDown, RotateCw, Search, SlidersHorizontal, X } from "lucide-react";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import {
  fetchKnowledgePoem,
  fetchKnowledgeStatus,
  knowledgeTagLabel,
  searchKnowledge,
} from "@/lib/knowledge";
import type {
  KnowledgeAnalysis,
  KnowledgePoemPayload,
  KnowledgeSearchItem,
  KnowledgeSearchPayload,
  KnowledgeSearchMode,
  KnowledgeVectorStatus,
} from "@/lib/types";

interface KnowledgeExplorerProps {
  open: boolean;
  initialPoemId?: string | null;
  initialLineId?: string | null;
  onClose: () => void;
  onSelectionChange: (poemId: string | null, lineId: string | null) => void;
  returnFocusRef?: React.RefObject<HTMLElement | null>;
}

type ExplorerPhase = "idle" | "loading" | "success" | "error";
interface KnowledgeCriteria {
  query: string;
  poet: string;
  dynasty: string;
  imagery: string;
  emotion: string;
  mode: KnowledgeSearchMode;
}

const tagValues = (values: KnowledgeSearchItem["imagery"] | KnowledgeSearchItem["emotions"]) => (
  (values ?? []).map(knowledgeTagLabel).filter(Boolean).slice(0, 5)
);
const PAGE_SIZE = 30;

export function KnowledgeExplorer({
  open,
  initialPoemId,
  initialLineId,
  onClose,
  onSelectionChange,
  returnFocusRef,
}: KnowledgeExplorerProps) {
  const [query, setQuery] = useState("");
  const [poet, setPoet] = useState("");
  const [dynasty, setDynasty] = useState("");
  const [imagery, setImagery] = useState("");
  const [emotion, setEmotion] = useState("");
  const [mode, setMode] = useState<KnowledgeSearchMode>("lexical");
  const [vectorStatus, setVectorStatus] = useState<KnowledgeVectorStatus>();
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [phase, setPhase] = useState<ExplorerPhase>("idle");
  const [results, setResults] = useState<KnowledgeSearchPayload>();
  const [detail, setDetail] = useState<KnowledgePoemPayload>();
  const [targetLineId, setTargetLineId] = useState<string>();
  const [error, setError] = useState("");
  const abortRef = useRef<AbortController | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const resultsRef = useRef<HTMLDivElement>(null);
  const resultsMetaRef = useRef<HTMLDivElement>(null);
  const requestSequence = useRef(0);
  const initializedKey = useRef("");
  const actualOpener = useRef<HTMLElement | null>(null);
  const activeCriteria = useRef<KnowledgeCriteria>({
    query: "",
    poet: "",
    dynasty: "",
    imagery: "",
    emotion: "",
    mode: "lexical",
  });

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    void fetchKnowledgeStatus(controller.signal)
      .then((response) => setVectorStatus(response.payload.vector))
      .catch(() => setVectorStatus(undefined));
    return () => controller.abort();
  }, [open]);

  const loadPoem = useCallback(async (poemId: string, lineId?: string) => {
    abortRef.current?.abort();
    const controller = new AbortController();
    const requestId = ++requestSequence.current;
    abortRef.current = controller;
    setPhase("loading");
    setDetail(undefined);
    setTargetLineId(undefined);
    setError("");
    try {
      const response = await fetchKnowledgePoem(poemId, controller.signal);
      if (requestId !== requestSequence.current) return;
      const validLineId = lineId && response.payload.lines.some(
        (line) => line.lineId === lineId,
      ) ? lineId : undefined;
      setDetail(response.payload);
      setTargetLineId(validLineId);
      setPhase("success");
      initializedKey.current = `${response.payload.poemId}:${validLineId ?? ""}`;
      onSelectionChange(response.payload.poemId, validLineId ?? null);
    } catch (cause) {
      if (controller.signal.aborted || requestId !== requestSequence.current) return;
      setPhase("error");
      setError(cause instanceof Error ? cause.message : "诗篇知识读取失败");
    }
  }, [onSelectionChange]);

  const runSearch = useCallback(async (
    offset = 0,
    source: "draft" | "active" = "draft",
    focusResults = false,
  ) => {
    const criteria = source === "active"
      ? activeCriteria.current
      : { query, poet, dynasty, imagery, emotion, mode };
    if (source === "draft") activeCriteria.current = criteria;
    const requestedMode = criteria.query.trim() ? criteria.mode : "lexical";
    abortRef.current?.abort();
    const controller = new AbortController();
    const requestId = ++requestSequence.current;
    abortRef.current = controller;
    setPhase("loading");
    setDetail(undefined);
    setTargetLineId(undefined);
    setError("");
    initializedKey.current = "__search__";
    onSelectionChange(null, null);
    try {
      const response = await searchKnowledge({
        query: criteria.query,
        poet: criteria.poet || undefined,
        dynasty: criteria.dynasty || undefined,
        imagery: criteria.imagery || undefined,
        emotion: criteria.emotion || undefined,
        mode: requestedMode,
        scope: criteria.query.trim() ? "all" : "poem",
        limit: PAGE_SIZE,
        offset,
      }, controller.signal);
      if (requestId !== requestSequence.current) return;
      setResults(response.payload);
      setPhase("success");
      window.requestAnimationFrame(() => {
        resultsRef.current?.scrollTo({ top: 0 });
        if (focusResults) resultsMetaRef.current?.focus();
      });
    } catch (cause) {
      if (controller.signal.aborted || requestId !== requestSequence.current) return;
      setPhase("error");
      setError(cause instanceof Error ? cause.message : "知识库检索失败");
    }
  }, [dynasty, emotion, imagery, mode, onSelectionChange, poet, query]);

  useEffect(() => {
    if (!open) {
      initializedKey.current = "";
      return;
    }
    const key = initialPoemId
      ? `${initialPoemId}:${initialLineId ?? ""}`
      : "__search__";
    if (initializedKey.current === key) return;
    initializedKey.current = key;
    const timer = window.setTimeout(() => {
      if (initialPoemId) void loadPoem(initialPoemId, initialLineId ?? undefined);
      else {
        inputRef.current?.focus();
        void runSearch();
      }
    }, 0);
    return () => window.clearTimeout(timer);
  }, [initialLineId, initialPoemId, loadPoem, open, runSearch]);

  useEffect(() => {
    if (!open) return;
    actualOpener.current = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : returnFocusRef?.current ?? null;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
      }
      if (event.key === "Tab") {
        const dialog = closeRef.current?.closest<HTMLElement>("[role=dialog]");
        const focusable = dialog?.querySelectorAll<HTMLElement>(
          "button:not([disabled]), input:not([disabled]), select:not([disabled]), a[href]",
        );
        if (!focusable?.length) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (!first || !last) return;
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", onKeyDown);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = overflow;
      abortRef.current?.abort();
      actualOpener.current?.focus();
    };
  }, [onClose, open, returnFocusRef]);

  useEffect(() => {
    if (!open || !initialPoemId || initialLineId) return;
    const timer = window.setTimeout(() => closeRef.current?.focus(), 0);
    return () => window.clearTimeout(timer);
  }, [initialLineId, initialPoemId, open]);

  if (!open) return null;

  return (
    <div className="knowledge-overlay" data-testid="knowledge-overlay">
      <div
        className="knowledge-scrim"
        aria-hidden="true"
        onClick={onClose}
      />
      <section
        className="knowledge-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="knowledge-title"
      >
        <header className="knowledge-header">
          <div>
            <span className="workspace-kicker">诗句 · 意象 · 情感</span>
            <h2 id="knowledge-title">诗词知识库</h2>
          </div>
          <button ref={closeRef} type="button" className="icon-command" onClick={onClose} aria-label="关闭">
            <X size={19} aria-hidden="true" />
          </button>
        </header>

        {detail ? (
          <KnowledgeDetail
            poem={detail}
            targetLineId={targetLineId}
            onBack={() => {
              setDetail(undefined);
              setTargetLineId(undefined);
              initializedKey.current = "__search__";
              onSelectionChange(null, null);
              window.requestAnimationFrame(() => inputRef.current?.focus());
            }}
          />
        ) : (
          <>
            <form
              className="knowledge-search"
              onSubmit={(event) => {
                event.preventDefault();
                void runSearch(0, "draft");
              }}
            >
              <label className="knowledge-query">
                <Search size={17} aria-hidden="true" />
                <span className="sr-only">搜索题名、诗人、诗句或分析</span>
                <input
                  ref={inputRef}
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="题名、诗人、诗句或分析…"
                />
              </label>
              <button type="submit" className="knowledge-submit" disabled={phase === "loading"}>
                检索
              </button>
              <div className="knowledge-mode" role="group" aria-label="检索方式">
                {(["lexical", "semantic", "hybrid"] as const).map((value) => {
                  const disabled = value !== "lexical" && !vectorStatus?.ready;
                  const label = value === "lexical" ? "关键词" : value === "semantic" ? "语义" : "混合";
                  return (
                    <button
                      key={value}
                      type="button"
                      className={mode === value ? "is-active" : ""}
                      aria-pressed={mode === value}
                      disabled={disabled}
                      title={disabled ? "向量索引尚未就绪" : undefined}
                      onClick={() => setMode(value)}
                    >
                      {label}
                    </button>
                  );
                })}
              </div>
              <button
                type="button"
                className="knowledge-filter-toggle"
                aria-expanded={filtersOpen}
                onClick={() => setFiltersOpen((value) => !value)}
              >
                <SlidersHorizontal size={16} aria-hidden="true" />
                筛选
              </button>
              {filtersOpen ? (
                <div className="knowledge-filters">
                  <label><span>诗人</span><input value={poet} onChange={(event) => setPoet(event.target.value)} /></label>
                  <label><span>朝代</span><input value={dynasty} onChange={(event) => setDynasty(event.target.value)} /></label>
                  <label><span>意象</span><input value={imagery} onChange={(event) => setImagery(event.target.value)} /></label>
                  <label><span>情感</span><input value={emotion} onChange={(event) => setEmotion(event.target.value)} /></label>
                </div>
              ) : null}
            </form>

            <div ref={resultsRef} className="knowledge-results" aria-busy={phase === "loading"}>
              <span className="sr-only" role="status" aria-live="polite">
                {phase === "loading" ? "正在检索" : phase === "error" ? error : phase === "success" ? `找到 ${results?.total ?? 0} 条结果` : ""}
              </span>
              {phase === "loading" ? <div className="knowledge-message">正在读取本地索引…</div> : null}
              {phase === "error" ? <div className="knowledge-message is-error"><strong>知识库未就绪</strong><span>{error}</span><code>python tools/build_poetry_knowledge_base.py --rebuild</code></div> : null}
              {phase === "success" && results ? (
                <>
                  <div
                    ref={resultsMetaRef}
                    className="knowledge-result-meta"
                    tabIndex={-1}
                  >
                    <span>
                      {results.total.toLocaleString("zh-CN")}
                      {results.totalRelation === "gte" ? "+" : ""} 条结果
                    </span>
                    {typeof results.elapsedMs === "number" ? <span>{results.elapsedMs.toFixed(1)} ms</span> : null}
                    {results.retrievalMethod ? <span>{results.retrievalMethod === "semantic" ? "语义" : results.retrievalMethod === "hybrid" ? "混合" : "关键词"}</span> : null}
                    {results.degraded ? <span className="is-warning">已降级为关键词</span> : null}
                  </div>
                  {results.degraded ? (
                    <div className="knowledge-degraded" role="status">
                      向量服务暂不可用，当前结果已回退到关键词检索。
                    </div>
                  ) : null}
                  {results.items.length ? (
                    <>
                      <div className="knowledge-result-list">
                        {results.items.map((item, index) => (
                        <button
                          type="button"
                          className="knowledge-result"
                          key={`${item.scope}-${item.lineId ?? item.poemId}-${index}`}
                          onClick={() => void loadPoem(item.poemId, item.lineId)}
                        >
                          <span className="knowledge-result-heading">
                            <strong>{item.title}</strong>
                            <i>{item.scope === "line" ? `第 ${item.lineNo ?? "?"} 句` : "全诗"}</i>
                          </span>
                          <span className="knowledge-byline">{item.dynasty} · {item.poet}</span>
                          <span className="knowledge-snippet">{item.snippet ?? item.text ?? "查看结构化分析"}</span>
                          {typeof item.score === "number" ? <span className="knowledge-score">相关度 {item.score.toFixed(2)}</span> : null}
                          <KnowledgeTags values={[...tagValues(item.imagery), ...tagValues(item.emotions)]} />
                        </button>
                        ))}
                      </div>
                      {(() => {
                        const approximateTotal = results.totalRelation === "gte";
                        const hasNextPage = approximateTotal
                          ? Boolean(results.hasMore)
                          : results.offset + results.limit < results.total;
                        const hasPreviousPage = results.offset > 0;
                        const showPagination = approximateTotal
                          ? hasPreviousPage || hasNextPage
                          : results.total > results.limit;
                        if (!showPagination) return null;
                        return (
                          <nav className="knowledge-pagination" aria-label="知识库结果分页">
                            <button
                              type="button"
                              disabled={!hasPreviousPage}
                              onClick={() => void runSearch(
                                Math.max(0, results.offset - results.limit),
                                "active",
                                true,
                              )}
                            >
                              上一页
                            </button>
                            <span>
                              {approximateTotal
                                ? `第 ${Math.floor(results.offset / results.limit) + 1} 页`
                                : `${Math.floor(results.offset / results.limit) + 1} / ${Math.ceil(results.total / results.limit)}`}
                            </span>
                            <button
                              type="button"
                              disabled={!hasNextPage}
                              onClick={() => void runSearch(
                                results.offset + results.limit,
                                "active",
                                true,
                              )}
                            >
                              下一页
                            </button>
                          </nav>
                        );
                      })()}
                    </>
                  ) : <div className="knowledge-message">没有找到匹配的诗篇或诗句。</div>}
                </>
              ) : null}
            </div>
          </>
        )}
      </section>
    </div>
  );
}

function KnowledgeDetail({
  poem,
  targetLineId,
  onBack,
}: {
  poem: KnowledgePoemPayload;
  targetLineId?: string;
  onBack: () => void;
}) {
  const poemImagery = (poem.imagery ?? []).map(knowledgeTagLabel).filter(Boolean);
  const poemEmotions = (poem.emotions ?? []).map(knowledgeTagLabel).filter(Boolean);
  const poemAnalyses = poem.analyses ?? (
    Array.isArray(poem.analysis) ? poem.analysis : poem.analysis ? [poem.analysis] : []
  );
  const guide = poemAnalyses.find((analysis) => (
    analysis.kind === "poem_guide"
    && (analysis.method === "llm" || analysis.payload?.origin)
    && Boolean(analysis.interpretation ?? analysis.summary)
  ));
  const guideOrigin = typeof guide?.payload?.origin === "string" ? guide.payload.origin : "";
  const guideNote = typeof guide?.payload?.note === "string" ? guide.payload.note : "";
  useEffect(() => {
    if (!targetLineId) return;
    const timer = window.setTimeout(() => {
      const target = document.getElementById(`knowledge-${targetLineId}`);
      const container = target?.closest<HTMLElement>(".knowledge-detail");
      if (target && container) {
        const top = target.offsetTop - (container.clientHeight - target.clientHeight) / 2;
        container.scrollTo({ top: Math.max(0, top), behavior: "smooth" });
      }
      target?.focus({ preventScroll: true });
    }, 0);
    return () => window.clearTimeout(timer);
  }, [targetLineId]);
  return (
    <article className="knowledge-detail">
      <button type="button" className="knowledge-back" onClick={onBack}>
        <ArrowLeft size={16} aria-hidden="true" /> 返回结果
      </button>
      <div className="knowledge-poem-heading">
        <span>{poem.dynasty} · {poem.poet}{poem.school ? ` · ${poem.school}` : ""}</span>
        <h3>{poem.title}</h3>
        <KnowledgeTags values={[...poemImagery, ...poemEmotions]} />
      </div>
      {guide ? (
        <section className="knowledge-guide" aria-labelledby="knowledge-guide-title">
          <div className="knowledge-section-label">
            <BookOpen size={15} aria-hidden="true" />
            <span>先从这里读起</span>
          </div>
          {guide.summary ? <h4 id="knowledge-guide-title">{guide.summary}</h4> : null}
          {guide.interpretation ? <p className="knowledge-guide-body">{guide.interpretation}</p> : null}
          {guideOrigin ? (
            <details className="knowledge-origin">
              <summary>背景，留在诗外的一点线索 <ChevronDown size={14} aria-hidden="true" /></summary>
              <p>{guideOrigin}</p>
            </details>
          ) : null}
        </section>
      ) : null}
      <section className="knowledge-poem" aria-labelledby="knowledge-poem-title">
        <div className="knowledge-section-heading">
          <h4 id="knowledge-poem-title">原诗</h4>
          <span>{poem.lines.length} 句</span>
        </div>
      <div className="knowledge-lines">
        {poem.lines.map((line) => {
          const imagery = (line.imagery ?? []).map(knowledgeTagLabel).filter(Boolean);
          const emotions = (line.emotions ?? []).map(knowledgeTagLabel).filter(Boolean);
          const analyses = line.analyses ?? (Array.isArray(line.analysis) ? line.analysis : line.analysis ? [line.analysis] : []);
          const readings = analyses.filter((analysis) => (
            analysis.method === "llm" && Boolean(analysis.interpretation ?? analysis.summary)
          ));
          const evidence = analyses.filter((analysis) => (
            analysis.method !== "llm" && Boolean(analysis.interpretation ?? analysis.summary)
          ));
          return (
            <section
              key={line.lineId}
              id={`knowledge-${line.lineId}`}
              className={`knowledge-line${line.lineId === targetLineId ? " is-target" : ""}`}
              tabIndex={-1}
            >
              <span className="knowledge-line-no">{String(line.lineNo).padStart(2, "0")}</span>
              <div>
                <p>{line.text}</p>
                <KnowledgeTags values={[...imagery, ...emotions]} />
                {readings.map((analysis, index) => {
                  const content = analysis.interpretation ?? analysis.summary;
                  if (!content) return null;
                  return (
                    <div className="knowledge-line-reading" key={`${analysis.method ?? "reading"}-${index}`}>
                      <span>读到这里</span>
                      <p>{content}</p>
                    </div>
                  );
                })}
                {evidence.length ? (
                  <details className="knowledge-line-evidence">
                    <summary>
                      <span>这句的线索</span>
                      <ChevronDown size={14} aria-hidden="true" />
                    </summary>
                    <div>
                      {evidence.map((analysis, index) => {
                        const content = analysis.interpretation ?? analysis.summary;
                        if (!content) return null;
                        return (
                          <p key={`${analysis.kind ?? "evidence"}-${index}`}>
                            <span>{content}</span>
                            {typeof analysis.confidence === "number" ? (
                              <small>检索信号 · {Math.round(analysis.confidence * 100)}%</small>
                            ) : null}
                          </p>
                        );
                      })}
                    </div>
                  </details>
                ) : null}
              </div>
            </section>
          );
        })}
      </div>
      </section>
      <details className="knowledge-provenance">
        <summary>
          <BookOpen size={15} aria-hidden="true" />
          <span>证据与出处</span>
          <ChevronDown size={14} aria-hidden="true" />
        </summary>
        <div className="knowledge-provenance-content">
          <p>稳定 ID：{poem.poemId}</p>
          {guide?.model ? <p>导读来源：{guide.model}</p> : null}
          {guideNote ? <p>{guideNote}</p> : null}
          {poem.sourceUrl ? <a href={poem.sourceUrl} target="_blank" rel="noreferrer">查看原始来源</a> : null}
        </div>
      </details>
    </article>
  );
}

function KnowledgeTags({ values }: { values: string[] }) {
  const unique = [...new Set(values.filter(Boolean))].slice(0, 8);
  if (!unique.length) return null;
  return <span className="knowledge-tags">{unique.map((value) => <i key={value}>{value}</i>)}</span>;
}

interface PoemKnowledgeSummaryProps {
  poemId?: string | null;
  onOpenKnowledge?: (poemId: string) => void;
  compact?: boolean;
}

export type PoemKnowledgePhase = "idle" | "loading" | "success" | "error";

const poemKnowledgeCache = new Map<string, KnowledgePoemPayload>();
const poemKnowledgeRequests = new Map<string, Promise<KnowledgePoemPayload>>();

function loadPoemKnowledge(poemId: string): Promise<KnowledgePoemPayload> {
  const cached = poemKnowledgeCache.get(poemId);
  if (cached) return Promise.resolve(cached);
  const pending = poemKnowledgeRequests.get(poemId);
  if (pending) return pending;

  const request = fetchKnowledgePoem(poemId)
    .then((response) => {
      if (poemKnowledgeRequests.get(poemId) === request) {
        poemKnowledgeCache.set(poemId, response.payload);
      }
      return response.payload;
    })
    .finally(() => {
      if (poemKnowledgeRequests.get(poemId) === request) {
        poemKnowledgeRequests.delete(poemId);
      }
    });
  poemKnowledgeRequests.set(poemId, request);
  return request;
}

export interface PoemKnowledgeState {
  phase: PoemKnowledgePhase;
  payload?: KnowledgePoemPayload;
  error: string;
  retry: () => void;
}

export function usePoemKnowledge(poemId?: string | null): PoemKnowledgeState {
  const [state, setState] = useState<{
    poemId?: string;
    phase: PoemKnowledgePhase;
    payload?: KnowledgePoemPayload;
    error: string;
  }>({ phase: "idle", error: "" });
  const [retryKey, setRetryKey] = useState(0);

  useEffect(() => {
    if (!poemId) return;

    let cancelled = false;
    void loadPoemKnowledge(poemId)
      .then((nextPayload) => {
        if (cancelled) return;
        setState({ poemId, phase: "success", payload: nextPayload, error: "" });
      })
      .catch((cause) => {
        if (cancelled) return;
        setState({
          poemId,
          phase: "error",
          error: cause instanceof Error ? cause.message : "诗篇知识读取失败",
        });
      });

    return () => {
      cancelled = true;
    };
  }, [poemId, retryKey]);

  return {
    phase: !poemId ? "idle" : state.poemId === poemId ? state.phase : "loading",
    payload: state.poemId === poemId ? state.payload : undefined,
    error: state.poemId === poemId ? state.error : "",
    retry: () => {
      if (poemId) {
        poemKnowledgeCache.delete(poemId);
        poemKnowledgeRequests.delete(poemId);
        setState({ poemId, phase: "loading", error: "" });
      }
      setRetryKey((value) => value + 1);
    },
  };
}

function findPoemGuide(payload: KnowledgePoemPayload): KnowledgeAnalysis | undefined {
  const analyses = payload.analyses ?? (
    Array.isArray(payload.analysis) ? payload.analysis : payload.analysis ? [payload.analysis] : []
  );
  return analyses.find((analysis) => (
    analysis.kind === "poem_guide"
    && Boolean(analysis.interpretation ?? analysis.summary)
  ));
}

export function PoemKnowledgeSummary({ poemId, onOpenKnowledge, compact = false }: PoemKnowledgeSummaryProps) {
  const { phase, payload, error, retry } = usePoemKnowledge(poemId);

  if (!poemId) return null;

  const guide = payload ? findPoemGuide(payload) : undefined;
  if (phase === "loading") {
    return <div className="poem-knowledge-summary is-loading" aria-live="polite">正在取回这首诗的导读…</div>;
  }
  if (phase === "error") {
    return (
      <div className="poem-knowledge-summary is-error" role="status">
        <span>导读暂时没有接上</span>
        <button type="button" onClick={retry}>
          <RotateCw size={13} aria-hidden="true" /> 重试
        </button>
        <small>{error}</small>
      </div>
    );
  }
  if (!guide) {
    return (
      <div className="poem-knowledge-summary is-empty" role="status">
        <span><BookOpen size={15} aria-hidden="true" /> 这首诗的亲笔导读还在整理中</span>
        {onOpenKnowledge ? (
          <button type="button" onClick={() => onOpenKnowledge(poemId)}>查看原诗条目</button>
        ) : null}
      </div>
    );
  }

  return (
    <section
      className={`poem-knowledge-summary${compact ? " is-compact" : ""}`}
      aria-labelledby={`poem-guide-${poemId}`}
    >
      <div className="poem-knowledge-summary-heading">
        <span><BookOpen size={15} aria-hidden="true" /> 读到这里</span>
        {onOpenKnowledge ? (
          <button type="button" onClick={() => onOpenKnowledge(poemId)}>
            打开完整导读
          </button>
        ) : null}
      </div>
      {guide.summary ? <h3 id={`poem-guide-${poemId}`}>{guide.summary}</h3> : null}
      {!compact && guide.interpretation ? <p>{guide.interpretation}</p> : null}
    </section>
  );
}
