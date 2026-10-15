# 美妆管家 BeautyCare（演示）· 前端

React + TypeScript + Vite 单页应用（PWA 可安装），是 BeautyCare「买后管家」后端的消费者端界面。

> **演示环境声明（请务必先读）**
> 本前端是**本地演示应用**：产品目录含虚构 DEMO SKU，识别（OCR/视觉）、天气、推送、品牌台全部是**本地模拟**，
> **没有接入任何真实品牌、真实订单、真实 OCR、真实推送通道或真实客服系统**，也**不是已交付的原生 App**。
> 界面上凡涉及 mock/演示数据的地方都内联标注（如「mock 演示数据」「DEMO 演示来源」「本地演示工作台」），
> 并尽量复用后端返回的 `notice` 文案，不自行编造结论。
> 成分图鉴与主动服务卡片的所有关联措辞都**逐字复用后端返回值**，前端绝不出现「过敏 / 导致 / 避免」这类断言。

---

## 1. 快速开始

工具链（本机没有全局 `node`/`pnpm`，用下面的绝对路径）：

```bash
NODE_BIN=/Users/ee/.dsh/dsh-runtimes/dsh-primary-runtime/dependencies/node/bin
PNPM="node /Users/ee/.dsh/dsh-runtimes/dsh-primary-runtime/dependencies/pnpm/bin/pnpm.mjs"
export PATH="$NODE_BIN:$PATH"
```

### 1.1 启动后端（必须，前端所有数据都来自它）

```bash
cd /Users/ee/Documents/deepseek-harness/default-workspace

# 首次：建库 + 种子数据
./.venv/bin/python -c "import sys;sys.path.insert(0,'backend');from app.db import get_engine;from app.models import Base;Base.metadata.create_all(get_engine())"
./.venv/bin/python -m scripts.seed_db

# 启动（演示期间关闭调度器）
DATABASE_URL="sqlite+pysqlite:///$PWD/beautycare.db" SCHEDULER_ENABLED=false \
  ./.venv/bin/uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

### 1.2 启动前端（开发模式，推荐）

```bash
cd frontend
export PATH="$NODE_BIN:$PATH"
node /Users/ee/.dsh/dsh-runtimes/dsh-primary-runtime/dependencies/pnpm/bin/pnpm.mjs install
node /Users/ee/.dsh/dsh-runtimes/dsh-primary-runtime/dependencies/pnpm/bin/pnpm.mjs dev
# 打开 http://127.0.0.1:5173
```

`vite.config.ts` 把 `/api` 代理到 `http://127.0.0.1:8000`，所以开发模式下是**同源请求，不经过 CORS**。

### 1.3 构建与预览（生产产物）

```bash
cd frontend
export PATH="$NODE_BIN:$PATH"
node .../pnpm.mjs build      # 等价于 tsc --noEmit && vite build，产物在 dist/
node .../pnpm.mjs preview    # 起一个静态服务器预览 dist/（默认 http://127.0.0.1:4173）
```

> `pnpm preview` **不带** `/api` 代理。若要让构建产物直接访问后端，有两种方式：
> 1. 把 `dist/` 交给一个反代 `/api` 的静态服务器（推荐，保持同源）；
> 2. 或构建时指定 `VITE_API_BASE=http://127.0.0.1:8000/api/v1`，并把该页面来源加入后端
>    `CORS_ORIGINS`（默认只允许 `http://localhost:5173,http://127.0.0.1:5173`）。
>    实测：不带 `Origin` 白名单时后端不会返回 `access-control-allow-origin`，浏览器会拦下跨源请求。

---

## 2. 指向后端 / 环境变量

| 变量 | 作用 | 默认 |
|---|---|---|
| `VITE_API_BASE` | 覆盖 API 前缀（例如 `http://127.0.0.1:8000/api/v1`） | 同源 `/api/v1` |
| `VITE_VAPID_PUBLIC_KEY` | Web Push 的 VAPID 公钥；**为空时设置页如实显示「未启用」**，不会假装已订阅 | 空 |

页面文案里的「后端未在运行」提示与 `NETWORK_ERROR` 都由真实请求失败产生，不做假成功。

---

## 3. 演示身份切换器（persona switcher）

本地演示用**服务端固定身份**，前端从不提交 `user_id`：

- 未登录时：首屏就是身份选择（`persona-switcher`），四个身份各一个按钮。
- 已登录时：左侧导航顶部仍有同一组按钮，可直接切换（切换后重新调用 `GET /api/v1/me`，令牌写入 localStorage）。

| personae | 说明 |
|---|---|
| `consumer_a` | 反馈积累充分，可触发成分图鉴（4 张卡片 / 2 个样本不足） |
| `consumer_b` | 另一个独立用户，用于验证数据隔离与空状态 |
| `staff` | 演示客服工作台（工单队列、审计事件） |
| `brand` | 演示品牌面板（只看聚合；群体不足 10 人时抑制明细） |

流程：点击身份 → `POST /api/v1/auth/demo-session {persona_code}` → 拿到 `{token,user}` →
`localStorage["beautycare.demo.token"]` → 之后所有请求带 `Authorization: Bearer <token>`。
令牌失效（真正两次 401）会自动清理并回到未登录页，并显示带 `code` 的错误。

---

## 4. 路由

| 路由 | 内容 |
|---|---|
| `/` | 首页：模式徽标、当前计划、待复核、主动服务跟进、组合适用性 |
| `/cabinet` | 美妆柜：筛选、手动添加、状态操作、导入入口 |
| `/imports/:id` | 识别结果、候选、低置信提示、改数量/匹配后确认入柜 |
| `/products/:ownedId` | 我的这件产品：版本、日期、到期未知说明、说明与来源、事件 |
| `/routine` | 早晚计划、生成草稿、差异、接受、历史版本、组合提示（保留/间隔/移除） |
| `/chat` | 对话：结构化卡片、追问、待确认按钮、交接入口 |
| `/memory` | 偏好 / 用户报告 / 来源 / 修改 / 删除 / 成分补充陈述 |
| `/service` | 交接草稿预览与提交、工单与时间线、是否解决的用户确认 |
| `/settings` | 数据导出/删除、城市、通知类型/渠道/频率/免打扰、模型模式说明、PWA 通知订阅、演示时钟与天气场景 |
| `/environment` | 城市、当前与预测环境、来源/更新时间/缺失字段、活动与行程、触发规则 |
| `/inbox` | 主动服务卡片：原因码、已读、采纳（仅意向）、稍后、无帮助、关闭此类、跟进任务、决策审计 |
| `/brand/insights` | 演示品牌需求面板（聚合、群体抑制、需求草稿与同意） |
| `/staff/tickets` `/staff/tickets/:id` | 演示客服队列与客服视图（摘要、证据、状态更新） |
| `/ingredients/atlas` | 成分图鉴 |

每个异步动作都有 **loading / error（含 `{code,message,retryable}` + 重试）/ empty** 四态；
任何请求失败都会在右下角出现 `data-testid="toast-error"`，文案包含错误 `code`。

右侧常驻「服务上下文」面板：`MODEL_MODE / WEATHER_MODE / NOTIFICATION_MODE` 徽标、当前生效计划版本、
未处理复核询问、未读服务消息、`clock.is_demo_time` 为真时的演示时钟横幅。
窄屏（< 900px）时该面板折叠到主内容下方，由按钮展开；导航变为横向换行。

---

## 5. PWA

- `public/manifest.webmanifest`：`name/short_name = BeautyCare`，`start_url="/"`，`display="standalone"`，
  `theme_color/background_color`，192/512 普通图标 + 192/512 maskable 图标。
- `public/icons/*.png`：真实 PNG，由 `scripts/make_icons.py` 生成（纯色圆角方块 + 「BC」字形，无真实品牌标识）：
  ```bash
  ./.venv/bin/python frontend/scripts/make_icons.py
  ```
- `public/sw.js`：
  - 静态资源 **cache-first**，缓存名带版本号（`beautycare-static-v1`，升级即失效旧缓存）；
  - `/api/` **network-only，个人 API 响应绝不写入缓存**；
  - `push` → 显示中性通知（不含症状、订单号、完整行程）；
  - `notificationclick` → 聚焦已打开页面，否则打开 `event.notification.data.url` 深链接。
- `src/main.tsx` **只在生产构建**注册 Service Worker（`import.meta.env.PROD`），开发模式不注册以免干扰 HMR。
- **通知权限永远不在首屏请求**：只有 `/settings` 上点击「点击开启浏览器通知（可选）」按钮才会
  `Notification.requestPermission()`；仅当配置了 `VITE_VAPID_PUBLIC_KEY` 时才 `pushManager.subscribe`，
  否则如实显示「未配置 VAPID：mock/未启用」。

安装步骤（Chrome/Edge）：打开站点 → 地址栏右侧「安装」图标（或菜单「安装 BeautyCare」）→ 建议用
`http://127.0.0.1` 或 https 打开（Service Worker 需要安全上下文）。iOS Safari：分享 → 添加到主屏幕。

---

## 6. 稳定的 E2E 钩子（`data-testid`）

所有钩子都已在**真实渲染后的 DOM** 中验证（见 `scripts/dom_audit.py`），不是只写在 JSX 里。节选：

- 外壳：`app-ready`（**只在 `GET /api/v1/me` 成功后出现**）、`mode-badges`、`clock-banner`、`toast-error`、
  `persona-switcher` / `persona-consumer_a|consumer_b|staff|brand`、`nav-*`（home/cabinet/routine/chat/memory/
  service/settings/environment/inbox/atlas/brand/staff）。
- 美妆柜/导入：`cabinet-list`、`cabinet-item[data-owned-id]`、`cabinet-add-open`、`cabinet-add-name`、
  `cabinet-add-submit`、`import-file-input`、`import-submit`、`import-status`、`import-candidates`、
  `import-candidate-row[data-index]`、`import-candidate-name-<n>`、`import-candidate-qty-<n>`、`import-confirm`。
- 计划：`routine-active`、`routine-active-version`、`routine-generate`、`routine-step[data-step-label]`、
  `routine-draft-card`、`routine-draft-version`、`routine-draft-steps`、`routine-diff-summary`、`routine-accept`、
  `routine-history`、`combination-note`、`combination-option-keep|space_out|remove_one`、
  `review-prompt-pause|keep|adjust`。
- 对话：`chat-input`、`chat-send`、`chat-message[data-role]`、`chat-card-<type>`、
  `chat-pending-action-<type>`（如 `chat-pending-action-accept_routine`）。
- 记忆：`memory-list`、`memory-record[data-key][data-status]`、`memory-edit-<key>`、`memory-edit-value`、
  `memory-edit-save`、`memory-delete-<key>`、`usage-event-row`、`usage-event-delete`。
- 图鉴：`atlas-generate`、`atlas-card[data-common-name]`、`atlas-card-status`、`atlas-below-threshold`、
  `atlas-dropped-extensions`、`atlas-feedback-input`、`atlas-feedback-submit`。
- 客服：`handoff-candidates`、`handoff-candidate-checkbox[data-record-id]`、`handoff-request-input`、
  `handoff-preview-button`、`handoff-preview`、`handoff-preview-status`、`handoff-submit`、`ticket-status`、
  `ticket-timeline`、`staff-ticket-row[data-ticket-id]`、`staff-ticket-status-select`、`staff-ticket-note`、
  `staff-ticket-save`。
- 环境/设置/收件箱：`city-select`、`city-save`、`env-current`、`env-quality`、`env-missing-fields`、
  `activity-title`、`activity-start`、`activity-create`、`activity-row`、`activity-cancel`、
  `notif-service-type-<type>`、`notif-channel-webpush`、`notif-daily-cap`、`notif-quiet-start`、`notif-quiet-end`、
  `notif-save`、`privacy-export`、`privacy-delete`、`inbox-list`、`inbox-message[data-message-id]`、
  `inbox-mark-read`、`inbox-adopt`、`inbox-later`、`inbox-mute`。

自查脚本（无 Playwright 也能跑，使用本机 Chrome + CDP）：

```bash
cd /Users/ee/Documents/deepseek-harness/default-workspace
./.venv/bin/python frontend/scripts/dom_audit.py http://127.0.0.1:5173
# 退出码 0 = 清单里所有 data-testid 都在渲染后的 DOM 中出现
```

---

## 7. 诚实清单：什么是 mock、什么没实现

**是 mock / 演示数据**

- 模型：`MODEL_MODE=mock` 使用确定性编排与 fixtures，**不声称真实模型能力**；`live` 未配置密钥时如实显示不可用。
- 识别/OCR：mock 只识别内置演示截图样本（`data/fixtures/imports/demo_order_screenshot_1|2.png`），
  其他图片返回空候选并提示改用手动添加，**不编造识别结果**。
- 天气：`WEATHER_MODE=mock` 的演示快照（含 `high_uv / dry_spell / missing_uv / stale / api_failure /
  beyond_coverage` 场景开关），全部带 `is_demo` 标注。
- 通知：`NOTIFICATION_MODE=in_app`，Web Push 未配置 VAPID，原生推送未实现（P1）。
- 品牌台：只做本地聚合与群体抑制演示，**不存在任何真实外发通道**。
- 客服：`adapter_mode=local_demo`，工单只提交到本地演示工作台，**不代表任何品牌已收到**。
- 产品数据：虚构 DEMO SKU + 少量带真实来源链接的真实 SKU，来源状态逐条标注。

**未实现 / 前端不负责**

- 没有真实登录/注册/OAuth：只有本地演示身份交换（`AUTH_MODE=demo`）。
- 没有多语言（中文优先）、没有暗色主题、没有组件库（手写 CSS）。
- 不做离线确认：断网时确认计划/提交工单会失败并显示错误，不会排队假成功。
- 不缓存个人 API 响应（`/api/` 在 SW 中 network-only）。
- 不在前端持有或展示任何 API 密钥、上传路径或他人数据。
- 计划/工单/图鉴的**任何业务判断都由后端决定**，前端只渲染与触发用户显式确认。

**已知的后端行为（前端已按实际情况处理，未修改 backend/）**

1. **同一浏览器会话内切换身份**会重建令牌，`/me` 与上下文面板随之刷新（这是设计行为）。
2. **重新 seed 数据库后必须重启后端**：如果在 uvicorn 运行期间**删除并重建** `beautycare.db`
   （例如 `scripts/reset_db.sh`），进程会同时持有旧、新两代 SQLite 文件（`lsof` 可见两个 inode），
   于是同一个合法令牌会在 200/401 之间随机跳变。用 `scripts/seed_db.py --force`（同文件内 drop/create）
   或重启后端即可消除。前端为此加了一次 401 原样重试（250ms），避免把一次噪声当成「被登出」。
3. `POST /admin/scheduler/tick` 与 `POST /admin/proactive/evaluate` 在**代码修复前**曾对
   「户外活动 + 有效 UV」路径抛 `TypeError: can't subtract offset-naive and offset-aware datetimes`
   （`app/services/triggers.py` → `proactive_service.create_message`，HTTP 500 / `INTERNAL_ERROR`）。
   重启后端加载当前代码后不再复现：现在户外路径返回 `suppress / ENVIRONMENT_UNAVAILABLE`，
   旅行路径可以正常产出消息。若要让收件箱有演示消息，可用：授权 `travel_support` → 建一条
   `trip` 活动（约 30 小时后开始）→ `POST /admin/proactive/evaluate`。
4. `POST /handoffs/drafts` 要求 `record_ids` 至少一条（否则 422「请至少选择一条要包含的记录」），
   界面已禁用按钮并给出提示。
5. 已完成验收的接口行为：接受计划带 `expected_version`，冲突返回 `409 VERSION_CONFLICT`
   （`{code,message,retryable,details}`），前端原样展示 code 与「不可重试」。

---

## 8. 目录结构

```
frontend/
  index.html                  # lang=zh-CN、theme-color、manifest、apple-touch-icon
  vite.config.ts              # base "/"、build→dist/、dev 代理 /api → 127.0.0.1:8000
  tsconfig.json               # strict + noUnusedLocals/Parameters
  pnpm-workspace.yaml         # pnpm 11 设置：allowBuilds(esbuild) + rollup→wasm 覆盖
  public/
    manifest.webmanifest  sw.js  icons/*.png
  scripts/
    make_icons.py             # 用 .venv 的 Pillow 生成 PNG 图标
    dom_audit.py              # Chrome+CDP 渲染后 DOM 的 data-testid 审计
  src/
    main.tsx App.tsx styles.css vite-env.d.ts
    api/{client.ts,endpoints.ts,types.ts}
    state/{SessionContext.tsx,useAsync.ts}
    lib/{format.ts,labels.ts}
    components/{Layout.tsx,ServiceContextPanel.tsx,PersonaSwitcher.tsx,Citations.tsx,
                ReviewPromptInline.tsx,ui.tsx,cards/TurnCards.tsx}
    pages/  (14 个路由页面)
```

### 关于 `rollup` 的 WASM 覆盖

本机 Node 启用库校验（library validation），会拒绝 `dlopen` rollup 的原生二进制
（ad-hoc 签名与 Node 进程 Team ID 不一致 → `ERR_DLOPEN_FAILED`）。因此 `pnpm-workspace.yaml` 里把
`rollup` 覆盖为官方同版本 WASM 构建 `@rollup/wasm-node@4.64.6`。这是同一份 rollup，只是不用原生绑定，
无需任何权限提升；在没有该限制的机器上可以删除这段 `overrides`。
