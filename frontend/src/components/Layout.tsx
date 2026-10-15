/**
 * 应用外壳：左侧导航 + 主内容 + 右侧「服务上下文」面板。
 * 未登录（localStorage 无令牌）时显示身份/空状态页，不渲染业务页面，
 * 因此所有页面都基于已授权请求。
 */

import { NavLink, Outlet } from "react-router-dom";
import { DEMO_NOTICE } from "../lib/labels";
import { useSession } from "../state/SessionContext";
import { PersonaSwitcher } from "./PersonaSwitcher";
import { ServiceContextPanel } from "./ServiceContextPanel";
import { Badge, ErrorState, Notice, Panel } from "./ui";

interface NavItem {
  to: string;
  label: string;
  end?: boolean;
  /** 稳定的 E2E 钩子（data-testid）。 */
  testId: string;
}

const NAV_GROUPS: Array<{ title: string; items: NavItem[] }> = [
  {
    title: "服务",
    items: [
      { to: "/", label: "首页", end: true, testId: "nav-home" },
      { to: "/inbox", label: "收件箱（主动服务）", testId: "nav-inbox" },
      { to: "/chat", label: "对话", testId: "nav-chat" },
      { to: "/routine", label: "早晚计划", testId: "nav-routine" },
      { to: "/environment", label: "环境与出行", testId: "nav-environment" },
    ],
  },
  {
    title: "我的产品",
    items: [
      { to: "/cabinet", label: "美妆柜", testId: "nav-cabinet" },
      { to: "/ingredients/atlas", label: "成分图鉴", testId: "nav-atlas" },
      { to: "/memory", label: "记忆与反馈", testId: "nav-memory" },
    ],
  },
  {
    title: "其他",
    items: [
      { to: "/service", label: "工单与交接", testId: "nav-service" },
      { to: "/settings", label: "设置", testId: "nav-settings" },
      { to: "/brand/insights", label: "品牌需求面板（演示）", testId: "nav-brand" },
      { to: "/staff/tickets", label: "客服工作台（演示）", testId: "nav-staff" },
    ],
  },
];

export function AppShell(): JSX.Element {
  const { token, error, loading, refreshMe, me } = useSession();

  if (!token) {
    return <AuthLanding />;
  }

  return (
    // data-testid="app-ready" 只在 GET /api/v1/me 成功返回后出现，
    // E2E 可以等待它来确认会话与上下文已经就绪。
    <div className="app-shell" data-testid={me !== null ? "app-ready" : undefined}>
      <aside className="app-sidebar">
        <div className="brand-block">
          <div className="brand-title">美妆管家 BeautyCare</div>
          <div className="brand-sub">买后管家 · 本地演示版</div>
          <div className="row tight" style={{ marginTop: 6 }}>
            <Badge tone="mock">演示数据</Badge>
          </div>
        </div>
        <PersonaSwitcher compact />
        <nav aria-label="主导航">
          {NAV_GROUPS.map((group) => (
            <div key={group.title}>
              <div className="nav-group-label">{group.title}</div>
              <ul className="nav-list">
                {group.items.map((item) => (
                  <li key={item.to}>
                    <NavLink to={item.to} end={item.end} data-testid={item.testId}>
                      {item.label}
                    </NavLink>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </nav>
      </aside>

      <main className="app-main">
        {loading && <div className="state loading">正在读取服务端会话状态…</div>}
        {error && (
          <ErrorState
            error={error}
            title="读取 /me 失败"
            onRetry={() => void refreshMe()}
          />
        )}
        <Outlet />
      </main>

      <ServiceContextPanel />
    </div>
  );
}

function AuthLanding(): JSX.Element {
  const { loading, error } = useSession();
  return (
    <div className="gate stack">
      <Panel
        title="美妆管家 BeautyCare（演示）"
        subtitle="买后管家：基于已购产品、使用记忆与实时环境的护肤计划与成分认知"
      >
        <p>
          当前没有可用的服务端会话令牌，因此页面处于未登录/空状态。请选择一个<b>演示身份</b>
          以完成本地演示身份交换（POST /api/v1/auth/demo-session），令牌会保存在浏览器
          localStorage 中，并在后续请求以 <code>Authorization: Bearer &lt;token&gt;</code> 发送。
        </p>
        <Notice tone="mock">{DEMO_NOTICE}</Notice>
        <p className="small muted">
          前端不会也不能提交 user_id：身份完全由服务端会话决定（spec 第 10/11 节）。
        </p>
      </Panel>
      <PersonaSwitcher />
      {loading && <div className="state loading">正在交换演示身份…</div>}
      {error && <ErrorState error={error} title="演示身份登录失败" />}
      <Panel title="需要后端在运行" subtitle="本前端默认走同源 /api/v1（开发时由 vite 代理到 127.0.0.1:8000）">
        <p className="small muted">
          启动后端示例：
          <br />
          <code>
            DATABASE_URL=&quot;sqlite+pysqlite:///$PWD/beautycare.db&quot; SCHEDULER_ENABLED=false
            ./.venv/bin/uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
          </code>
        </p>
      </Panel>
    </div>
  );
}
