/**
 * /staff/tickets/:id 演示客服视图：摘要、证据、状态更新。
 * 明确标识为本地模拟业务环境，不对应任何真实品牌客服系统。
 * 附带 /staff/tickets 队列页，便于从演示列表进入具体工单。
 */

import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getAudit, getStaffQueue, getStaffTicket, patchStaffTicket } from "../api/endpoints";
import type { ServiceTicket } from "../api/types";
import { TicketView } from "./ServicePage";
import {
  ActionFeedback,
  AsyncBlock,
  Badge,
  EmptyState,
  Notice,
  Panel,
  useToast,
} from "../components/ui";
import { formatDateTime } from "../lib/format";
import { HANDOFF_STATUS_OPTIONS, ticketStatusLabel } from "../lib/labels";
import { useAction, useAsync } from "../state/useAsync";
import { useSession } from "../state/SessionContext";

export function StaffQueuePage(): JSX.Element {
  const { me, lastLoadedAt } = useSession();
  const queue = useAsync(() => getStaffQueue(), { deps: [lastLoadedAt] });
  const audit = useAsync(() => getAudit(), { deps: [lastLoadedAt] });

  return (
    <div className="stack">
      <Panel
        title="客服工作台（演示）"
        subtitle="模拟业务环境（本地演示工作台）：不对应任何真实品牌客服系统"
        actions={
          <button type="button" onClick={() => {
            queue.reload();
            audit.reload();
          }}>
            刷新
          </button>
        }
      >
        <div className="row tight">
          <Badge tone="mock">角色：{me?.user.role ?? "未知"}</Badge>
          {me?.user.role !== "staff" && (
            <Badge tone="warn">非 staff 角色访问该接口会返回 403 FORBIDDEN</Badge>
          )}
        </div>
        <Notice tone="mock">
          工单状态来自本地演示工作台；staff 标记 resolved 不等于用户已确认解决。
        </Notice>
      </Panel>

      <Panel title="工单队列" subtitle="GET /staff/tickets">
        <AsyncBlock
          loading={queue.loading}
          error={queue.error}
          data={queue.data}
          onRetry={queue.reload}
          isEmpty={(data) => data.tickets.length === 0}
          empty="队列为空：先在 /service 生成交接草稿并确认提交。"
        >
          {(data) => (
            <div className="stack">
              <div className="small muted">{data.environment}</div>
              <table className="table">
                <thead>
                  <tr>
                    <th>工单</th>
                    <th>状态</th>
                    <th>适配器</th>
                    <th>提交时间</th>
                    <th>下一步</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {data.tickets.map((ticket) => (
                    <tr key={ticket.id} data-testid="staff-ticket-row" data-ticket-id={ticket.id}>
                      <td className="mono">{ticket.id.slice(0, 8)}</td>
                      <td>
                        <Badge tone={ticket.status === "resolved" ? "ok" : "accent"}>
                          {ticketStatusLabel(ticket.status)}
                        </Badge>
                      </td>
                      <td>{ticket.adapter_mode}</td>
                      <td>{formatDateTime(ticket.submitted_at)}</td>
                      <td className="small">{ticket.next_action ?? "—"}</td>
                      <td>
                        <Link className="btn" to={`/staff/tickets/${ticket.id}`}>
                          打开客服视图
                        </Link>
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

      <Panel title="审计事件（脱敏）" subtitle="GET /admin/audit，仅 staff 角色">
        <AsyncBlock
          loading={audit.loading}
          error={audit.error}
          data={audit.data}
          onRetry={audit.reload}
          isEmpty={(data) => data.events.length === 0}
          empty="没有审计事件。"
        >
          {(data) => (
            <div className="stack">
              <table className="table">
                <thead>
                  <tr>
                    <th>时间</th>
                    <th>动作</th>
                    <th>角色</th>
                    <th>实体</th>
                    <th>元数据</th>
                  </tr>
                </thead>
                <tbody>
                  {data.events.slice(0, 40).map((event) => (
                    <tr key={event.id}>
                      <td className="small">{formatDateTime(event.at)}</td>
                      <td>{event.action}</td>
                      <td>{event.actor_role ?? "—"}</td>
                      <td className="small">
                        {event.entity_type ?? "—"} {event.entity_id ? event.entity_id.slice(0, 8) : ""}
                      </td>
                      <td className="mono small">{JSON.stringify(event.meta)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <Notice>{data.notice}</Notice>
            </div>
          )}
        </AsyncBlock>
      </Panel>
    </div>
  );
}

export function StaffTicketPage(): JSX.Element {
  const { id = "" } = useParams();
  const toast = useToast();
  const ticket = useAsync(() => getStaffTicket(id), { deps: [id], enabled: id.length > 0 });
  const [status, setStatus] = useState<string>("in_review");
  const [note, setNote] = useState("");
  const update = useAction<[string], Awaited<ReturnType<typeof patchStaffTicket>>>((nextStatus) =>
    patchStaffTicket(id, { status: nextStatus, note: note || null }),
  );

  return (
    <div className="stack">
      <Panel
        title="演示客服视图"
        subtitle={`工单 ${id}`}
        actions={
          <>
            <Link className="btn" to="/staff/tickets">
              返回队列
            </Link>
            <button type="button" onClick={() => ticket.reload()}>
              刷新
            </button>
          </>
        }
      >
        <AsyncBlock
          loading={ticket.loading}
          error={ticket.error}
          data={ticket.data}
          onRetry={ticket.reload}
          loadingLabel="加载工单…"
        >
          {(data) => (
            <div className="stack">
              <div className="row tight">
                <Badge tone="mock">{data.environment}</Badge>
                <Badge>状态：{ticketStatusLabel(data.ticket.status)}</Badge>
                <Badge tone="mock">adapter_mode：{data.ticket.adapter_mode}</Badge>
              </div>

              <div>
                <div className="panel-sub">摘要（summary_json，不含原始对话原文）</div>
                <pre className="mono" style={{ whiteSpace: "pre-wrap" }}>
                  {JSON.stringify(data.ticket.summary, null, 1)}
                </pre>
              </div>

              <div>
                <div className="panel-sub">证据</div>
                <div className="grid">
                  <EvidenceList title="产品" items={data.evidence.products} />
                  <EvidenceList title="用户报告" items={data.evidence.user_reports} />
                  <EvidenceList title="已做动作" items={data.evidence.actions_already_taken} />
                </div>
              </div>

              <TicketView ticket={data.ticket as ServiceTicket} />

              <div>
                <div className="panel-sub">状态更新（PATCH /staff/tickets/{id}）</div>
                <div className="row">
                  <div className="field">
                    <label htmlFor="staff-status">目标状态</label>
                    <select
                      id="staff-status"
                      data-testid="staff-ticket-status-select"
                      value={status}
                      onChange={(event) => setStatus(event.target.value)}
                    >
                      {HANDOFF_STATUS_OPTIONS.map((option) => (
                        <option key={option.value} value={option.value}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="field" style={{ flex: 1, minWidth: 220 }}>
                    <label htmlFor="staff-note">备注</label>
                    <input
                      id="staff-note"
                      data-testid="staff-ticket-note"
                      value={note}
                      onChange={(event) => setNote(event.target.value)}
                    />
                  </div>
                  <button
                    type="button"
                    className="primary"
                    data-testid="staff-ticket-save"
                    disabled={update.running}
                    onClick={() => {
                      void (async () => {
                        const result = await update.run(status);
                        if (result) {
                          toast.show(result.notice);
                          ticket.reload();
                        }
                      })();
                    }}
                  >
                    {update.running ? "更新中…" : "更新状态"}
                  </button>
                </div>
                <Notice>客服标记 resolved 不等于用户已确认解决；用户确认单独存储。</Notice>
                <ActionFeedback error={update.error} />
              </div>
            </div>
          )}
        </AsyncBlock>
      </Panel>
    </div>
  );
}

function EvidenceList({ title, items }: { title: string; items: unknown[] }): JSX.Element {
  return (
    <div className="step">
      <div className="panel-sub">{title}（{items.length}）</div>
      {items.length === 0 ? (
        <EmptyState>无</EmptyState>
      ) : (
        <ul className="small">
          {items.map((item, index) => (
            <li key={index}>{typeof item === "string" ? item : JSON.stringify(item)}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
