/**
 * 引用（来源）展示组件。
 *
 * 规则（spec 第 8 节 / 8.1.4）：关键建议必须能打开来源；前端不构造 URL，
 * 只展示后端返回的 title/locator/url/file_ref。来源详情通过 GET /sources/{source_id}
 * 拉取（脱敏后返回）。
 */

import { useState } from "react";
import { getSource } from "../api/endpoints";
import type { Citation, SourceDetail } from "../api/types";
import { formatDate } from "../lib/format";
import { useAsync } from "../state/useAsync";
import { AsyncBlock, Badge, ErrorState, Loading, Notice } from "./ui";

export function CitationChips({
  citationIds,
  lookup,
  label = "来源",
}: {
  citationIds: string[];
  lookup?: Map<string, Citation>;
  label?: string;
}): JSX.Element | null {
  const [openId, setOpenId] = useState<string | null>(null);
  if (citationIds.length === 0) {
    return (
      <p className="small muted" style={{ marginTop: 6 }}>
        {label}：后端未为此条目返回引用（无来源支持的结论不会展示）。
      </p>
    );
  }
  const openCitation = openId ? lookup?.get(openId) ?? null : null;
  return (
    <div>
      <div className="chips">
        <span className="small muted" style={{ alignSelf: "center" }}>
          {label}：
        </span>
        {citationIds.map((id) => {
          const citation = lookup?.get(id);
          const isOpen = openId === id;
          return (
            <button
              type="button"
              key={id}
              className={citation?.is_demo ? "chip demo" : "chip"}
              title={citation ? citation.title : `引用 ID：${id}`}
              onClick={() => setOpenId(isOpen ? null : id)}
            >
              {citation ? shortTitle(citation.title) : `引用 #${id.slice(0, 8)}`}
            </button>
          );
        })}
      </div>
      {openId && openCitation && <CitationDetail citation={openCitation} />}
      {openId && !openCitation && (
        <p className="small muted" style={{ marginTop: 6 }}>
          该引用 ID（{openId}）由后端解析，本次响应未附带来源明细；请到对应产品页查看完整来源。
        </p>
      )}
    </div>
  );
}

function shortTitle(title: string): string {
  const cleaned = title.replace(/[《》]/g, "");
  return cleaned.length > 22 ? `${cleaned.slice(0, 22)}…` : cleaned;
}

export function CitationDetail({ citation }: { citation: Citation }): JSX.Element {
  const [showSource, setShowSource] = useState(false);
  return (
    <div className="citation-box">
      <div className="row tight" style={{ justifyContent: "space-between" }}>
        <strong>{citation.title}</strong>
        {citation.is_demo && <Badge tone="mock">DEMO 演示来源</Badge>}
      </div>
      <div className="small muted">
        {citation.locator ? `定位：${citation.locator} · ` : ""}
        来源类型：{citation.source_type ?? "未知"} · 检索时间：{formatDate(citation.retrieved_at)} · 审核时间：
        {formatDate(citation.reviewed_at)}
      </div>
      {citation.excerpt && <p style={{ marginTop: 6 }}>{citation.excerpt}</p>}
      <div className="row tight" style={{ marginTop: 6 }}>
        {citation.url && (
          <a className="btn" href={citation.url} target="_blank" rel="noreferrer noopener">
            打开官方来源
          </a>
        )}
        {citation.file_ref && !citation.url && <span className="mono small">{citation.file_ref}</span>}
        <button type="button" onClick={() => setShowSource((value) => !value)}>
          {showSource ? "收起来源详情" : "查看来源详情"}
        </button>
      </div>
      {showSource && <SourceDetailView sourceId={citation.source_id} />}
    </div>
  );
}

/** GET /sources/{id}：脱敏来源与支持段落。 */
export function SourceDetailView({ sourceId }: { sourceId: string }): JSX.Element {
  const state = useAsync<SourceDetail>(() => getSource(sourceId), { deps: [sourceId] });
  return (
    <div style={{ marginTop: 8 }}>
      <AsyncBlock
        loading={state.loading}
        error={state.error}
        data={state.data}
        onRetry={state.reload}
        loadingLabel="加载来源…"
        empty="未找到该来源。"
      >
        {(source) => (
          <div>
            <div className="row tight">
              <Badge tone={source.status === "approved" ? "ok" : "warn"}>{source.status}</Badge>
              {source.is_demo && <Badge tone="mock">演示来源</Badge>}
              <span className="small muted">{source.publisher ?? "未标注发布方"}</span>
            </div>
            <h4 style={{ marginTop: 6 }}>{source.title}</h4>
            <div className="small muted">
              地区：{source.region ?? "未标注"} · 检索：{formatDate(source.retrieved_at)} · 审核：
              {formatDate(source.reviewed_at)}
            </div>
            {source.approval_note && <p className="small">{source.approval_note}</p>}
            {source.chunks.length === 0 ? (
              <p className="small muted">该来源暂无支持段落。</p>
            ) : (
              <ul className="small">
                {source.chunks.map((chunk) => (
                  <li key={chunk.id}>
                    <span className="muted">{chunk.locator ?? "未标注定位"}</span>：{chunk.text}
                  </li>
                ))}
              </ul>
            )}
            <Notice>{source.notice}</Notice>
          </div>
        )}
      </AsyncBlock>
    </div>
  );
}

/** 简单加载指示（供内联使用）。 */
export function InlineLoading(): JSX.Element {
  return <Loading label="加载中…" />;
}

export function InlineError({
  error,
  onRetry,
}: {
  error: ReturnType<typeof import("../api/client").describeError>;
  onRetry?: () => void;
}): JSX.Element {
  return <ErrorState error={error} onRetry={onRetry} />;
}
