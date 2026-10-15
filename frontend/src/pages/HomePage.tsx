/**
 * / 服务首页：当前计划、未完成事项/待复核、主动服务跟进、模式徽标。
 */

import { Link } from "react-router-dom";
import { getCombinations, listReviewPrompts, listRoutines } from "../api/endpoints";
import type { CombinationsResponse, RoutineListResponse } from "../api/types";
import { ReviewPromptCardLite } from "../components/ReviewPromptInline";
import { AsyncBlock, Badge, EmptyState, Notice, Panel, Stat } from "../components/ui";
import { formatDateTime, truncate } from "../lib/format";
import { planStatusLabel, serviceTypeLabel } from "../lib/labels";
import { useAsync } from "../state/useAsync";
import { useSession } from "../state/SessionContext";

export function HomePage(): JSX.Element {
  const { me, inbox, refreshContext, lastLoadedAt } = useSession();

  const routines = useAsync<RoutineListResponse>(() => listRoutines(), {
    deps: [lastLoadedAt],
  });
  const prompts = useAsync(() => listReviewPrompts(), { deps: [lastLoadedAt] });
  const combinations = useAsync<CombinationsResponse>(() => getCombinations(), {
    deps: [lastLoadedAt],
  });

  const refreshAll = () => {
    void refreshContext();
    routines.reload();
    prompts.reload();
    combinations.reload();
  };

  const openPrompts = prompts.data?.prompts.filter((prompt) => prompt.status === "open") ?? [];

  return (
    <div className="stack">
      <Panel
        title="服务首页"
        subtitle="当前计划、未完成事项与主动服务跟进（状态以服务器为准）"
        actions={
          <>
            <button type="button" onClick={refreshAll}>
              刷新
            </button>
            <Link className="btn" to="/chat">
              去对话
            </Link>
          </>
        }
      >
        {me ? (
          <div className="row tight">
            <Badge tone={me.mode.model_mode === "mock" ? "mock" : "ok"}>
              MODEL_MODE：{me.mode.model_mode}
            </Badge>
            <Badge tone={me.mode.weather_mode === "mock" ? "mock" : "ok"}>
              WEATHER_MODE：{me.mode.weather_mode}
            </Badge>
            <Badge tone="accent">NOTIFICATION_MODE：{me.mode.notification_mode}</Badge>
            <Badge tone="mock">数据为 mock/演示数据</Badge>
          </div>
        ) : (
          <EmptyState>尚未取得用户信息。</EmptyState>
        )}
        <Notice>{me?.notice ?? "演示环境：状态以服务器为准，跨设备共享。"}</Notice>
      </Panel>

      <div className="grid wide">
        <Panel title="当前计划" subtitle="每用户最多一份生效版本">
          <AsyncBlock
            loading={routines.loading}
            error={routines.error}
            data={routines.data}
            onRetry={routines.reload}
            loadingLabel="加载计划…"
            empty="尚无计划记录。可到计划页生成草稿。"
          >
            {(data) =>
              data.active === null ? (
                <EmptyState hint="草稿在接受前不会生效。">
                  当前没有生效中的计划。
                  <div className="row tight" style={{ marginTop: 8 }}>
                    <Link className="btn primary" to="/routine">
                      生成计划草稿
                    </Link>
                  </div>
                </EmptyState>
              ) : (
                <div className="stack">
                  <div className="row tight">
                    <Badge tone="ok">生效版本 v{data.active.version}</Badge>
                    <Badge>{planStatusLabel(data.active.status)}</Badge>
                    <Badge>步骤 {data.active.steps.length}</Badge>
                    {data.active.needs_review && <Badge tone="warn">需要复核</Badge>}
                  </div>
                  {data.active.needs_review_reason && (
                    <p className="small muted">{data.active.needs_review_reason}</p>
                  )}
                  <div className="small muted">
                    接受时间：{formatDateTime(data.active.accepted_at, me?.user.timezone)}
                  </div>
                  <ol className="small">
                    {data.active.steps.slice(0, 6).map((step) => (
                      <li key={step.id}>
                        [{step.period}] {step.label}
                      </li>
                    ))}
                  </ol>
                  {data.active.steps.length > 6 && (
                    <div className="small muted">…共 {data.active.steps.length} 步</div>
                  )}
                  <div className="row tight">
                    <Link className="btn primary" to="/routine">
                      查看完整计划与历史
                    </Link>
                  </div>
                </div>
              )
            }
          </AsyncBlock>
        </Panel>

        <Panel title="未完成事项 / 待复核" subtitle="负面反馈只生成复核询问，不自动改计划">
          <AsyncBlock
            loading={prompts.loading}
            error={prompts.error}
            data={prompts.data}
            onRetry={prompts.reload}
            loadingLabel="加载复核询问…"
            isEmpty={(data) => data.prompts.filter((p) => p.status === "open").length === 0}
            empty="没有未处理的复核询问。"
          >
            {(data) => (
              <div className="stack">
                {data.prompts
                  .filter((prompt) => prompt.status === "open")
                  .slice(0, 4)
                  .map((prompt) => (
                    <ReviewPromptCardLite key={prompt.id} prompt={prompt} onDecided={refreshAll} />
                  ))}
                {data.prompts.filter((prompt) => prompt.status !== "open").length > 0 && (
                  <div className="small muted">
                    已处理 {data.prompts.filter((prompt) => prompt.status !== "open").length} 条复核询问
                    （记录保留，可到计划页查看）。
                  </div>
                )}
                <Notice>{data.notice}</Notice>
              </div>
            )}
          </AsyncBlock>
        </Panel>

        <Panel title="主动服务跟进" subtitle="内应用消息与到期跟进任务">
          {inbox === null ? (
            <EmptyState>暂无收件箱数据。</EmptyState>
          ) : (
            <div className="stack">
              <div className="stat">
                <Stat label="未读服务消息" value={inbox.unread_count} />
                <Stat label="到期跟进" value={inbox.due_followups.length} />
                <Stat label="复核询问" value={openPrompts.length} />
              </div>
              {inbox.messages.length === 0 ? (
                <EmptyState hint="主动消息由后端调度产生，关闭网页也会继续。">
                  收件箱为空。
                </EmptyState>
              ) : (
                <ul className="small">
                  {inbox.messages.slice(0, 4).map((message) => (
                    <li key={message.id}>
                      <strong>{message.title}</strong> — {truncate(message.body, 60)}
                      {message.read_at === null ? "（未读）" : ""}
                    </li>
                  ))}
                </ul>
              )}
              {inbox.due_followups.length > 0 && (
                <ul className="small">
                  {inbox.due_followups.map((item) => (
                    <li key={item.id}>
                      {item.title} · {serviceTypeLabel(item.purpose)}
                    </li>
                  ))}
                </ul>
              )}
              <div className="row tight">
                <Link className="btn" to="/inbox">
                  打开收件箱
                </Link>
              </div>
            </div>
          )}
        </Panel>

        <Panel title="组合适用性" subtitle="每条提示都逐条附来源，系统不替你判定能否叠用">
          <AsyncBlock
            loading={combinations.loading}
            error={combinations.error}
            data={combinations.data}
            onRetry={combinations.reload}
            loadingLabel="加载组合提示…"
            isEmpty={(data) => data.combination_notes.length === 0}
            empty="当前没有需要提示的组合情况。"
          >
            {(data) => (
              <div className="stack">
                <div className="small muted">
                  计划版本：{data.plan_version === null ? "无生效版本" : `v${data.plan_version}`} · 参与推理
                  产品 {data.products.length} 件
                </div>
                <ul className="small">
                  {data.combination_notes.slice(0, 3).map((note, index) => (
                    <li key={index}>{truncate(note.text, 90)}</li>
                  ))}
                </ul>
                <div className="row tight">
                  <Link className="btn" to="/routine">
                    到计划页选择保留 / 间隔 / 移除
                  </Link>
                </div>
                <Notice>{data.notice}</Notice>
              </div>
            )}
          </AsyncBlock>
        </Panel>
      </div>
    </div>
  );
}
