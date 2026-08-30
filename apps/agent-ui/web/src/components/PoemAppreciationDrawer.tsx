"use client";

import {
  BookOpen,
  ExternalLink,
  Languages,
  ListTree,
  LoaderCircle,
  Quote,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  fetchRichGuide,
  generateRichGuide,
  type RichGuideAvailableResponse,
  type RichGuideItem,
  type RichGuideResponse,
} from "@/lib/rich-guide";

export interface AppreciationTarget {
  poemId: string;
  title: string;
  poet: string;
  dynasty: string;
}

interface PoemAppreciationDrawerProps {
  open: boolean;
  target: AppreciationTarget | null;
  onClose: () => void;
}

type GuidePhase = "idle" | "loading" | "ready" | "absent" | "generating" | "error";
type GuideTab = "story" | "translation" | "annotations" | "appreciation" | "evidence";

const GUIDE_TABS: Array<{ id: GuideTab; label: string }> = [
  { id: "story", label: "导读" },
  { id: "translation", label: "逐句译文" },
  { id: "annotations", label: "注释" },
  { id: "appreciation", label: "赏析" },
  { id: "evidence", label: "依据" },
];

function guideErrorMessage(cause: unknown): string {
  const message = cause instanceof Error ? cause.message : "译注赏析请求未完成";
  if (message.includes("missing_env")) {
    return "Agent API 尚未配置模型地址、密钥或模型名；离线动画仍可正常使用。";
  }
  if (message.includes("knowledge_base_missing")) {
    return "诗词知识库尚未构建，暂时无法定位这首诗。";
  }
  if (message.includes("quality_failed")) {
    return "本次模型结果没有通过逐字质量门，请稍后重试。";
  }
  if (message.includes("upstream_error")) {
    return "上游模型暂时没有返回可用结果，请稍后重试。";
  }
  return message;
}

function sourceLabel(response: RichGuideAvailableResponse): string {
  return response.source === "hand" ? "助手撰写 · 非人工考据" : "模型生成 · 非人工考据";
}

function referenceLabel(item: RichGuideItem): string {
  if (item.reference_mode === "reviewed_references") return "经审核摘要约束";
  if (item.reference_mode === "poem_only") return "仅原文约束";
  if (item.reference_mode === "legacy_unconstrained") return "未使用网站证据约束";
  return "助手撰写层";
}

function anchorLabel(item: RichGuideItem): string {
  const labels: Record<string, string> = {
    verified: "已核验作年作地",
    rule: "规则事实锚定",
    ai: "AI 候选事实锚定",
    none: "作年作地待考",
  };
  return labels[item.anchor_tier ?? "none"] ?? "作年作地待考";
}

function tabCount(tab: GuideTab, item: RichGuideItem): number {
  if (tab === "story") return item.story.trim() ? 1 : 0;
  if (tab === "translation") return item.notes.filter((note) => note.translation.trim()).length;
  if (tab === "annotations") {
    return item.notes.reduce((sum, note) => sum + note.annotations.length, 0);
  }
  if (tab === "appreciation") return item.ap.length;
  return item.sources.length;
}

export function PoemAppreciationDrawer({
  open,
  target,
  onClose,
}: PoemAppreciationDrawerProps) {
  const [phase, setPhase] = useState<GuidePhase>("idle");
  const [response, setResponse] = useState<RichGuideResponse>();
  const [error, setError] = useState("");
  const [activeTab, setActiveTab] = useState<GuideTab>("appreciation");
  const abortRef = useRef<AbortController | null>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const openerRef = useRef<HTMLElement | null>(null);
  const requestSequence = useRef(0);
  const poemId = target?.poemId;

  const loadGuide = useCallback(async () => {
    if (!poemId) return;
    abortRef.current?.abort();
    const controller = new AbortController();
    const requestId = ++requestSequence.current;
    abortRef.current = controller;
    setPhase("loading");
    setResponse(undefined);
    setError("");
    try {
      const next = await fetchRichGuide(poemId, controller.signal);
      if (requestId !== requestSequence.current) return;
      setResponse(next);
      setPhase(next.status === "absent" ? "absent" : "ready");
    } catch (cause) {
      if (controller.signal.aborted || requestId !== requestSequence.current) return;
      setPhase("error");
      setError(guideErrorMessage(cause));
    }
  }, [poemId]);

  useEffect(() => {
    if (!open || !poemId) return;
    const timer = window.setTimeout(() => {
      setActiveTab("appreciation");
      void loadGuide();
    }, 0);
    return () => {
      window.clearTimeout(timer);
      abortRef.current?.abort();
    };
  }, [loadGuide, open, poemId]);

  useEffect(() => {
    if (!open) return;
    openerRef.current = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const focusTimer = window.setTimeout(() => closeRef.current?.focus(), 0);
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== "Tab") return;
      const dialog = closeRef.current?.closest<HTMLElement>("[role=dialog]");
      const focusable = dialog?.querySelectorAll<HTMLElement>(
        "button:not([disabled]), a[href], summary",
      );
      if (!focusable?.length) return;
      const first = focusable[0];
      if (!first) return;
      const last = focusable[focusable.length - 1] ?? first;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      window.clearTimeout(focusTimer);
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
      openerRef.current?.focus();
    };
  }, [onClose, open]);

  const generate = async () => {
    if (!poemId) return;
    abortRef.current?.abort();
    const controller = new AbortController();
    const requestId = ++requestSequence.current;
    abortRef.current = controller;
    setPhase("generating");
    setError("");
    try {
      const next = await generateRichGuide(poemId, controller.signal);
      if (requestId !== requestSequence.current) return;
      setResponse(next);
      setPhase(next.status === "absent" ? "absent" : "ready");
      setActiveTab("appreciation");
    } catch (cause) {
      if (controller.signal.aborted || requestId !== requestSequence.current) return;
      setPhase("error");
      setError(guideErrorMessage(cause));
    }
  };

  const availableResponse = response?.status === "exists" || response?.status === "generated"
    ? response
    : undefined;
  const item = availableResponse?.item;
  const counts = useMemo(() => {
    if (!item) return new Map<GuideTab, number>();
    return new Map(GUIDE_TABS.map((tab) => [tab.id, tabCount(tab.id, item)]));
  }, [item]);

  if (!open || !target) return null;

  return (
    <div className="appreciation-overlay" data-testid="appreciation-overlay">
      <button
        type="button"
        className="appreciation-scrim"
        aria-label="关闭译注赏析"
        onClick={onClose}
      />
      <section
        className="appreciation-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="appreciation-title"
      >
        <header className="appreciation-header">
          <div>
            <span className="workspace-kicker">诗词 · 译注 · 赏析</span>
            <h2 id="appreciation-title">译注赏析</h2>
          </div>
          <button
            ref={closeRef}
            type="button"
            className="icon-command"
            onClick={onClose}
            aria-label="关闭译注赏析"
          >
            <X size={19} aria-hidden="true" />
          </button>
        </header>

        <div className="appreciation-poem-heading">
          <span>{target.dynasty} · {target.poet}</span>
          <h3>《{target.title}》</h3>
          {item && availableResponse ? (
            <div className="appreciation-badges" aria-label="内容状态">
              <i><BookOpen size={13} aria-hidden="true" />{sourceLabel(availableResponse)}</i>
              <i data-tone="evidence"><ShieldCheck size={13} aria-hidden="true" />{referenceLabel(item)}</i>
            </div>
          ) : null}
        </div>

        {item ? (
          <nav className="appreciation-tabs" role="tablist" aria-label="译注赏析章节">
            {GUIDE_TABS.map((tab) => (
              <button
                key={tab.id}
                type="button"
                role="tab"
                aria-selected={activeTab === tab.id}
                data-active={activeTab === tab.id}
                onClick={() => setActiveTab(tab.id)}
              >
                <span>{tab.label}</span>
                <small>{counts.get(tab.id) ?? 0}</small>
              </button>
            ))}
          </nav>
        ) : null}

        <div className="appreciation-body" aria-live="polite">
          {phase === "loading" ? <GuideLoading label="正在读取这首诗的译注赏析" /> : null}
          {phase === "generating" ? <GuideLoading label="模型正在逐句生成并执行质量校验" /> : null}
          {phase === "absent" ? (
            <GuideEmpty onGenerate={() => void generate()} />
          ) : null}
          {phase === "error" ? (
            <GuideError
              message={error}
              onRetry={() => void loadGuide()}
              onGenerate={() => void generate()}
            />
          ) : null}
          {phase === "ready" && item && availableResponse ? (
            <GuideCards tab={activeTab} item={item} response={availableResponse} />
          ) : null}
        </div>

        <footer className="appreciation-footer">
          <span>关闭后仍停留在当前动画镜头</span>
          <button type="button" onClick={onClose}>返回动画</button>
        </footer>
      </section>
    </div>
  );
}

function GuideLoading({ label }: { label: string }) {
  return (
    <div className="appreciation-loading" role="status">
      <LoaderCircle className="spin" size={20} aria-hidden="true" />
      <strong>{label}</strong>
      <div className="appreciation-skeleton-grid" aria-hidden="true">
        <i /><i /><i />
      </div>
    </div>
  );
}

function GuideEmpty({ onGenerate }: { onGenerate: () => void }) {
  return (
    <article className="appreciation-state-card">
      <Sparkles size={23} aria-hidden="true" />
      <span>按需生成</span>
      <h3>这首诗还没有完整译注赏析</h3>
      <p>可调用本机 Agent API 生成背景导读、逐句译文、注释和赏析要点；结果通过原句逐字质量门后才会展示。</p>
      <button type="button" className="appreciation-primary" onClick={onGenerate}>
        <Sparkles size={16} aria-hidden="true" /> 在线生成译注赏析
      </button>
    </article>
  );
}

function GuideError({
  message,
  onRetry,
  onGenerate,
}: {
  message: string;
  onRetry: () => void;
  onGenerate: () => void;
}) {
  const generationUnavailable = message.includes("尚未配置模型");
  return (
    <article className="appreciation-state-card is-error" role="status">
      <RefreshCw size={22} aria-hidden="true" />
      <span>暂时不可用</span>
      <h3>译注赏析没有接上</h3>
      <p>{message}</p>
      <div className="appreciation-state-actions">
        <button type="button" onClick={onRetry}>重新查询</button>
        {!generationUnavailable ? (
          <button type="button" className="appreciation-primary" onClick={onGenerate}>重新生成</button>
        ) : null}
      </div>
    </article>
  );
}

function GuideCards({
  tab,
  item,
  response,
}: {
  tab: GuideTab;
  item: RichGuideItem;
  response: RichGuideAvailableResponse;
}) {
  if (tab === "story") {
    return item.story.trim() ? (
      <section className="guide-card-grid is-single" aria-label="导读">
        <article className="guide-card guide-story-card">
          <span className="guide-card-kicker"><BookOpen size={14} aria-hidden="true" />背景导读</span>
          <p>{item.story}</p>
        </article>
      </section>
    ) : <GuideSectionEmpty label="导读" />;
  }

  if (tab === "translation") {
    const notes = item.notes.filter((note) => note.translation.trim());
    return notes.length ? (
      <section className="guide-card-grid" aria-label="逐句译文">
        {notes.map((note, index) => (
          <article className="guide-card guide-line-card" key={`${note.original}-${index}`}>
            <span className="guide-card-index">{String(index + 1).padStart(2, "0")}</span>
            <blockquote>{note.original}</blockquote>
            <p><Languages size={14} aria-hidden="true" />{note.translation}</p>
          </article>
        ))}
      </section>
    ) : <GuideSectionEmpty label="逐句译文" />;
  }

  if (tab === "annotations") {
    const annotations = item.notes.flatMap((note) => (
      note.annotations.map((annotation) => ({ original: note.original, annotation }))
    ));
    return annotations.length ? (
      <section className="guide-card-grid" aria-label="注释">
        {annotations.map((note, index) => (
          <article className="guide-card guide-note-card" key={`${note.original}-${index}`}>
            <span className="guide-card-kicker"><ListTree size={14} aria-hidden="true" />注释 {String(index + 1).padStart(2, "0")}</span>
            <blockquote>{note.original}</blockquote>
            <p>{note.annotation}</p>
          </article>
        ))}
      </section>
    ) : <GuideSectionEmpty label="注释" />;
  }

  if (tab === "appreciation") {
    return item.ap.length ? (
      <section className="guide-card-grid" aria-label="赏析要点">
        {item.ap.map((point, index) => (
          <article className="guide-card guide-appreciation-card" key={`${point}-${index}`}>
            <span className="guide-card-index">{String(index + 1).padStart(2, "0")}</span>
            <div>
              <span className="guide-card-kicker"><Quote size={14} aria-hidden="true" />赏析要点</span>
              <p>{point}</p>
            </div>
          </article>
        ))}
      </section>
    ) : <GuideSectionEmpty label="赏析" />;
  }

  return (
    <section className="guide-card-grid" aria-label="依据与来源">
      <article className="guide-card guide-evidence-card">
        <span className="guide-card-kicker"><ShieldCheck size={14} aria-hidden="true" />内容边界</span>
        <dl>
          <div><dt>内容层</dt><dd>{sourceLabel(response)}</dd></div>
          <div><dt>外部依据</dt><dd>{referenceLabel(item)}</dd></div>
          <div><dt>事实锚定</dt><dd>{anchorLabel(item)}</dd></div>
          {response.batch ? <div><dt>数据批次</dt><dd>{response.batch}</dd></div> : null}
        </dl>
      </article>
      {item.sources.map((source) => (
        <article className="guide-card guide-source-card" key={source.reference_id}>
          <span className="guide-card-index">{source.reference_id}</span>
          <h4>{source.name}</h4>
          <a href={source.url} target="_blank" rel="noreferrer">
            查看来源 <ExternalLink size={13} aria-hidden="true" />
          </a>
        </article>
      ))}
      {!item.sources.length ? (
        <article className="guide-card guide-source-card is-muted">
          <span className="guide-card-kicker"><ShieldCheck size={14} aria-hidden="true" />来源说明</span>
          <p>本条未公开外部来源链接；请以当前约束徽章为准，不把模型文字当作人工考据结论。</p>
        </article>
      ) : null}
    </section>
  );
}

function GuideSectionEmpty({ label }: { label: string }) {
  return (
    <article className="appreciation-state-card is-quiet">
      <BookOpen size={20} aria-hidden="true" />
      <h3>暂未提供{label}</h3>
      <p>当前条目没有这一部分内容，其他章节仍可继续阅读。</p>
    </article>
  );
}
