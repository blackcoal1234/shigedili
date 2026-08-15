import { ExternalLink, FileCheck2, Fingerprint } from "lucide-react";

import type { PoetryScene, ToolResponse, WorkbenchPayload } from "@/lib/types";

interface EvidencePanelProps {
  response: ToolResponse<WorkbenchPayload>;
  activeScene?: PoetryScene;
  imageryEvidenceCount?: number;
}

export function EvidencePanel({ response, activeScene, imageryEvidenceCount }: EvidencePanelProps) {
  const hashes = Object.entries(response.sourceHashes);
  const evidenceLabel = activeScene?.source_grade
    ? `${activeScene.source_grade} 级`
    : imageryEvidenceCount !== undefined
      ? `语料原句 ${imageryEvidenceCount} 条`
      : "数据集级";

  return (
    <section className="evidence-panel" aria-labelledby="evidence-title">
      <div className="section-heading">
        <div>
          <FileCheck2 size={17} aria-hidden="true" />
          <h2 id="evidence-title">证据与方法</h2>
        </div>
        <span className="evidence-grade">{evidenceLabel}</span>
      </div>

      <div className="evidence-grid">
        <div className="evidence-block">
          <span className="meta-label">状态</span>
          <strong className="status-value" data-status={response.status}>{response.status}</strong>
        </div>
        <div className="evidence-block evidence-source">
          <span className="meta-label">来源</span>
          {activeScene ? (
            <>
              <strong>{activeScene.source_name || "来源名称未记录"}</strong>
              {activeScene.source_url ? (
                <a href={activeScene.source_url} target="_blank" rel="noreferrer">
                  查看原始来源 <ExternalLink size={13} aria-hidden="true" />
                </a>
              ) : <small>source_url insufficient</small>}
            </>
          ) : hashes.length > 0 ? (
            <strong>{hashes.length} 个版本化数据源</strong>
          ) : (
            <small>source_hashes insufficient</small>
          )}
        </div>
        <div className="evidence-block method-block">
          <span className="meta-label">方法</span>
          <p>{response.methodNote || "methodNote insufficient"}</p>
        </div>
      </div>

      <details className="hash-details">
        <summary><Fingerprint size={14} aria-hidden="true" /> 数据指纹</summary>
        <div>
          {hashes.length > 0 ? hashes.map(([path, hash]) => (
            <p key={path}><span>{path}</span><code>{hash}</code></p>
          )) : <p>insufficient</p>}
        </div>
      </details>
    </section>
  );
}
