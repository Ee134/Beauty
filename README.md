# BeautyCare MVP — 基于已购产品、使用记忆与实时环境的主动美妆服务 Agent

版本 1.2 · 对应规格 `BeautyCare_Agent_Spec_v1_2.md`

> **本仓库是本地可运行、可演示、可测试的 MVP，不是生产系统。**
> 所有虚构商品都带 `DEMO` 标识；3 个真实 SKU 附带实测抓取到的官方页面链接与引文；
> 模型默认运行在 **mock 模式**（确定性实现，不声称真实模型能力）。
> 未接入任何真实品牌客服系统、真实订单平台、真实推送服务或原生 App。

---

## 1. 快速开始（5 分钟）

```bash
# 1) 创建虚拟环境、安装锁定依赖、迁移数据库、写入演示数据
./scripts/bootstrap.sh

# 2) 构建前端（可安装 PWA）
cd frontend && pnpm install && pnpm build && cd ..

# 3) 启动（同时提供 API 与前端静态资源）
./scripts/run_server.sh
#    → http://127.0.0.1:8000        消费者/客服/品牌界面
#    → http://127.0.0.1:8000/docs   OpenAPI 文档
#    → http://127.0.0.1:8000/health 健康状态
```

演示身份由服务端固定映射，前端通过 `POST /api/v1/auth/demo-session` 换取令牌：

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/auth/demo-session \
  -H 'Content-Type: application/json' -d '{"persona_code":"consumer_a"}'
# → {"token":"bc_…","persona_code":"consumer_a","user":{…}}
```

四个演示身份：`consumer_a`（反馈积累充分、可触发成分图鉴）、`consumer_b`（反馈样本不足）、
`staff`（本地演示客服台）、`brand`（演示品牌需求面板）。

---

## 2. 技术栈与仓库结构

| 层 | 选型 | 说明 |
|---|---|---|
| 前端 | React + TypeScript + Vite（PWA） | `frontend/`，手写 CSS，无 UI 框架 |
| 后端 | Python 3.12 + FastAPI + Pydantic v2 | `backend/app/`，模块化单体 |
| 持久化 | SQLAlchemy 2.x + Alembic + SQLite | 预留 PostgreSQL（只需替换 `DATABASE_URL`） |
| 测试 | pytest（真实数据库集成）+ Playwright | `tests/`（AC 48 条 + 单元 + 集成 + 评估 + E2E）|
| 模型 | 适配器注入：`mock` / `live`（OpenAI 兼容） | 同一编排与校验流程 |
| 其它适配器 | WeatherProvider / NotificationProvider / VisionProvider / BrandFeedbackAdapter | `backend/app/providers/` |

```text
frontend/src/{pages,components,api,types}
backend/app/{api,auth,models,schemas,services,agent,providers,knowledge,environment,notifications,scheduler,insights}
backend/migrations/
data/{catalog,sources,fixtures}
tests/{unit,integration,ac,e2e,eval}
docs/{architecture,demo,limitations,evaluation}
scripts/
README.md  .env.example
```

> 与规格推荐结构的两点差异（已按规格第 0 节要求记录）：
> 1. 测试统一放在仓库根的 `tests/`（`pytest.ini` 里用 `pythonpath = backend`），而不是 `backend/tests/`；
> 2. 增加了 `tests/ac/`，把 48 条验收准则一一对应成可执行测试。

---

## 3. 配置

复制 `.env.example` 为 `.env`。**密钥只由后端读取，永不返回浏览器。**

关键开关：

| 变量 | 取值 | 含义 |
|---|---|---|
| `MODEL_MODE` | `mock` \| `live` | `mock` 使用确定性 fixtures；`live` 需要 `API_BASE`/`API_KEY`/`MODEL_NAME`，缺一即 `MODEL_UNAVAILABLE`，**不会偷偷退回 mock** |
| `VISION_MODE` | `mock` \| `live` | `mock` 只按文件哈希识别内置演示截图，不假装能读任意图片 |
| `WEATHER_MODE` | `mock` \| `live` | `live` 使用固定 Open-Meteo 端点（无需密钥）；缺失/过时/失败都如实上报 |
| `NOTIFICATION_MODE` | `in_app` \| `mock_push` \| `web_push` | 默认仅应用内；`web_push` 需要 VAPID 凭据 |
| `AUTH_MODE` | `demo` \| 其它 | `demo` 为本地演示身份；部署必须替换为真实认证 |
| `ATLAS_MIN_EVENTS` | 默认 3 | 成分图鉴的最小样本量 |
| `SCHEDULER_ENABLED` / `SCHEDULER_INTERVAL` | 默认 true / 60 | 持久化调度；关闭页面也会继续处理 |
| `SERVICE_DAILY_CAP` / `QUIET_HOURS` | 默认 1 / `22:00-08:00` | 主动服务频次与免打扰 |
| `IMPORT_RETENTION_HOURS` | 默认 24 | 截图确认后的删除时限 |

---

## 4. 常用命令

```bash
./scripts/bootstrap.sh          # 建 venv + 安装依赖 + 迁移 + seed
./scripts/run_server.sh         # 启动 API + 前端（需先构建 frontend/dist）
./scripts/reset_db.sh           # 删除本地数据库与上传文件并重新 seed
./.venv/bin/python -m scripts.seed_db          # 仅 seed（幂等，已存在则跳过）
./.venv/bin/python -m scripts.seed_db --force  # 清空全部表后重新 seed
./.venv/bin/python scripts/make_demo_fixtures.py  # 重新生成内置演示截图

cd backend && ../.venv/bin/alembic -c alembic.ini upgrade head   # 迁移
cd backend && ../.venv/bin/alembic -c alembic.ini downgrade base # 回滚

.venv/bin/python -m pytest tests -q             # 全部测试
.venv/bin/python -m tests.eval.run_eval         # 评估并生成报告
```

---

## 5. 测试

| 目录 | 内容 |
|---|---|
| `tests/ac/` | **AC01–AC48** 逐条验收测试（真实 SQLite 数据库 + 真实 HTTP 调用） |
| `tests/unit/` | 词法检索与引用校验、图鉴措辞规则、到期/PAO、时钟与免打扰、记忆契约与删除血缘、模式诚实性 |
| `tests/integration/` | Alembic `upgrade/downgrade` 往返、完整端到端业务流、幂等、重启持久化 |
| `tests/e2e/` | Playwright 关键流程 1–7（导入→接受计划、反馈→记忆→版本、交接→客服→进度、图鉴、组合与删除、环境触发） |
| `tests/eval/` | 48 个多轮评估场景 + 20+ 安全用例 + 指标计算，输出 `docs/evaluation/report.md` |

```bash
# 后端全部测试（156 项，约 46 秒；含 48 条 AC、单元、集成与评估慢测）
.venv/bin/python -m pytest tests -q

# 只跑验收矩阵 AC01–AC48
.venv/bin/python -m pytest tests/ac -q

# 评估：48 个多轮场景 + 20+ 安全用例 + 指标报告
.venv/bin/python -m tests.eval.run_eval

# Playwright：先在一个终端启动专用 E2E 服务，再在另一个终端跑测试
./scripts/run_e2e_server.sh
./scripts/run_e2e_tests.sh

# 一键复现全部检查（pytest + 评估 + 前端构建 + E2E）
./scripts/check_all.sh
```

**实测结果（本机实跑，非估算）**

| 检查 | 命令 | 结果 |
|---|---|---|
| 后端测试 | `.venv/bin/python -m pytest tests -q` | **156 passed**（46.3 s） |
| 评估（48 场景 + 30 安全用例） | `.venv/bin/python -m tests.eval.run_eval` | **0 失败**；15 项指标全部达标；P50 11.0 ms / P95 36.1 ms（108 轮） |
| Playwright E2E | `./scripts/run_e2e_server.sh` + `./scripts/run_e2e_tests.sh` | **7 passed**（10.0 s） |
| 真实天气 API | `.venv/bin/python scripts/smoke_live_weather.py CN-GZ CN-BJ` | **成功**（Open-Meteo 实测，见 live-integrations.md） |
| 前端构建 | `cd frontend && pnpm build` | **exit 0**（tsc --noEmit + vite build） |

详细数字、分子/分母、失败用例与「无法测量」清单见
[`docs/evaluation/report.md`](docs/evaluation/report.md)；
真实外部接入的实测记录见 [`docs/evaluation/live-integrations.md`](docs/evaluation/live-integrations.md)。

---

## 6. 已实现能力（对应规格 2 与 15 的里程碑）

**闭环**：已有产品入柜 → 组合适用性推理 → 个性化计划 → 反馈事件 → 反馈驱动的计划迭代 →
成分图鉴 → 生活场景延伸 → 连续客服。

- **入柜**：手动添加、截图导入（校验真实格式/像素/扩展名、去 EXIF、同用户按内容哈希去重、
  候选确认前零写入、确认后按保留期删除文件）。
- **计划**：仅用已审核且版本匹配的资料生成步骤；资料不足的产品进入待确认列表且**不参与**组合推理；
  每步带引用；草稿/生效/历史版本；数据库层保证每用户最多一份 active；接受时重新校验（产品状态、资料撤销）。
- **组合推理**：同类活性成分叠加、来源声明的间隔要求、时段分配，**逐条附来源**，
  只呈现“可能增加刺激风险”等有来源表述，不自行判定冲突。
- **记忆**：用户确认事实 / 明确偏好 / 用户报告 / 模型推测（仅待确认假设）/ 业务事实分流；
  修正产生版本链；遗忘会遮盖原文、失效派生摘要与图鉴信号并在重启后保持。
- **反馈迭代**：负面反馈只生成**显式复核询问**，绝不自动暂停或改计划；确认暂停才产生 v+1 草稿。
- **成分图鉴**：`/ingredients/atlas` 主动查看时生成；功效/致敏性/生活延伸必须有已审核来源；
  冲突来源进入待审核不选边；无来源显示「暂无充分信息」；样本不足显示「样本不足」；
  措辞统一为“关联/出现次数”，并提供禁用词的自动检查。
- **主动服务**：地点（手动城市优先，不做轨迹跟踪）、活动/行程（用户确认）、环境快照
  （provider/mode/issued_at/valid_to/units/quality/缺失字段，缺失不用 0 代替）、
  版本化 TriggerRule（阈值来源与审核状态逐条标注）、确定性筛选 → send/defer/suppress/ask + reason_codes、
  频次/免打扰/时区/去重/暂停产品校验。
- **通知管线**：事务 outbox、`user+event+service_type+rule_version+occurrence` 幂等键、
  worker 租约、指数退避且最多 3 次、过期不发、授权撤销后发送前取消；
  `provider_accepted` 永不等于已送达或已读；应用内消息为 P0，Web Push 为可配置渠道（未配置即明确 mock）。
- **调度**：常驻 asyncio 循环 + 单行租约锁 + `POST /api/v1/admin/scheduler/tick`（测试/演示用）；
  重启后继续处理且 inbox 不重复。
- **客服交接**：用户预览选择记录 → 生成草稿 → 确认提交到本地演示工作台；
  明确不声称品牌已收到；解决与否由用户独立确认。
- **品牌需求**：资料缺口/服务缺口/显式需求/功能建议四类内部草稿；显式与推测分列；
  外发需独立同意与审核；品牌台演示聚合在群体 < `BRAND_MIN_COHORT` 时抑制展示；跨租户隔离。
- **安全与隐私**：服务端会话（body 不接受 `user_id`）、越权统一 404、上传内容与检索内容一律当作不可信数据、
  注入检测、导出与全量删除（含上传文件、派生图鉴与通知）、审计不含原文。

---

## 6.1 由测试发现并修复的缺陷

自动化并不只是"跑绿灯"：48 条 AC + 评估 + Playwright 在交付过程中确实找出了 8 个产品缺陷
（图鉴无来源断言、部分产品名无法关联、退款金额被写成预算偏好、时段偏好不生效、
工单进度缺少时间线、前端 testid 丢失、接受草稿按钮恒禁用、别处产生的草稿不可见），
全部已修复并补上回归测试，清单见 [`docs/limitations.md`](docs/limitations.md) 第 11 节。

## 7. 尚未完成 / 需要真实接入条件

详见 [`docs/limitations.md`](docs/limitations.md)。摘要：

- **原生 App**：P1，未交付。只有可安装 PWA，**不得**表述为已交付 iOS/Android 原生应用。
- **真实 Web Push**：适配器与 mock 渠道已完成；真实发送需 VAPID 密钥、受支持设备与实测。
- **真实模型（live）**：适配器与严格 JSON schema 调用已完成；未配置密钥时明确不可用，附有未实跑的说明。
- **真实天气**：`WEATHER_MODE=live` 使用 Open-Meteo；是否有实测结果见评估报告。
- **真实电商/CRM/OA 接入、批量导入、过期提醒、推荐补缺**：P1/P2，未实现。
- **真实品牌外发**：不存在通道，MVP 只做内部草稿与演示汇总。
- **医学相关内容**：不诊断、不建立因果、不提供治疗建议；只做记录、必要询问、暂停草稿与升级到人工。
- **PWA 后台推送在部分设备/浏览器不可用**：按实际能力提示，不承诺所有设备都能后台推送。

---

## 8. 数据与合规声明

- 虚构演示数据：`data/catalog/products.json`、`data/sources/demo_sources.json`、
  `data/sources/demo_ingredients.json`（全部 `is_demo=true`，来源标题含「虚构」）。
- 真实数据：`data/sources/real_sources.json` 中 3 个真实 SKU 与 3 个真实成分，
  URL 与引文为 2026-10-15 实测抓取；**审核由演示种子流程完成（`reviewed_by=demo_seed`），不是品牌官方审核**。
  成分致敏等级映射规则同文件 `_meta.irritancy_mapping_rule`。
- 原始抓取证据：`refdata/`（PubChem 官方 JSON、品牌页面快照与汇总 `result.json`），
  仅作本地来源核验，应用运行时不读取；第三方页面快照不应再分发（见 `refdata/README.md`）。
- 本规格与实现不代表赛事官方要求、品牌授权或医学验证。

## 9. 文档索引

- [`docs/demo.md`](docs/demo.md) — 演示脚本与逐步操作
- [`docs/atlas.md`](docs/atlas.md) — 成分图鉴 API、来源冲突处理说明、生活延伸来源清单
- [`docs/limitations.md`](docs/limitations.md) — 已知限制、未完成项、真实接入条件
- [`docs/architecture/architecture.md`](docs/architecture/architecture.md) — 架构、数据模型、状态机与契约
- [`docs/architecture/openapi.json`](docs/architecture/openapi.json) — 生成的 OpenAPI 契约
- [`docs/evaluation/report.md`](docs/evaluation/report.md) — 评估报告（指标含分子/分母与失败用例）
- [`docs/evaluation/live-integrations.md`](docs/evaluation/live-integrations.md) — 真实天气 API / 来源抓取 / Playwright 安装的实测记录与未实测清单
- `frontend/README.md` — 前端开发、构建与 PWA 安装说明
