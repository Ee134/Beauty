/**
 * /service 工单与处理时间线。
 * 交接流程：/handoffs/candidates 选择记录 -> /handoffs/drafts 生成预览草稿
 * -> 用户确认后 /handoffs/{id}/submit 提交到本地演示工作台（不称品牌已收到）。
 */

import { useState } from "react";
import {
  confirmResolution,
  createHandoffDraft,
  getHandoffCandidates,
  getTicket,
  listTickets,
  submitHandoff,
} from "../api/endpoints";
import type { ServiceTicket } from "../api/types";
import {
  ActionFeedback,
  AsyncBlock,
  Badge,
  EmptyState,
  KeyValue,
  Notice,
  Panel,
  useToast,
} from "../components/ui";
import { formatDateTime } from "../lib/format";
import { ticketStatusLabel } from "../lib/labels";
import { useAction, useAsync } from "../state/useAsync";
import { useSession } from "../state/SessionContext";

export function ServicePage(): JSX.Element {
  const toast = useToast();
  const { refreshContext, lastLoadedAt } = useSession();
  const tickets = useAsync(() => listTickets(), { deps: [lastLoadedAt] });
  const candidates = useAsync(() => getHandoffCandidates(), { deps: [lastLoadedAt] });
  const [selected, setSelected] = useState<string[]>([]);
  const [request, setRequest] = useState("");
  const [openTicketId, setOpenTicketId] = useState<string | null>(null);
  const [draftTicket, setDraftTicket] = useState<ServiceTicket | null>(null);

  const draft = useAction(() =>
    createHandoffDraft({ record_ids: selected, request: request.trim() }),
  );
  const submit = useAction<[string, number | null, string[]], Awaited<ReturnType<typeof submitHandoff>>>(
    (ticketId, version, recordIds) =>
      submitHandoff(ticketId, { expected_version: version, included_record_ids: recordIds }),
  );

  const refresh = () => {
    tickets.reload();
    candidates.reload();
    void refreshContext();
  };

  return (
    <div className="stack">
      <Panel
        title="客服交接与工单"
        subtitle="状态来自本地演示工作台；提交不等于任何品牌已收到"
        actions={
          <button type="button" onClick={refresh}>
            刷新
          </button>
        }
      >
        <Notice>
          模拟提交只说明已进入本地演示工作台（adapter_mode=local_demo）；工单是否解决以你的确认为准，不用客服
          状态自动认定解决率。
        </Notice>
      </Panel>

      <Panel title="1. 选择要包含的记录" subtitle="GET /handoffs/candidates（默认不包含任何记录）">
        <AsyncBlock
          loading={candidates.loading}
          error={candidates.error}
          data={candidates.data}
          onRetry={candidates.reload}
          isEmpty={(data) => data.records.length === 0}
          empty="暂无可用于交接的记录（没有反馈事件或产品时可先记录反馈）。"
        >
          {(data) => (
            <div className="stack">
              <div className="row tight">
                <button type="button" onClick={() => setSelected(data.records.map((record) => record.id))}>
                  全选
                </button>
                <button type="button" onClick={() => setSelected([])}>
                  清空
                </button>
                <span className="small muted">已选 {selected.length} 条</span>
              </div>
              <ul className="stack" data-testid="handoff-candidates" style={{ listStyle: "none", padding: 0 }}>
                {data.records.map((record) => (
                  <li key={record.id} className="step">
                    <label style={{ display: "flex", gap: 8, alignItems: "flex-start", fontSize: 13 }}>
                      <input
                        type="checkbox"
                        data-testid="handoff-candidate-checkbox"
                        data-record-id={record.id}
                        checked={selected.includes(record.id)}
                        onChange={(event) =>
                          setSelected((prev) =>
                            event.target.checked
                              ? [...prev, record.id]
                              : prev.filter((id) => id !== record.id),
                          )
                        }
                      />
                      <span>
                        <Badge>{record.type}</Badge> {record.label}
                        <span className="small muted">
                          {" "}
                          · {record.occurred_at ? formatDateTime(record.occurred_at) : "时间未知"}
                        </span>
                      </span>
                    </label>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </AsyncBlock>
      </Panel>

      <Panel title="2. 生成交接预览草稿" subtitle="POST /handoffs/drafts（不产生任何工单状态变化）">
        <div className="row">
          <div className="field" style={{ flex: 1, minWidth: 260 }}>
            <label htmlFor="handoff-request">我的诉求 *</label>
            <input
              id="handoff-request"
              data-testid="handoff-request-input"
              value={request}
              onChange={(event) => setRequest(event.target.value)}
              placeholder="例如：上周用某精华后持续刺痛，希望确认下一步怎么处理"
            />
          </div>
          <button
            type="button"
            className="primary"
            data-testid="handoff-preview-button"
            disabled={draft.running || request.trim().length === 0 || selected.length === 0}
            onClick={() => {
              void (async () => {
                const result = await draft.run();
                if (result) {
                  setDraftTicket(result.ticket);
                  toast.show(result.notice);
                }
              })();
            }}
          >
            {draft.running ? "生成中…" : "生成预览草稿"}
          </button>
        </div>
        {selected.length === 0 && (
          <p className="small muted">
            请先在上一步勾选至少一条要包含的记录：服务端要求 record_ids 非空（否则返回 422
            VALIDATION_ERROR「请至少选择一条要包含的记录」）。
          </p>
        )}
        <ActionFeedback error={draft.error} />
        {draftTicket && (
          <div className="stack" data-testid="handoff-preview" style={{ marginTop: 10 }}>
            <TicketView ticket={draftTicket} statusTestId="handoff-preview-status" />
            <div className="row tight">
              <button
                type="button"
                className="primary"
                data-testid="handoff-submit"
                disabled={submit.running}
                onClick={() => {
                  void (async () => {
                    const result = await submit.run(draftTicket.id, draftTicket.version, selected);
                    if (result) {
                      toast.show(result.notice);
                      setDraftTicket(result.ticket);
                      refresh();
                    }
                  })();
                }}
              >
                {submit.running ? "提交中…" : "确认提交到本地演示工作台"}
              </button>
              <span className="small muted">
                提交前不会出现 submitted 工单；重复提交由幂等键去重。
              </span>
            </div>
            <ActionFeedback error={submit.error} />
          </div>
        )}
      </Panel>

      <Panel title="我的工单" subtitle="GET /tickets（状态与时间线）">
        <AsyncBlock
          loading={tickets.loading}
          error={tickets.error}
          data={tickets.data}
          onRetry={tickets.reload}
          isEmpty={(data) => data.tickets.length === 0}
          empty="还没有工单。先按上面的步骤生成预览并确认提交。"
        >
          {(data) => (
            <div className="stack">
              <table className="table">
                <thead>
                  <tr>
                    <th>工单</th>
                    <th>状态</th>
                    <th>适配器</th>
                    <th>提交时间</th>
                    <th>用户确认解决</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {data.tickets.map((ticket) => (
                    <tr key={ticket.id}>
                      <td className="mono">{ticket.id.slice(0, 8)}</td>
                      <td>
                        {/* 工单列表也带 ticket-status，E2E 不必先打开详情 */}
                        <span data-testid="ticket-status">
                          <Badge tone={ticket.status === "resolved" ? "ok" : "accent"}>
                            {ticketStatusLabel(ticket.status)}
                          </Badge>
                        </span>
                      </td>
                      <td>{ticket.adapter_mode}</td>
                      <td>{formatDateTime(ticket.submitted_at)}</td>
                      <td>{ticket.user_confirmed_resolution === null ? "未确认" : ticket.user_confirmed_resolution ? "已确认为已解决" : "确认为未解决"}</td>
                      <td>
                        <button type="button" onClick={() => setOpenTicketId(ticket.id)}>
                          查看时间线
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <Notice>{data.notice}</Notice>
            </div>
          )}
        </AsyncBlock>
      </Panel>

      {openTicketId && (
        <Panel
          title={`工单详情 ${openTicketId.slice(0, 8)}`}
          subtitle="GET /tickets/{id}"
          actions={
            <button type="button" onClick={() => setOpenTicketId(null)}>
              关闭
            </button>
          }
        >
          <TicketDetail ticketId={openTicketId} onChanged={refresh} />
        </Panel>
      )}
    </div>
  );
}

function TicketDetail({ ticketId, onChanged }: { ticketId: string; onChanged: () => void }): JSX.Element {
  const toast = useToast();
  const ticket = useAsync(() => getTicket(ticketId), { deps: [ticketId] });
  const resolution = useAction<[boolean], Awaited<ReturnType<typeof confirmResolution>>>((resolved) =>
    confirmResolution(ticketId, resolved),
  );

  return (
    <AsyncBlock
      loading={ticket.loading}
      error={ticket.error}
      data={ticket.data}
      onRetry={ticket.reload}
      loadingLabel="加载工单…"
    >
      {(data) => (
        <div className="stack">
          <TicketView ticket={data.ticket} />
          <div>
            <div className="panel-sub">处理时间线</div>
            {(data.ticket.timeline ?? []).length === 0 ? (
              <EmptyState>暂无时间线记录。</EmptyState>
            ) : (
              <ul className="small" data-testid="ticket-timeline">
                {(data.ticket.timeline ?? []).map((entry) => (
                  <li key={entry.id}>
                    {formatDateTime(entry.at)} · {entry.actor_role ?? "system"} · {entry.action}
                    {entry.from_status || entry.to_status
                      ? `（${entry.from_status ?? "—"} → ${entry.to_status ?? "—"}）`
                      : ""}
                    {entry.note ? ` · ${entry.note}` : ""}
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div className="row tight">
            <span className="small muted">你认为这个问题解决了吗？（独立于客服状态存储）</span>
            <button
              type="button"
              disabled={resolution.running}
              onClick={() => {
                void (async () => {
                  const result = await resolution.run(true);
                  if (result) {
                    toast.show(result.notice);
                    ticket.reload();
                    onChanged();
                  }
                })();
              }}
            >
              已解决
            </button>
            <button
              type="button"
              disabled={resolution.running}
              onClick={() => {
                void (async () => {
                  const result = await resolution.run(false);
                  if (result) {
                    toast.show(result.notice);
                    ticket.reload();
                    onChanged();
                  }
                })();
              }}
            >
              还没解决
            </button>
          </div>
          <ActionFeedback error={resolution.error} />
        </div>
      )}
    </AsyncBlock>
  );
}

export function TicketView({
  ticket,
  statusTestId = "ticket-status",
}: {
  ticket: ServiceTicket;
  /** 稳定的 E2E 钩子：交接预览与工单列表复用同一组件。 */
  statusTestId?: string;
}): JSX.Element {
  const summary = ticket.summary as Record<string, unknown>;
  return (
    <div className="step">
      <div className="row tight">
        <span data-testid={statusTestId}>
          <Badge tone={ticket.status === "draft" ? "warn" : "accent"}>
            {ticketStatusLabel(ticket.status)}
          </Badge>
        </span>
        <Badge tone="mock">adapter_mode：{ticket.adapter_mode}</Badge>
        {ticket.escalated && <Badge tone="error">已升级</Badge>}
        <span className="mono small">{ticket.id.slice(0, 8)}</span>
      </div>
      {typeof summary.request === "string" && <p style={{ marginTop: 6 }}>诉求：{summary.request}</p>}
      <KeyValue
        items={[
          ["包含记录", ticket.included_record_ids.length > 0 ? `${ticket.included_record_ids.length} 条` : "未包含记录"],
          ["下一步", ticket.next_action ?? "—"],
          ["外部 ID", ticket.external_id ?? "无（本地演示）"],
          ["创建 / 提交", `${formatDateTime(ticket.created_at)} / ${formatDateTime(ticket.submitted_at)}`],
          ["版本", `v${ticket.version}`],
        ]}
      />
      {Array.isArray(summary.products) && summary.products.length > 0 && (
        <div className="small muted">涉及产品：{summary.products.length} 件（摘要不含原始对话或订单截图）</div>
      )}
      <Notice>{ticket.notice}</Notice>
    </div>
  );
}
