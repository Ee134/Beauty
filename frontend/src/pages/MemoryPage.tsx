/**
 * /memory 记忆：当前偏好、用户报告、来源、修改/删除。
 * 修改会生成新版本（旧值只在历史显示）；删除会同步失效派生摘要与图鉴信号。
 */

import { useState } from "react";
import { Link } from "react-router-dom";
import {
  createUsageEvent,
  deleteIngredientFeedback,
  deleteMemory,
  deleteUsageEvent,
  listIngredientFeedback,
  listMemories,
  listUsageEvents,
  updateMemory,
} from "../api/endpoints";
import type { MemoryRecord, UsageEventRecord } from "../api/types";
import {
  ActionFeedback,
  AsyncBlock,
  Badge,
  Notice,
  Panel,
  useToast,
} from "../components/ui";
import { formatDateTime, formatValue } from "../lib/format";
import { useAction, useAsync } from "../state/useAsync";
import { useSession } from "../state/SessionContext";

const KIND_LABELS: Record<string, string> = {
  explicit_preference: "用户明确偏好",
  preference: "偏好",
  user_report: "用户报告事件",
  fact: "业务事实",
  correction: "修正",
  pending_confirmation: "待确认（模型推测）",
  pending: "待确认",
};

export function MemoryPage(): JSX.Element {
  const toast = useToast();
  const { refreshContext, lastLoadedAt } = useSession();
  const memories = useAsync(() => listMemories({ include_history: true }), { deps: [lastLoadedAt] });
  const events = useAsync(() => listUsageEvents(), { deps: [lastLoadedAt] });
  const ingredientFeedback = useAsync(() => listIngredientFeedback(), { deps: [lastLoadedAt] });

  const [newText, setNewText] = useState("");
  const [newType, setNewType] = useState<"positive" | "negative" | "neutral" | "uncertain">("neutral");
  const createEvent = useAction(() =>
    createUsageEvent({ reported_text: newText, time_precision: "unknown", event_type: newType }),
  );
  const removeEvent = useAction<[string], Awaited<ReturnType<typeof deleteUsageEvent>>>((id) =>
    deleteUsageEvent(id),
  );
  const removeFeedback = useAction<[string], Awaited<ReturnType<typeof deleteIngredientFeedback>>>((id) =>
    deleteIngredientFeedback(id),
  );

  const refresh = () => {
    memories.reload();
    events.reload();
    ingredientFeedback.reload();
    void refreshContext();
  };

  const records = memories.data?.records ?? [];
  const byKind = new Map<string, MemoryRecord[]>();
  for (const record of records) {
    const list = byKind.get(record.kind) ?? [];
    list.push(record);
    byKind.set(record.kind, list);
  }

  return (
    <div className="stack">
      <Panel
        title="记忆与反馈"
        subtitle="有效偏好、用户报告与来源；模型推测只以待确认形式存在"
        actions={
          <button type="button" onClick={refresh}>
            刷新
          </button>
        }
      >
        <Notice>{memories.data?.notice}</Notice>
        <Notice>
          删除记忆会同步遮盖关联原文、失效派生摘要与图鉴信号（重启后仍保持）；删除审计不保留内容。
        </Notice>
      </Panel>

      <Panel title="新增用户报告" subtitle="POST /api/v1/usage-events（发生时间允许未知）">
        <div className="row">
          <div className="field" style={{ flex: 1, minWidth: 240 }}>
            <label htmlFor="mem-text">我报告的体验 *</label>
            <input
              id="mem-text"
              value={newText}
              onChange={(event) => setNewText(event.target.value)}
              placeholder="例如：换了新产品后感觉有点干"
            />
          </div>
          <div className="field">
            <label htmlFor="mem-type">类型</label>
            <select
              id="mem-type"
              value={newType}
              onChange={(event) => setNewType(event.target.value as typeof newType)}
            >
              <option value="neutral">无明显变化</option>
              <option value="positive">正面体验</option>
              <option value="negative">负面体验</option>
              <option value="uncertain">不确定</option>
            </select>
          </div>
          <button
            type="button"
            className="primary"
            disabled={createEvent.running || newText.trim().length === 0}
            onClick={() => {
              void (async () => {
                const result = await createEvent.run();
                if (result) {
                  toast.show(result.notice);
                  setNewText("");
                  refresh();
                }
              })();
            }}
          >
            {createEvent.running ? "保存中…" : "保存为用户报告"}
          </button>
        </div>
        <ActionFeedback error={createEvent.error} />
      </Panel>

      <Panel title="当前偏好与其他记忆" subtitle="按 kind 分组；历史版本只读">
        <AsyncBlock
          loading={memories.loading}
          error={memories.error}
          data={memories.data}
          onRetry={memories.reload}
          isEmpty={(data) => data.records.length === 0}
          empty="还没有任何记忆记录。"
        >
          {() => (
            <div className="stack" data-testid="memory-list">
              {[...byKind.entries()].map(([kind, list]) => (
                <div key={kind}>
                  <div className="panel-sub">
                    {KIND_LABELS[kind] ?? kind} · {list.length} 条
                  </div>
                  <table className="table">
                    <thead>
                      <tr>
                        <th>key</th>
                        <th>值</th>
                        <th>状态</th>
                        <th>来源类型 / 原文</th>
                        <th>有效期</th>
                        <th>版本</th>
                        <th>操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {list.map((record) => (
                        <MemoryRow key={record.id} record={record} onChanged={refresh} />
                      ))}
                    </tbody>
                  </table>
                </div>
              ))}
            </div>
          )}
        </AsyncBlock>
      </Panel>

      <Panel title="用户报告事件" subtitle="这些是你报告的体验，不是诊断结论">
        <AsyncBlock
          loading={events.loading}
          error={events.error}
          data={events.data}
          onRetry={events.reload}
          isEmpty={(data) => data.events.length === 0}
          empty="还没有用户报告事件。"
        >
          {(data) => (
            <div className="stack">
              <ul className="stack" style={{ listStyle: "none", padding: 0 }}>
                {data.events.map((event: UsageEventRecord) => (
                  <li className="step" key={event.id} data-testid="usage-event-row" data-event-id={event.id}>
                    <div className="row tight" style={{ justifyContent: "space-between" }}>
                      <span>
                        <Badge tone={event.event_type === "negative" ? "warn" : "ok"}>
                          {event.event_type ?? "未标注"}
                        </Badge>{" "}
                        {event.reported_text}
                      </span>
                      <button
                        type="button"
                        className="danger"
                        data-testid="usage-event-delete"
                        disabled={removeEvent.running}
                        onClick={() => {
                          void (async () => {
                            const result = await removeEvent.run(event.id);
                            if (result) {
                              toast.show(result.notice);
                              refresh();
                            }
                          })();
                        }}
                      >
                        删除并失效派生信号
                      </button>
                    </div>
                    <div className="small muted">
                      发生时间：{formatDateTime(event.occurred_at)}（{event.time_precision}） · provenance：
                      {event.provenance} · 关联产品 {event.owned_product_ids.length} 件
                    </div>
                    <div className="notice">{event.disclaimer}</div>
                  </li>
                ))}
              </ul>
              <ActionFeedback error={removeEvent.error} />
              <Notice>{data.notice}</Notice>
            </div>
          )}
        </AsyncBlock>
      </Panel>

      <Panel
        title="成分补充陈述"
        subtitle="你在图鉴页对某成分的明确陈述；与统计信号分开显示"
        actions={
          <Link className="btn" to="/ingredients/atlas">
            到图鉴补充陈述
          </Link>
        }
      >
        <AsyncBlock
          loading={ingredientFeedback.loading}
          error={ingredientFeedback.error}
          data={ingredientFeedback.data}
          onRetry={ingredientFeedback.reload}
          isEmpty={(data) => data.records.length === 0}
          empty="还没有成分补充陈述。"
        >
          {(data) => (
            <div className="stack">
              {data.records.map((record) => (
                <div className="step" key={record.id}>
                  <div className="row tight" style={{ justifyContent: "space-between" }}>
                    <span>
                      {record.statement}
                      <span className="small muted"> · 成分 {record.ingredient_id.slice(0, 8)}</span>
                    </span>
                    <button
                      type="button"
                      className="danger"
                      disabled={removeFeedback.running}
                      onClick={() => {
                        void (async () => {
                          const result = await removeFeedback.run(record.id);
                          if (result) {
                            toast.show("已删除该陈述，图鉴将重新生成。");
                            refresh();
                          }
                        })();
                      }}
                    >
                      删除
                    </button>
                  </div>
                </div>
              ))}
              <ActionFeedback error={removeFeedback.error} />
              <Notice>这是你本人的明确陈述，会与统计信号分开显示，不作为因果结论。</Notice>
            </div>
          )}
        </AsyncBlock>
      </Panel>
    </div>
  );
}

function MemoryRow({ record, onChanged }: { record: MemoryRecord; onChanged: () => void }): JSX.Element {
  const toast = useToast();
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(formatValue(record.value));
  const update = useAction<[], Awaited<ReturnType<typeof updateMemory>>>((..._args) =>
    updateMemory(record.id, { value: coerce(value), expected_version: record.version }),
  );
  const remove = useAction(() => deleteMemory(record.id));

  return (
    <tr data-testid="memory-record" data-key={record.key} data-status={record.status}>
      <td className="mono">{record.key}</td>
      <td>
        {editing ? (
          <input
            data-testid="memory-edit-value"
            value={value}
            onChange={(event) => setValue(event.target.value)}
          />
        ) : (
          formatValue(record.value)
        )}
      </td>
      <td>
        <Badge tone={record.status === "active" ? "ok" : "warn"}>{record.status}</Badge>
        {record.is_current ? "" : "（历史）"}
      </td>
      <td className="small muted">
        {record.provenance_type ?? "—"}
        {record.source_excerpt ? (
          <div className="small muted">原文：{record.source_excerpt}</div>
        ) : (
          <div className="small muted">无关联原文</div>
        )}
        {record.supersedes_id && <div className="mono small">supersedes {record.supersedes_id.slice(0, 8)}</div>}
      </td>
      <td className="small muted">
        {formatDateTime(record.valid_from)} → {record.valid_to ? formatDateTime(record.valid_to) : "有效"}
      </td>
      <td>v{record.version}</td>
      <td>
        <div className="row tight">
          {editing ? (
            <>
              <button
                type="button"
                className="primary"
                data-testid="memory-edit-save"
                disabled={update.running}
                onClick={() => {
                  void (async () => {
                    const result = await update.run();
                    if (result) {
                      toast.show(result.notice);
                      setEditing(false);
                      onChanged();
                    }
                  })();
                }}
              >
                保存
              </button>
              <button type="button" onClick={() => setEditing(false)}>
                取消
              </button>
            </>
          ) : (
            <button type="button" data-testid={`memory-edit-${record.key}`} onClick={() => setEditing(true)}>
              修改
            </button>
          )}
          <button
            type="button"
            className="danger"
            data-testid={`memory-delete-${record.key}`}
            disabled={remove.running}
            onClick={() => {
              void (async () => {
                const result = await remove.run();
                if (result) {
                  toast.show(result.notice);
                  onChanged();
                }
              })();
            }}
          >
            删除
          </button>
        </div>
        <ActionFeedback error={update.error} />
        <ActionFeedback error={remove.error} />
      </td>
    </tr>
  );
}

/** 简单类型还原：能解析成数字/布尔就转，其余保持字符串。 */
function coerce(raw: string): unknown {
  const trimmed = raw.trim();
  if (trimmed === "true") {
    return true;
  }
  if (trimmed === "false") {
    return false;
  }
  if (trimmed !== "" && !Number.isNaN(Number(trimmed))) {
    return Number(trimmed);
  }
  return raw;
}
