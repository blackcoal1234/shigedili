import { AlertTriangle, Database, RefreshCw } from "lucide-react";

export function GalaxyLoader({ label = "正在读取证据" }: { label?: string }) {
  return (
    <div className="state-view" role="status" aria-live="polite">
      <span className="galaxy-loader" aria-hidden="true">
        <i />
        <i />
        <i />
      </span>
      <p>{label}</p>
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="state-view state-error" role="alert">
      <AlertTriangle aria-hidden="true" />
      <div>
        <strong>数据读取中断</strong>
        <p>{message}</p>
      </div>
      <button className="text-button" type="button" onClick={onRetry}>
        <RefreshCw size={15} aria-hidden="true" />
        重试
      </button>
    </div>
  );
}

export function EmptyState({ title = "暂无可显示数据", detail }: { title?: string; detail?: string }) {
  return (
    <div className="state-view">
      <Database aria-hidden="true" />
      <div>
        <strong>{title}</strong>
        {detail ? <p>{detail}</p> : null}
      </div>
    </div>
  );
}

export function InsufficientState({ missingFacts = [] }: { missingFacts?: string[] }) {
  return (
    <div className="insufficient-state" role="status">
      <div className="insufficient-heading">
        <AlertTriangle size={18} aria-hidden="true" />
        <div>
          <span className="status-code">insufficient_evidence</span>
          <h2>现有史料不足以形成行迹</h2>
        </div>
      </div>
      <p>保留作品目录，不从诗题或诗句中的地名推断旅行事实。</p>
      {missingFacts.length > 0 ? (
        <div className="missing-facts" aria-label="缺失事实字段">
          {missingFacts.map((fact) => <code key={fact}>{fact}</code>)}
        </div>
      ) : null}
    </div>
  );
}
