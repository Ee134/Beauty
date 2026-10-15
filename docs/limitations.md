# 已知限制与未完成内容

> 本文件是如实清单。**没有实测过的能力不会被写成已完成**；
> 需要凭据、账号或外部合同的能力全部列在下文，并说明接入条件。

## 1. 交付形态

| 项目 | 状态 | 说明 |
|---|---|---|
| 可安装 PWA（manifest + service worker + 图标 + 深链接） | 已实现 | Android/桌面 Chromium 可安装；iOS 需手动「添加到主屏幕」 |
| 原生 iOS / Android App | **未交付（P1）** | 不存在原生客户端；本项目任何位置都不得表述为已交付原生 App |
| 原生推送（APNs / FCM） | **未实现（P1）** | 只有 PWA Web Push 适配器与 mock 渠道 |
| 跨端状态一致 | 已实现 | 状态以服务器为准，各端共享账号、计划、记忆、消息与工单 |
| 离线读写 | 明确禁止 | 离线时禁止确认计划或提交工单；个人 API 响应不写入共享离线缓存 |

## 2. 模型与识别

| 项目 | 状态 | 说明 |
|---|---|---|
| `MODEL_MODE=mock` | 已实现并测试 | 确定性规则实现，与 live 共用编排、工具、校验与写入门禁 |
| `MODEL_MODE=live` 适配器 | 已实现，**未实跑** | OpenAI 兼容 `/chat/completions` + JSON schema；无 `API_BASE`/`API_KEY`/`MODEL_NAME` 时返回 `MODEL_UNAVAILABLE`，不会退回 mock。真实调用需要用户提供密钥与模型名 |
| 视觉/OCR | mock 已实现并测试 | mock 只按 sha256 匹配内置演示截图，**不假装识别任意图片**；`VISION_MODE=live` 走模型适配器，同样未实跑 |
| 独立 OCR 供应商 | 未实现 | 适配器接口已预留（`providers/vision.py`） |

## 3. 环境数据

| 项目 | 状态 | 说明 |
|---|---|---|
| `WEATHER_MODE=mock` | 已实现并测试 | 演示场景可切换：`default` / `dry_spell` / `high_uv` / `missing_uv` / `stale` / `api_failure` / `beyond_coverage` |
| `WEATHER_MODE=live`（Open-Meteo） | 已实现，实测结果见评估报告 | 端点固定为配置项，模型不能构造任意 URL（防 SSRF）；需外网 |
| 精确定位 | 仅接口预留 | 需一次性 `consent_ref`；不做持续轨迹跟踪；IP 不作为居住地 |
| 其它天气供应商 | 未实现 | 需按规格锁定响应 schema、超时、限流与许可 |

## 4. 知识与目录

| 项目 | 状态 | 说明 |
|---|---|---|
| 虚构 DEMO SKU | 12 个（`is_demo=true`） | 全部带 DEMO 标识，不含真实配方 |
| 真实 SKU | 3 个（CeraVe / The Ordinary / La Roche-Posay） | URL 与引文为 2026-10-15 实测抓取；**审核人=demo_seed**，不是品牌官方审核；LRP 因美国站 403 使用德国站，区域标为 EU |
| 真实成分资料 | 3 个（Niacinamide / Salicylic Acid / Retinol） | 来源为 NCBI PubChem PUG-View 机器可读端点（HTML 页面被 reCAPTCHA 拦截）；CosIng 在本环境 DNS 不可解析，**未使用** |
| 成分致敏等级 | 由规则映射 | `slightly irritating → low`；GHS `H315 → moderate`；`H317 → high`；无分类 → `unknown`。这些是**工业化学品危害分类汇总**，不等同于化妆品成品结论，已逐条写入 note |
| 检索 | 词法 BM25 + 精确产品/版本过滤 | 未建向量库（规格允许） |
| 20–30 个真实 SKU 扩展 | 未完成（P2 目标） | 不是为了数量而填造内容 |
| 用户上传截图作为知识 | 明确禁止 | 只能证明上传内容，不进入 approved 资料 |

## 5. 功能范围

| 项目 | 状态 |
|---|---|
| 批量导入、真实电商/CRM/OA 接入 | **未实现（P1）**，需合法接口、凭据与业务约束 |
| 过期提醒（PAO 主动提醒） | 仅实现日期计算与「未知」展示；**主动提醒未实现（P1）** |
| 推荐补缺（补货建议） | **未实现（P1）**，且必须标注商业推荐属性 |
| 自动抓取订单、自动购买、自动退款 | **明确不做** |
| 皮肤疾病诊断、功效保证、药物治疗建议 | **明确不做** |
| 自动训练用户数据 / SFT / GRPO | **明确不做** |
| 彩妆、染发、香水 | MVP 不覆盖 |
| 真实品牌外发（需求反馈） | **不存在通道**；只有内部草稿 + 用户同意 + 演示品牌台汇总 |

## 6. 通知

- 应用内消息：已实现并测试。
- Playwright E2E：7 条流程（导入→计划接受、反馈→记忆→版本、交接→客服→进度、图鉴、组合与删除、
  环境触发→inbox、环境缺失展示）已在本机 Chromium 上实跑通过（7 passed / 10.0 s）。
  浏览器二进制安装在仓库内 `.playwright-browsers/`（用户级缓存不可写）。
- Web Push：适配器 + mock 渠道已实现；**真实推送未实测**。需要 `VAPID_PUBLIC_KEY` /
  `VAPID_PRIVATE_KEY`、支持 Push API 的设备与浏览器、用户手势触发的授权。
- 未配置凭据时页面显示「未配置 Web Push / mock 渠道」，**不声称已送达**。
- `provider_accepted` 只表示渠道接受，不表示设备送达、展示或已读；只有供应商能核实回执时才记录 delivered。
- 无法证明远端幂等，因此**不宣称 exactly-once**；重试复用同一 message/delivery id。

## 7. 调度与部署

- 调度器与 API 在同一进程内以 asyncio 循环运行（生产应拆为独立 worker 进程）。
- 单实例通过 `fixed_job_locks` 单行租约互斥；**多实例部署的分布式锁未验证**。
- SQLite 为本地 MVP 数据库；预留 PostgreSQL，但**未在 PostgreSQL 上实测**。
- 未进行负载、并发与容量测试；`P50/P95` 仅为单机 mock 模式下的脚本测量。

## 8. 安全与合规

- 认证：演示模式为服务端固定身份。`AUTH_MODE` 非 `demo` 时演示登录被拒绝，
  但**真实认证（OIDC/密码/风控）未实现**，部署前必须补齐。
- 上传校验：真实格式（Pillow 解码）、10MB、25MP、扩展名与格式一致性、去 EXIF、路径穿越拒绝。
  未做病毒扫描与内容安全审核。
- 提示注入：上传与检索内容按不可信数据处理，检测到指令式文本会记录并提示，
  不改变权限、不执行写入。**未做完备的红队测试**，安全用例集见 `tests/eval/security_scenarios.py`。
- 全量删除：覆盖原文、图片、计划、记忆、事件、工单、任务、通知、地点、行程、订阅、图鉴视图与品牌草稿。
  MVP **不保留备份副本**；若未来加入备份，必须明确保留期限与删除生效时间，不承诺不可实现的即时擦除。
- 日志与审计：审计记录不含原文、联系方式、订单号与上传内容；
  `AgentRun` 只记录元数据与脱敏工具结果。

## 9. 评估与结论边界

- 评估在 **mock 模型模式**下运行，不能外推到真实模型或真实用户。
- 演示数据上的成绩**不代表真实用户效果**；商业试点需另测每单人工处理时间、重复联系率与消费者反馈。
- 复购/留存需要足够观察周期与对照，本 MVP **不承诺任何具体提升百分比**。
- 计费与合作模式（按租户/活跃服务用户/用量）未验证。
- 「用户信号误报率」在自动化中只能做**代理度量**（低于最小样本量的信号是否被展示），
  真实误报率需要人工评估，见评估报告的「无法测量」章节。

## 10. 需要真实接入时补齐的条件

1. **模型**：`API_BASE` / `API_KEY` / `MODEL_NAME`，以及数据出境与供应商条款确认。
2. **推送**：VAPID 密钥对（或原生 APNs/FCM 凭据）与受支持设备实测。
3. **天气**：供应商合同、配额、限流与响应 schema 锁定；当前默认使用 Open-Meteo。
4. **电商/CRM**：合法接口、OAuth/服务账号、订单数据最小化与用户授权记录。
5. **品牌**：目录审核流程、政策版本、品牌联系人、数据共享协议与用户同意书。
6. **认证与合规**：真实身份体系、区域化数据存储、个人信息保护评估、事件响应流程。
7. **内容审核**：真实 SKU 资料必须由品牌或合格审核人签署，替换 `reviewed_by=demo_seed`。


## 11. 实现过程中由自动化测试发现并修复的缺陷

评估与 E2E 用例不只是"跑绿灯"，它们真的找出了产品缺陷。以下缺陷已修复并补上回归测试：

| # | 缺陷 | 影响 | 修复 | 回归测试 |
|---|---|---|---|---|
| 1 | 成分档案标记为 `approved`，但其来源引用无法解析时仍以 `data_status=approved` 输出（且带一个没有引用的致敏等级） | 违反「无来源不得断言」，属硬零指标风险 | `atlas.py` 在功效与致敏性都没有可解析引用时降级为 `insufficient` +「暂无充分信息」，致敏等级置 `unknown` | `tests/unit/test_atlas_and_expiry.py::test_approved_ingredient_without_resolvable_sources_degrades_to_insufficient` |
| 2 | 只按完整产品名匹配，「修护晚霜」无法关联到「澄泉修护晚霜」 | 反馈无法关联产品 → 不生成复核询问 | `resolve_products_from_text` 改为最长后缀匹配（≥3 字），并列时取最长者 | `test_partial_product_names_resolve_to_the_cabinet_item` |
| 3 | 任意「N 元」都被当作预算，例如「帮我退款 1380 元」写成一条 active 预算记忆 | 无关文本变成长期偏好 | 裸金额只有在出现预算/每月/控制在等语境词时才提取 | `test_money_mention_is_not_a_budget_statement` |
| 4 | `routine.preferred_period` 保存了但计划生成从不使用 | 已确认偏好不生效 | 生成草稿时按偏好过滤时段，并在 `reasons` 中列出被移除的步骤（不合并产品） | `tests/ac/test_ac01_22.py::test_ac08b_confirmed_period_preference_is_applied` |
| 5 | 对话无法解析工单号，进度卡片的 `timeline_count` 恒为 0 | 进度回答不完整 | 从消息中提取 UUID / `LOCAL-DEMO-…` 并传给工具；列表分支也返回时间线长度 | `test_ac19b_progress_query_uses_the_real_ticket` |
| 6 | 前端 `Badge` 不透传 `data-testid`（DOM 里根本没有这些钩子） | 关键状态无法被自动化验证 | `ui.tsx` 透传剩余属性 | Playwright flow2/flow5 |
| 7 | 前端待确认动作按钮 `disabled={action.blocked_reason !== null}` 在字段缺省时恒为真 | 「接受草稿」按钮永久不可点 | 改为 `Boolean(action.blocked_reason)` | Playwright flow1 |
| 8 | 在别处（对话复核、组合选择）产生的草稿不会出现在 `/routine` | 用户看不到待接受的草稿 | `/routines` 历史对 draft 也返回步骤；页面回退到历史中最新的 draft | Playwright flow2/flow5 |
