/**
 * 持久右侧「服务上下文」面板。
 *
 * 展示：模式徽标（MODEL_MODE / WEATHER_MODE / NOTIFICATION_MODE，来自 GET /api/v1/me）、
 * 当前生效计划版本、未处理复核询问、未读服务消息，以及 clock.is_demo_time 为 true 时的
 * 演示时钟横幅。窄屏（<900px）时由按钮折叠/展开，默认折叠。
 */

import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { formatDateTime } from "../lib/format";
import { serviceTypeLabel } from "../lib/labels";
import { useSession } from "../state/SessionContext";
import { Badge, ErrorState, Loading } from "./ui";

function useNarrowScreen(): boolean {
  const [narrow, setNarrow] = useState<boolean>(
    () => typeof window !== "undefined" && window.matchMedia("(max-width: 900px)").matches,
  );
  useEffect(() => {
    const query = window.matchMedia("(max-width: 900px)");
    const listener = (event: MediaQueryListEvent) => setNarrow(event.matches);
    query.addEventListener("change", listener);
    return () => query.removeEventListener("change", listener);
  }, []);
  return narrow;
}

export function ServiceContextPanel(): JSX.Element {
  const { me, reviewPrompts, inbox, loading, error, contextError, refreshContext, lastLoadedAt } =
    useSession();
  const narrow = useNarrowScreen();
  const [open, setOpen] = useState<boolean>(!narrow);

  useEffect(() => {
    setOpen(!narrow);
  }, [narrow]);

  const openPrompts = reviewPrompts.filter((prompt) => prompt.status === "open");
  const unread = inbox?.unread_count ?? 0;

  return (
    <div className={open ? "app-context" : "app-context collapsed"}>
      <div className="row tight">
        <span className="panel-title">服务上下文</span>
        <span className="spacer" />
        <button type="button" className="context-toggle" onClick={() => setOpen((value) => !value)}>
          {open ? "收起" : "展开"}
        </button>
      </div>

      {loading && me === null && <Loading label="加载服务上下文…" />}
      {error && me === null && (
        <ErrorState error={error} title="无法读取 /me" onRetry={() => void refreshContext()} />
      )}

      {me && (
        <>
          {me.clock.is_demo_time && (
            <div className="demo-banner" data-testid="clock-banner">
              演示时钟：{me.clock.label} · 服务端时间 {formatDateTime(me.clock.now, me.user.timezone)}
              （偏移 {Math.round(me.clock.offset_seconds / 3600)} 小时）。所有输出都会标记
              is_demo_time=true，不会当作真实时间。
            </div>
          )}

          <section className="panel tight">
            <div className="panel-sub">运行模式</div>
            <div className="row tight" style={{ marginTop: 6 }} data-testid="mode-badges">
              <Badge tone={me.mode.model_mode === "mock" ? "mock" : "ok"}>
                MODEL_MODE：{me.mode.model_mode}
                {me.mode.model_mode === "mock" ? "（确定性演示，不称真实模型）" : ""}
              </Badge>
              <Badge tone={me.mode.weather_mode === "mock" ? "mock" : "ok"}>
                WEATHER_MODE：{me.mode.weather_mode}
              </Badge>
              <Badge tone="accent">NOTIFICATION_MODE：{me.mode.notification_mode}</Badge>
              <Badge>AUTH_MODE：{me.mode.auth_mode}</Badge>
            </div>
          </section>

          <section className="panel tight">
            <div className="panel-sub">当前计划</div>
            <div style={{ marginTop: 6 }}>
              {me.counts.active_plan_version === null ? (
                <span className="small muted">当前没有生效中的计划版本。</span>
              ) : (
                <Badge tone="ok">生效版本 v{me.counts.active_plan_version}</Badge>
              )}
            </div>
            <div className="small muted" style={{ marginTop: 4 }}>
              产品 {me.counts.owned_products} 件（暂停 {me.counts.paused_products}） · 计划记录{" "}
              {me.counts.plans} 份
            </div>
            <div className="row tight" style={{ marginTop: 6 }}>
              <Link className="btn" to="/routine">
                打开计划
              </Link>
            </div>
          </section>

          <section className="panel tight">
            <div className="panel-sub">未处理复核询问</div>
            {openPrompts.length === 0 ? (
              <div className="small muted" style={{ marginTop: 4 }}>
                暂无未处理的复核询问。
              </div>
            ) : (
              <ul className="small" style={{ marginTop: 4 }}>
                {openPrompts.slice(0, 3).map((prompt) => (
                  <li key={prompt.id}>{prompt.question}</li>
                ))}
              </ul>
            )}
            <div className="row tight">
              <Badge tone={openPrompts.length > 0 ? "warn" : "default"}>{openPrompts.length} 项待处理</Badge>
              <Link className="btn" to="/routine">
                去复核
              </Link>
            </div>
          </section>

          <section className="panel tight">
            <div className="panel-sub">未读服务消息</div>
            <div className="row tight" style={{ marginTop: 6 }}>
              <Badge tone={unread > 0 ? "warn" : "default"}>{unread} 条未读</Badge>
              <Link className="btn" to="/inbox">
                打开收件箱
              </Link>
            </div>
            {inbox && inbox.due_followups.length > 0 && (
              <ul className="small" style={{ marginTop: 6 }}>
                {inbox.due_followups.map((item) => (
                  <li key={item.id}>
                    {item.title}（{serviceTypeLabel(item.purpose)}）
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="panel tight">
            <div className="panel-sub">通知授权摘要</div>
            <div className="small muted" style={{ marginTop: 4 }}>
              服务类型：{me.notification.service_types.map(serviceTypeLabel).join("、") || "未选择"} ·
              渠道：{me.notification.channels.join("、") || "无"} · 每日上限 {me.notification.daily_cap}{" "}
              条 · 免打扰 {me.notification.quiet_hours[0]}–{me.notification.quiet_hours[1]}（
              {me.notification.timezone}）
            </div>
            <div className="row tight">
              <Link className="btn" to="/settings">
                修改通知设置
              </Link>
            </div>
          </section>

          <div className="row tight">
            <button type="button" onClick={() => void refreshContext()}>
              刷新上下文
            </button>
            <span className="small muted">
              {lastLoadedAt ? `最后刷新 ${formatDateTime(lastLoadedAt, me.user.timezone)}` : ""}
            </span>
          </div>
          {contextError && (
            <ErrorState error={contextError} title="上下文部分数据刷新失败" onRetry={() => void refreshContext()} />
          )}
        </>
      )}
    </div>
  );
}
