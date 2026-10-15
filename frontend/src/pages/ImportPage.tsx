/**
 * /imports/:id 识别结果、产品候选、低置信提示、确认入柜。
 * 可修改名称 / 数量 / 匹配目录项；确认走 POST /api/v1/imports/{id}/confirm {items:[...]}。
 * 确认前不会写入任何用户产品实例（spec US-01 / AC01）。
 */

import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { confirmImport, getImport } from "../api/endpoints";
import type { ConfirmImportItem, ImportBatch, ImportCandidate, MatchStatus } from "../api/types";
import { ActionFeedback, AsyncBlock, Badge, EmptyState, KeyValue, Notice, Panel, useToast } from "../components/ui";
import { formatDateTime } from "../lib/format";
import { matchStatusLabel } from "../lib/labels";
import { useAction, useAsync } from "../state/useAsync";
import { useSession } from "../state/SessionContext";

interface EditRow {
  raw_name: string;
  custom_name: string;
  quantity: number;
  size: string;
  match_status: MatchStatus;
  catalog_product_id: string;
  purchase_date: string;
  opened_date: string;
  lifecycle_status: "unopened" | "opened" | "finished" | "discarded" | "unknown";
}

function toRow(candidate: ImportCandidate): EditRow {
  return {
    raw_name: candidate.raw_name,
    custom_name: candidate.matched_name ?? candidate.raw_name,
    quantity: candidate.quantity || 1,
    size: candidate.size ?? "",
    match_status: (candidate.match_status as MatchStatus) ?? "custom",
    catalog_product_id: candidate.catalog_product_id ?? "",
    purchase_date: "",
    opened_date: "",
    lifecycle_status: "unopened",
  };
}

export function ImportPage(): JSX.Element {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const toast = useToast();
  const { refreshMe, refreshContext } = useSession();
  const batch = useAsync<ImportBatch>(() => getImport(id), { deps: [id], enabled: id.length > 0 });
  const [rows, setRows] = useState<EditRow[]>([]);

  useEffect(() => {
    if (batch.data) {
      setRows(batch.data.candidates.map(toRow));
    }
  }, [batch.data]);

  const confirm = useAction<[ConfirmImportItem[]], Awaited<ReturnType<typeof confirmImport>>>((items) =>
    confirmImport(id, items),
  );

  const items = useMemo<ConfirmImportItem[]>(
    () =>
      rows.map((row) => ({
        raw_name: row.raw_name,
        custom_name: row.custom_name || row.raw_name,
        catalog_product_id: row.catalog_product_id || null,
        quantity: row.quantity,
        size: row.size || null,
        match_status: row.match_status,
        purchase_date: row.purchase_date ? new Date(row.purchase_date).toISOString() : null,
        opened_date: row.opened_date ? new Date(row.opened_date).toISOString() : null,
        lifecycle_status: row.lifecycle_status,
      })),
    [rows],
  );

  const submit = async () => {
    const result = await confirm.run(items);
    if (result) {
      toast.show(`已确认入柜：新增 ${result.created.length} 件产品实例。`);
      void refreshMe();
      void refreshContext();
      batch.reload();
    }
  };

  return (
    <div className="stack">
      <Panel
        title="导入识别结果"
        subtitle={`批次 ${id}`}
        actions={
          <>
            <button type="button" onClick={batch.reload}>
              重新读取
            </button>
            <Link className="btn" to="/cabinet">
              返回美妆柜
            </Link>
          </>
        }
      >
        <AsyncBlock
          loading={batch.loading}
          error={batch.error}
          data={batch.data}
          onRetry={batch.reload}
          loadingLabel="加载识别结果…"
        >
          {(data) => (
            <div className="stack">
              <div className="row tight" data-testid="import-status">
                <Badge tone={data.status === "confirmed" ? "ok" : "accent"}>状态：{data.status}</Badge>
                <Badge tone="mock">识别模式：{data.provider_mode}</Badge>
                {data.extractor && <Badge>适配器：{data.extractor}</Badge>}
                {data.low_confidence && <Badge tone="warn">存在低置信候选，请核对</Badge>}
                {data.duplicate_upload && <Badge tone="warn">该文件此前已上传（去重）</Badge>}
              </div>
              {data.error_code && <Badge tone="error">错误码：{data.error_code}</Badge>}
              <Notice tone="mock">{data.notice}</Notice>
              <KeyValue
                items={[
                  ["候选数量", `${data.candidates.length} 件`],
                  ["截图保留", `${data.retention_hours} 小时后按策略删除（file_deleted_at：${formatDateTime(data.file_deleted_at)}）`],
                  ["批次过期", formatDateTime(data.expires_at)],
                  ["确认时间", formatDateTime(data.confirmed_at)],
                  ["已创建产品", data.created_owned_ids.length > 0 ? `${data.created_owned_ids.length} 件` : "尚未创建"],
                ]}
              />
              {data.raw_text && (
                <details>
                  <summary className="small muted">查看识别原始文本（mock 样本内容）</summary>
                  <pre className="mono" style={{ whiteSpace: "pre-wrap" }}>
                    {data.raw_text}
                  </pre>
                </details>
              )}
            </div>
          )}
        </AsyncBlock>
      </Panel>

      <Panel title="产品候选" subtitle="可修改名称、数量与匹配项；确认后才会写入美妆柜">
        <AsyncBlock
          loading={batch.loading}
          error={batch.error}
          data={batch.data}
          onRetry={batch.reload}
          isEmpty={(data) => data.candidates.length === 0}
          empty={
            <div>
              这张图片没有候选。
              <p className="small muted">
                mock 模式只识别内置演示截图样本（data/fixtures/imports/），其他图片不会编造识别结果。
                你可以改用「手动添加产品」。
              </p>
              <Link className="btn" to="/cabinet">
                去手动添加
              </Link>
            </div>
          }
        >
          {(data) => (
            <div className="stack" data-testid="import-candidates">
              {rows.map((row, index) => {
                const candidate = data.candidates[index];
                return (
                  <div
                    className="panel tight stack"
                    key={`${candidate?.raw_name ?? index}-${index}`}
                    data-testid="import-candidate-row"
                    data-index={index}
                  >
                    <div className="row tight" style={{ justifyContent: "space-between" }}>
                      <span style={{ fontWeight: 600 }}>
                        #{index + 1} 识别原文：{candidate?.raw_name}
                      </span>
                      <Badge tone={row.match_status === "matched" ? "ok" : "warn"}>
                        {matchStatusLabel(row.match_status)}
                        {candidate ? ` · 置信度 ${candidate.confidence}` : ""}
                      </Badge>
                    </div>
                    {candidate?.evidence_text && (
                      <div className="small muted">截图证据：{candidate.evidence_text}</div>
                    )}
                    {candidate && candidate.confidence < 0.7 && (
                      <Notice>
                        低置信候选：识别文本与目录匹配度不足，请手动确认名称或匹配项后再入柜（低置信匹配不会
                        自动进入计划）。
                      </Notice>
                    )}
                    <div className="row">
                      <div className="field">
                        <label htmlFor={`name-${index}`}>入柜名称</label>
                        <input
                          id={`name-${index}`}
                          data-testid={`import-candidate-name-${index}`}
                          value={row.custom_name}
                          onChange={(event) =>
                            setRows((prev) =>
                              prev.map((item, i) =>
                                i === index ? { ...item, custom_name: event.target.value } : item,
                              ),
                            )
                          }
                        />
                      </div>
                      <div className="field">
                        <label htmlFor={`qty-${index}`}>数量（1–10）</label>
                        <input
                          id={`qty-${index}`}
                          data-testid={`import-candidate-qty-${index}`}
                          type="number"
                          min={1}
                          max={10}
                          value={row.quantity}
                          onChange={(event) =>
                            setRows((prev) =>
                              prev.map((item, i) =>
                                i === index
                                  ? { ...item, quantity: Math.max(1, Math.min(10, Number(event.target.value) || 1)) }
                                  : item,
                              ),
                            )
                          }
                        />
                      </div>
                      <div className="field">
                        <label htmlFor={`size-${index}`}>规格</label>
                        <input
                          id={`size-${index}`}
                          value={row.size}
                          onChange={(event) =>
                            setRows((prev) =>
                              prev.map((item, i) => (i === index ? { ...item, size: event.target.value } : item)),
                            )
                          }
                        />
                      </div>
                      <div className="field">
                        <label htmlFor={`match-${index}`}>匹配目录项</label>
                        <select
                          id={`match-${index}`}
                          value={row.catalog_product_id}
                          onChange={(event) => {
                            const value = event.target.value;
                            const selected = candidate?.candidates.find(
                              (option) => option.catalog_product_id === value,
                            );
                            setRows((prev) =>
                              prev.map((item, i) =>
                                i === index
                                  ? {
                                      ...item,
                                      catalog_product_id: value,
                                      match_status: value ? "matched" : "custom",
                                      custom_name: selected ? selected.name : item.custom_name,
                                    }
                                  : item,
                              ),
                            );
                          }}
                        >
                          <option value="">（不匹配目录，使用自定义名称）</option>
                          {(candidate?.candidates ?? []).map((option) => (
                            <option key={option.catalog_product_id} value={option.catalog_product_id}>
                              {option.name} · {option.brand ?? "未知品牌"} · {option.size ?? ""}（分数{" "}
                              {option.score}）
                            </option>
                          ))}
                        </select>
                      </div>
                      <div className="field">
                        <label htmlFor={`lifecycle-${index}`}>开封状态</label>
                        <select
                          id={`lifecycle-${index}`}
                          value={row.lifecycle_status}
                          onChange={(event) =>
                            setRows((prev) =>
                              prev.map((item, i) =>
                                i === index
                                  ? { ...item, lifecycle_status: event.target.value as EditRow["lifecycle_status"] }
                                  : item,
                              ),
                            )
                          }
                        >
                          <option value="unopened">未开封</option>
                          <option value="opened">已开封</option>
                          <option value="unknown">未知</option>
                        </select>
                      </div>
                    </div>
                    {candidate && candidate.match_reasons.length > 0 && (
                      <div className="small muted">匹配理由：{candidate.match_reasons.join("；")}</div>
                    )}
                    {candidate?.candidates && candidate.candidates.length > 0 && (
                      <table className="table">
                        <thead>
                          <tr>
                            <th>候选目录项</th>
                            <th>品牌</th>
                            <th>版本</th>
                            <th>分数</th>
                            <th>已审核来源</th>
                            <th>演示</th>
                          </tr>
                        </thead>
                        <tbody>
                          {candidate.candidates.map((option) => (
                            <tr key={option.catalog_product_id}>
                              <td>{option.name}</td>
                              <td>{option.brand ?? "—"}</td>
                              <td>{option.variant ?? option.size ?? "—"}</td>
                              <td>{option.score}</td>
                              <td>{option.has_approved_source ? "有" : "无"}</td>
                              <td>{option.is_demo ? "DEMO" : "真实 SKU"}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    )}
                  </div>
                );
              })}

              {data.status === "confirmed" ? (
                <div className="state">
                  该批次已确认入柜（created {data.created_owned_ids.length} 件）。重复确认不会重复创建。
                  <div className="row tight" style={{ marginTop: 6 }}>
                    <Link className="btn" to="/cabinet">
                      查看美妆柜
                    </Link>
                  </div>
                </div>
              ) : (
                <div className="row tight">
                  <button
                    type="button"
                    className="primary"
                    data-testid="import-confirm"
                    disabled={confirm.running || rows.length === 0}
                    onClick={() => void submit()}
                  >
                    {confirm.running ? "确认中…" : `确认入柜（${items.length} 行，共 ${items.reduce((sum, item) => sum + item.quantity, 0)} 件）`}
                  </button>
                  <span className="small muted">
                    确认请求携带 Idempotency-Key；重复上传同一文件不会重复入柜。
                  </span>
                </div>
              )}
              <ActionFeedback error={confirm.error} />
              {confirm.result && (
                <div className="state">
                  已确认：创建 {confirm.result.created.length} 件产品实例。
                  <ul className="small">
                    {confirm.result.created.map((product) => (
                      <li key={product.id}>
                        <Link to={`/products/${product.id}`}>{product.custom_name}</Link>
                      </li>
                    ))}
                  </ul>
                  <button type="button" className="primary" onClick={() => navigate("/cabinet")}>
                    前往美妆柜
                  </button>
                </div>
              )}
            </div>
          )}
        </AsyncBlock>
      </Panel>

      {batch.data === null && !batch.loading && batch.error === null && (
        <EmptyState>未找到该导入批次。</EmptyState>
      )}
    </div>
  );
}
