/**
 * /inbox 主动服务卡片：原因、已读、采纳（仅记录意向）、稍后、关闭此类。
 * 点击「采用」只记录意向，不会自动接受计划；忽略/未读不改变产品状态。
 */

import { useState } from "react";
import { Link } from "react-router-dom";
import {
  getInboxSummary,
  getProactiveDecisions,
  listFollowups,
  listMessages,
  postMessageFeedback,
  patchFollowup,
} from "../api/endpoints";
import type { MessageFeedbackAction, ServiceMessage } from "../api/types";
import {
  ActionFeedback,
  AsyncBlock,
  Badge,
  Notice,
  Panel,
  useToast,
} from "../components/ui";
import { formatDateTime } from "../lib/format";
import { messageStatusLabel, serviceTypeLabel } from "../lib/labels";
import { useAction, useAsync } from "../state/useAsync";
import { useSession } from "../state/SessionContext";

const ACTION_ORDER: Array<{ action: MessageFeedbackAction; label: string; testId: string }> = [
  { action: "read", label: "标记已读", testId: "inbox-mark-read" },
  { action: "adopt_intent", label: "采用（仅记录意向）", testId: "inbox-adopt" },
  { action: "later", label: "稍后", testId: "inbox-later" },
  { action: "not_helpful", label: "无帮助", testId: "inbox-not-helpful" },
  { action: "mute_type", label: "关闭此类", testId: "inbox-mute" },
];

export function InboxPage(): JSX.Element {
  const toast = useToast();
  const { refreshContext, lastLoadedAt } = useSession();
  const summary = useAsync(() => getInboxSummary(), { deps: [lastLoadedAt] });
  const messages = useAsync(() => listMessages({ limit: 30 }), { deps: [lastLoadedAt] });
  const followups = useAsync(() => listFollowups(), { deps: [lastLoadedAt] });
  const decisions = useAsync(() => getProactiveDecisions(), { deps: [lastLoadedAt] });
  const [busyId, setBusyId] = useState<string | null>(null);

  const feedback = useAction<[string, MessageFeedbackAction], Awaited<ReturnType<typeof postMessageFeedback>>>(
    (messageId, action) => postMessageFeedback(messageId, action),
  );
  const updateFollowup = useAction<[string, "pending" | "done" | "cancelled"], Awaited<ReturnType<typeof patchFollowup>>>(
    (id, status) => patchFollowup(id, status),
  );

  const refresh = () => {
    summary.reload();
    messages.reload();
    followups.reload();
    decisions.reload();
    void refreshContext();
  };

  const run = async (messageId: string, action: MessageFeedbackAction) => {
    setBusyId(messageId);
    const result = await feedback.run(messageId, action);
    setBusyId(null);
    if (result) {
      toast.show(result.notice);
      refresh();
    }
  };

  return (
    <div className="stack">
      <Panel
        title="收件箱（主动服务）"
        subtitle="所有端共享同一 inbox；发送由后端调度与授权策略决定"
        actions={
          <button type="button" onClick={refresh}>
            刷新
          </button>
        }
      >
        {summary.data && (
          <div className="row tight">
            <Badge tone={summary.data.unread_count > 0 ? "warn" : "default"}>
              未读 {summary.data.unread_count} 条
            </Badge>
            <Badge>到期跟进 {summary.data.due_followups.length} 项</Badge>
            <Badge tone="mock">渠道模式：{summary.data.channels.mode}</Badge>
            <Badge tone={summary.data.channels.web_push.available ? "ok" : "mock"}>
              Web Push：{summary.data.channels.web_push.mode}
            </Badge>
          </div>
        )}
        <Notice>
          主动提醒只在授权、相关性、时效、频率与免打扰校验通过后发出；点击「采用」不会自动接受计划或提交售后。
        </Notice>
        <ActionFeedback error={feedback.error} />
      </Panel>

      <Panel title="服务卡片" subtitle="每张卡片说明触发原因，并可已读 / 采纳 / 稍后 / 关闭此类">
        {/* 容器始终渲染：即使收件箱为空，E2E 也能稳定地找到 inbox-list */}
        <div data-testid="inbox-list">
        <AsyncBlock
          loading={messages.loading}
          error={messages.error}
          data={messages.data}
          onRetry={messages.reload}
          isEmpty={(data) => data.messages.length === 0}
          empty="收件箱为空。主动消息由后端调度与触发决策产生（环境＋活动＋计划＋记忆），所有端共享同一 inbox。"
        >
          {(data) => (
            <div className="grid wide">
              {data.messages.map((message) => (
                <MessageCard
                  key={message.id}
                  message={message}
                  busy={busyId === message.id}
                  onAction={(action) => void run(message.id, action)}
                />
              ))}
            </div>
          )}
        </AsyncBlock>
        </div>
        <Notice>{messages.data?.notice}</Notice>
      </Panel>

      <Panel title="跟进任务" subtitle="GET/PATCH /followups">
        <AsyncBlock
          loading={followups.loading}
          error={followups.error}
          data={followups.data}
          onRetry={followups.reload}
          isEmpty={(data) => data.followups.length === 0}
          empty="没有跟进任务。"
        >
          {(data) => (
            <table className="table">
              <thead>
                <tr>
                  <th>标题</th>
                  <th>用途</th>
                  <th>状态</th>
                  <th>计划时间</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {data.followups.map((followup) => (
                  <tr key={followup.id}>
                    <td>{followup.title}</td>
                    <td>{serviceTypeLabel(followup.purpose)}</td>
                    <td>
                      <Badge tone={followup.status === "done" ? "ok" : followup.status === "cancelled" ? "warn" : "accent"}>
                        {followup.status}
                      </Badge>
                    </td>
                    <td>{formatDateTime(followup.scheduled_at)}</td>
                    <td>
                      <div className="row tight">
                        <button
                          type="button"
                          disabled={updateFollowup.running}
                          onClick={() => {
                            void (async () => {
                              const result = await updateFollowup.run(followup.id, "done");
                              if (result) {
                                refresh();
                              }
                            })();
                          }}
                        >
                          标记完成
                        </button>
                        <button
                          type="button"
                          disabled={updateFollowup.running}
                          onClick={() => {
                            void (async () => {
                              const result = await updateFollowup.run(followup.id, "cancelled");
                              if (result) {
                                refresh();
                              }
                            })();
                          }}
                        >
                          取消
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </AsyncBlock>
        <ActionFeedback error={updateFollowup.error} />
      </Panel>

      <Panel title="主动决策审计" subtitle="抑制原因可审计；消费者界面不展示内部评分">
        <AsyncBlock
          loading={decisions.loading}
          error={decisions.error}
          data={decisions.data}
          onRetry={decisions.reload}
          isEmpty={(data) => data.decisions.length === 0}
          empty="还没有决策记录。"
        >
          {(data) => (
            <div className="stack">
              <table className="table">
                <thead>
                  <tr>
                    <th>事件</th>
                    <th>服务类型</th>
                    <th>结果</th>
                    <th>原因码</th>
                    <th>渠道</th>
                    <th>计划版本</th>
                    <th>规则版本</th>
                    <th>时间</th>
                  </tr>
                </thead>
                <tbody>
                  {data.decisions.map((decision) => (
                    <tr key={decision.id}>
                      <td className="mono small">{decision.event_id}</td>
                      <td>{serviceTypeLabel(decision.service_type)}</td>
                      <td>
                        <Badge tone={decision.outcome === "send" ? "ok" : "warn"}>{decision.outcome}</Badge>
                      </td>
                      <td className="small">{decision.reason_codes.join("、")}</td>
                      <td>{decision.channel ?? "—"}</td>
                      <td>{decision.plan_version ?? "—"}</td>
                      <td>{decision.rule_version ?? "—"}</td>
                      <td className="small">{formatDateTime(decision.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <Notice>{data.notice}</Notice>
            </div>
          )}
        </AsyncBlock>
      </Panel>

      <p className="small muted">
        相关页面：<Link to="/settings">通知与渠道设置</Link> · <Link to="/environment">环境与活动</Link> ·{" "}
        <Link to="/routine">计划</Link>
      </p>
    </div>
  );
}

function MessageCard({
  message,
  busy,
  onAction,
}: {
  message: ServiceMessage;
  busy: boolean;
  onAction: (action: MessageFeedbackAction) => void;
}): JSX.Element {
  const serviceType = (message.payload as Record<string, unknown> | null)?.service_type;
  return (
    <div className="turn-card" data-testid="inbox-message" data-message-id={message.id}>
      <div className="row tight">
        <Badge tone={message.read_at === null ? "warn" : "default"}>
          {message.read_at === null ? "未读" : "已读"}
        </Badge>
        <Badge>{messageStatusLabel(message.status)}</Badge>
        <Badge tone="mock">{message.mode}</Badge>
        {typeof serviceType === "string" && <Badge tone="accent">{serviceTypeLabel(serviceType)}</Badge>}
        {message.plan_version !== null && <Badge>计划 v{message.plan_version}</Badge>}
      </div>
      <strong style={{ display: "block", marginTop: 6 }}>{message.title}</strong>
      <p>{message.body}</p>
      <div className="small muted">
        为什么现在提醒：{message.reason_codes.length > 0 ? message.reason_codes.join("、") : "未提供原因码"}
        {message.decision_outcome ? ` · 决策结果：${message.decision_outcome}` : ""}
      </div>
      <div className="small muted">
        数据时间：{formatDateTime(message.created_at)} · 过期：{formatDateTime(message.expires_at)}
      </div>
      {message.source_refs && message.source_refs.length > 0 && (
        <div className="small muted">来源引用：{message.source_refs.length} 条（由后端解析）</div>
      )}
      <div className="row tight" style={{ marginTop: 8 }}>
        {ACTION_ORDER.map((item) => (
          <button
            key={item.action}
            type="button"
            data-testid={item.testId}
            className={item.action === "adopt_intent" ? "primary" : ""}
            disabled={busy}
            onClick={() => onAction(item.action)}
          >
            {busy ? "处理中…" : item.label}
          </button>
        ))}
      </div>
      <Notice>{message.notice}</Notice>
      {typeof serviceType === "string" && serviceType === "service_progress" && (
        <div className="row tight">
          <Link className="btn" to="/service">
            查看工单进度
          </Link>
        </div>
      )}
    </div>
  );
}
