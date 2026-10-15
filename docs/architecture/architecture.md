# 架构与契约

## 1. 总览

模块化单体：一个编排 Agent + 确定性服务。模型只负责意图理解、候选提取、追问与文案；
数据库状态、权限、引用有效性与写入门禁全部由服务端决定。

```text
前端 (React PWA)
   │  已授权 API（Bearer 令牌 → 服务端会话；body 不接受 user_id）
   ▼
FastAPI 路由层  backend/app/api/*
   │
   ├─ 认证/隔离      auth/sessions.py            → AuthContext(tenant_id, user_id, role)
   ├─ 领域服务       services/*                  → 记忆、计划、图鉴、工单、通知、隐私…
   ├─ 知识检索       knowledge/service.py        → BM25 + 产品/版本精确过滤 + 引用校验
   ├─ 环境           environment/service.py      → 地点、活动、环境快照、时效
   └─ Agent 编排     agent/orchestrator.py
            │  1) plan:  intent + 只读工具请求 + 仅草稿写入请求
            │  2) 执行只读工具（≤ MAX_TOOL_CALLS_PER_TURN）
            │  3) 执行草稿写入（SAVEPOINT 保护）
            │  4) compose: 回答 / 追问 / 记忆提议 / 引用
            │  5) 服务端校验（引用、归属、措辞、是否声称未发生的写入）
            │  6) 允许一次修复；仍失败 → 明确失败，SAVEPOINT 回滚
            ▼
      持久化 (SQLAlchemy) + 事件 (AuditEvent) + AgentRun
            ▼
      调度器 (scheduler/loop.py) → 触发评估 → 决策 → 事务 outbox → 渠道适配器
```

**关键不变量**

1. 模型的输出永远不被信任为事实：引用必须能在库里解析为 approved 且版本匹配的 chunk。
2. 写工具（接受计划、提交工单、删除记忆、发送通知）不由模型执行；只由用户确认 API 或后端策略执行。
3. 每用户最多一份 `active` 计划，由数据库部分唯一索引保证。
4. 上传内容、检索内容、工具返回内容都是**数据**，不是指令。
5. 跨所有者访问统一 404，不泄露资源是否存在。

## 2. 数据模型（40 张表）

所有用户业务表包含 `tenant_id`、`user_id`、UUID 主键、`created_at`/`updated_at`；
所有时间列使用 `UTCDateTime`（写入/读取都保证 aware UTC，按用户时区展示）。

### 2.1 身份与目录

| 表 | 关键字段 |
|---|---|
| `tenants` | name, kind |
| `users` | tenant_id, email, display_name, role(consumer/staff/brand), timezone, consent_flags, is_demo |
| `user_sessions` | user_id, token_hash(sha256), kind(demo/…), persona_code, revoked_at |
| `catalog_products` | brand, name, category, region, variant, formula_version, size, aliases, verification_status(demo_fictional/real_verified), is_demo |
| `knowledge_sources` | catalog_product_id, source_type, title, publisher, url/file_ref, region, applies_to_variant, retrieved_at, reviewed_at, status(pending/approved/revoked), content_hash, approval_note, conflict_group, is_demo |
| `knowledge_chunks` | source_id, catalog_product_id, locator, heading, text, claim_types[], structured(JSON), content_hash |
| `ingredient_profiles` | inci_name, common_name, known_effects[{text,source_id}], irritant_level, irritant_notes[], life_extensions[{kind,text,source_id}], source_ids[], approval_status(approved/pending/pending_review/insufficient), conflict_flag |
| `user_ingredient_signals` | user_id, ingredient_id, signal_type(positive/negative), event_count, contributing_event_ids[], computed_at, invalidated_at, invalidation_reason |
| `cities` | city_id, name_zh/en, country, timezone, lat/lon, forecast_days |
| `system_settings` | key(text PK), value(JSON) — 时钟覆盖、天气场景 |
| `fixed_job_locks` | name(PK), owner, locked_until — 调度器单行租约 |

### 2.2 用户业务数据

| 表 | 关键字段 |
|---|---|
| `owned_products` | catalog_product_id?, custom_name, match_status, purchase/opened/expiry_date?, expiry_source, pao_months?, lifecycle_status(unopened/opened/finished/discarded/unknown), usage_status(active/paused/unknown), key_actives[], irritant_flags[], ingredient_source_status, review_flag, version |
| `import_batches` | file_hash, storage_key, mime, status(uploaded/processing/ready/confirmed/failed/expired), candidates[], raw_text, provider_mode, expires_at, file_deleted_at, created_owned_ids[], idempotency_key |
| `conversations` / `messages` | session, role, content, sequence, run_id, cards[], citations[], redacted_at, redaction_scope |
| `memory_records` | kind(confirmed_fact/explicit_preference/user_report/model_hypothesis/business_fact), key, value, provenance_type, source_ref, source_excerpt, valid_from/to, status(active/superseded/pending_confirmation/deleted), supersedes_id/superseded_by_id, version |
| `usage_events` | owned_product_ids[], reported_text, occurred_at?, time_precision(unknown/day/exact/approximate), event_type(positive/negative/neutral/uncertain), provenance=user_report, severity, escalated, ingredient_snapshot[], source_message_id |
| `ingredient_feedback` | ingredient_id, statement, provenance_type, status |
| `ingredient_atlas_views` | version, min_events, payload(JSON), signal_ids[], generated_at, status(current/stale) |
| `review_prompts` | usage_event_id, plan_id, owned_product_id, question, options[], status(open/resolved/dismissed), decision, resulting_plan_id |
| `routine_plans` | version, status(draft/active/superseded/rejected/stale), parent_id, input_snapshot_hash, reasons[], diff, pending_products[], combination_notes[], uncertainties[], needs_review, accepted_at |
| `routine_steps` | plan_id, period, position, owned_product_id, label, instruction, frequency, basis, citation_ids[], review_flag |
| `followup_tasks` | purpose, related_entity_id, scheduled_at, status(pending/sent/done/cancelled/expired), consent_ref |
| `service_tickets` | status(draft/submitted/awaiting_user/in_review/resolved/cancelled), summary(JSON), included_record_ids[], adapter_mode(local_demo), external_id, next_action, user_confirmed_resolution, version |
| `ticket_events` | ticket_id, actor_role, action, from/to_status, note |
| `agent_runs` | intent, model_mode/provider/name, prompt_version, tool_events[], validation_result, latency_ms, usage_metadata, error_code, idempotency_key, repair_attempts, response(JSON) |
| `audit_events` | actor_user_id, actor_role, action, entity_type/id, meta(JSON) — **不含原文** |
| `brand_insight_drafts` | category(source_gap/service_gap/explicit_product_request/feature_request), summary, evidence_refs[], explicitness(explicit/inferred), user_consent, review_status, mode, brand_scope, occurrence_count |
| `location_preferences` | city_id, timezone, lat/lon, purpose(home/travel), provenance(manual/device_precise), consent_ref, version, is_active |
| `activities` | activity_type(outdoor/trip), starts_at, ends_at, destination_city_id, user_confirmed, status(planned/cancelled/completed/expired), version |
| `environment_snapshots` | provider, mode(mock/live), kind(current/forecast), issued_at, fetched_at, valid_from/to, timezone, units, metrics(可空), quality(ok/partial/unavailable/stale), missing_fields[], is_demo |
| `trigger_rules` | service_type, conditions(JSON), threshold_source(demo_rule/…), approval_status(demo/approved), cooldown_minutes, min_interval_minutes, version |
| `notification_preferences` | service_types[], channels[], daily_cap, quiet_hours_start/end, timezone, consent_version, marketing_opt_in, external_push_enabled, muted_service_types[], version |
| `push_subscriptions` | device_id, platform, endpoint_encrypted, keys_encrypted, status(active/revoked/expired/failed) |
| `proactive_decisions` | event_id, service_type, outcome(send/defer/suppress/ask), reason_codes[], context_refs[], snapshot_id, rule_version, plan_version, citation_ids[], expires_at, channel, mode, defer_until |
| `service_messages` | decision_id, kind(service/marketing), title, body, payload(JSON), source_refs[], plan_version, status(draft/approved/queued/sent/expired/cancelled/read), read_at, idempotency_key(unique) |
| `notification_outbox` | message_id, channel, idempotency_key(unique), attempts, max_attempts, next_attempt_at, status(pending/processing/provider_accepted/failed/cancelled/expired), lease_owner, lease_expires_at, expires_at |
| `notification_deliveries` | outbox_id, channel, attempt, status, provider_id, error, provider_confirmed_receipt |
| `message_feedback` | message_id, action(read/adopt_intent/reject/later/not_helpful/mute_type), occurred_at |

## 3. 状态机

**RoutinePlan**：`draft → active → superseded`；`draft → rejected`；任何已接受版本在引用失效时只标记
`needs_review`（不静默改写）。接受时的校验：`status == draft`、`expected_version` 匹配、
所有步骤的产品仍可用、所有引用仍 approved 且版本匹配；否则 409 `STALE_DRAFT` 或 `VERSION_CONFLICT`。

**ServiceTicket**：`draft → submitted → {in_review|awaiting_user|resolved|cancelled}`；
客服 `resolved` 不代表用户已确认解决（`user_confirmed_resolution` 独立存储）。

**ServiceMessage**：`draft → approved → queued → sent → read`，任意阶段可 `cancelled`/`expired`。

**NotificationOutbox**：`pending → processing → provider_accepted | failed | cancelled | expired`；
重试最多 `max_attempts=3`，退避 1/5/15 分钟，超过 `expires_at` 立即过期且**不补发**。

**OwnedProduct**：`lifecycle_status = unopened/opened/finished/discarded` 与
`usage_status = active/paused/unknown` 正交；暂停不等于未开封；新购另一瓶是新实例。

**到期日期规则**：包装日期/用户确认日期为来源；PAO **仅当**开封日期与包装 PAO 月数都已知时计算；
实际失效取所有已知约束中最早者；来源缺失时显示未知，绝不按品类猜测。

**ReviewPrompt**：`open → resolved(decision=pause|keep|adjust)`；`pause` 只产生草稿。

## 4. Agent 工具契约

只读工具（模型可按名请求，参数按 schema 校验，单轮 ≤ `MAX_TOOL_CALLS_PER_TURN`）：
`get_user_context`、`search_catalog`、`get_product_sources`、`list_owned_products`、
`get_active_routine`、`get_service_status`、`extract_ingredients`、`build_ingredient_atlas`、
`get_ingredient_profile`、`search_knowledge`、`get_environment`、`get_user_activities`、
`get_notification_status`。

仅草稿写入（编排器执行，SAVEPOINT 保护）：
`draft_routine`、`record_usage_event`、`draft_handoff`、`create_followup`、
`draft_brand_feedback`、`propose_proactive_service`。

**模型不可调用**（只能由用户确认 API 或后端策略触发）：
`accept_routine`、`submit_handoff`、`DELETE /memories/{id}`、`DELETE /usage-events/{id}`、
`POST /push-subscriptions`、`PATCH /staff/tickets/{id}`、以及任何真实发送动作。

## 5. 引用与资料有效性

- 只有 `status=approved` 且产品/变体/版本匹配的来源可用于建议。
- 每条计划步骤、每条组合提示、每条主动服务卡片都必须有解析成功的 `citation_ids`。
- 引用校验包含：chunk 存在、来源 approved、产品版本一致。
- 冲突来源（同一 `conflict_group`）使相关确定性建议暂停，成分进入 `pending_review`。
- 用户上传截图不进入 approved 知识，只能证明「用户上传了这段内容」。

## 6. 成分图鉴契约

- 生成时机：用户主动 `GET /ingredients/atlas` 时；**不自动推送**。
- 信号：只统计 `provenance=user_report` 的 `UsageEvent`；同一成分关联事件 ≥ `ATLAS_MIN_EVENTS` 才展示。
- 措辞：只允许「出现了 N 次」「有统计关联，但不代表因果关系」；
  禁止「过敏 / 导致 / 避免XX成分」；由 `assert_allowed_wording()` 在生成时校验。
- 卡片必填项：成分名（通俗+INCI）、事件计数、不确定性说明、免责声明；
  功效/致敏性/生活延伸在**有已审核来源时**才展示，否则为「暂无充分信息」或「信息存在冲突，待审核」。
- 生活延伸：必须有 approved 来源且与功效/致敏性直接相关，并标注
  「此延伸基于已审核来源，非个人诊断」；被丢弃的延伸进入 `dropped_life_extensions` 审计列表。
- 删除联动：删除 `UsageEvent` → 依赖它的 `UserIngredientSignal` 立即失效 → 图鉴按需重建。

## 7. 主动服务决策契约

必须**同时**满足才可能 `send`：
用户已授权该服务类型 → 未被静音 → 活动未被取消 → 环境快照存在且新鲜（`issued_at` 在
`WEATHER_MAX_AGE_MINUTES` / `WEATHER_FORECAST_MAX_AGE_MINUTES` 内）→ 引用的产品资料 approved →
未引用暂停/用完的产品 → 未过期 → 未重复（幂等键）→ 未处于冷却 → 未超过每日上限 → 不处于免打扰。

输出包含 `outcome`、`reason_codes`、`context_refs`、`environment_snapshot_id`、`rule_version`、
`plan_version`、`citation_ids`、`expires_at`、`channel`、`mode`；抑制原因可审计。
免打扰内「延后仍有用」→ `defer`（带 `defer_until`），否则 `suppress`。
天气阈值来自版本化 `TriggerRule`，逐条标注 `threshold_source=demo_rule` 与 `approval_status=demo`。

## 8. 错误契约

统一格式 `{code, message, retryable, details, run_id}`。

| code | HTTP | 含义 |
|---|---|---|
| `UNAUTHORIZED` / `FORBIDDEN` | 401 / 403 | 未认证 / 角色不足 |
| `NOT_FOUND` | 404 | 不存在**或**不属于当前用户（不泄露存在性） |
| `VALIDATION_ERROR` | 422 | 请求参数不合法 |
| `VERSION_CONFLICT` | 409 | `expected_version` 不匹配或对象已被处理 |
| `STALE_DRAFT` | 409 | 接受时产品状态或资料来源已失效，需复核 |
| `SOURCE_MISSING` | 422 | 引用不存在 / 未审核 / 版本不符 |
| `SOURCE_CONFLICT` | 409 | 资料冲突，确定性建议暂停 |
| `UNKNOWN_PRODUCT` | 422 | 未匹配到目录产品 |
| `IMPORT_FAILED` | 422 | 上传校验或识别失败 |
| `MODEL_UNAVAILABLE` | 503 | live 模式未配置凭据、超时或提供方错误 |
| `INVALID_MODEL_OUTPUT` | 502 | 模型输出未通过 schema/引用/一致性校验 |
| `ENVIRONMENT_UNAVAILABLE` | 503 | 环境提供方失败 |
| `NOT_CONFIGURED` | 501 | 请求了未配置的渠道（如未配置 VAPID 的 Web Push） |
| `RATE_LIMITED` | 429 | 频次限制 |

## 9. API

完整契约见 [`openapi.json`](openapi.json)（由 `app.openapi()` 生成，共 70 条路径）。
命名空间 ` /api/v1`：

- 身份：`GET /health`、`GET /meta`、`POST /auth/demo-session`、`GET /me`
- 入柜：`POST|GET /imports`、`GET /imports/{id}`、`POST /imports/{id}/confirm`、
  `GET|POST /owned-products`、`GET|PATCH|DELETE /owned-products/{id}`、
  `GET /catalog/search`、`GET /catalog/{id}`、`GET /sources/{id}`
- 计划：`GET /routines`、`GET /routines/{id}`、`POST /routines/drafts`、
  `POST /routines/{id}/accept`、`POST /routines/{id}/restore`、
  `GET /review-prompts`、`POST /review-prompts/{id}/decision`
- 对话：`POST /chat/messages`、`GET /chat/sessions`、`GET /chat/sessions/{id}/messages`
- 记忆与反馈：`GET /memories`、`GET|PATCH|DELETE /memories/{id}`、
  `GET|POST /usage-events`、`DELETE /usage-events/{id}`
- 图鉴：`GET /ingredients/atlas`、`GET /ingredients/atlas/latest`、`GET /ingredients/{id}`、
  `POST /ingredients/feedback`、`GET|DELETE /ingredient-feedback/{id}`、
  `GET /combinations`、`POST /combinations/choice`
- 客服：`GET /handoffs/candidates`、`POST /handoffs/drafts`、`POST /handoffs/{id}/submit`、
  `GET /tickets`、`GET /tickets/{id}`、`POST /tickets/{id}/resolution`、
  `GET /staff/tickets`、`GET|PATCH /staff/tickets/{id}`
- 环境：`GET /cities`、`GET|PUT /location-preferences`、`GET|POST /activities`、
  `PATCH|DELETE /activities/{id}`、`GET /environment`、`GET /environment/forecast-for`、
  `GET /trigger-rules`
- 通知：`GET|PUT /notification-preferences`、`GET|POST /push-subscriptions`、
  `DELETE /push-subscriptions[/{id}]`、`GET /messages`、`POST /messages/{id}/feedback`、
  `GET|POST /followups`、`PATCH /followups/{id}`、`GET /inbox/summary`
- 品牌：`GET|POST /brand-feedback/drafts`、`POST /brand-feedback/{id}/consent`、`GET /brand/insights`
- 隐私与管理：`GET /privacy/export`、`DELETE /privacy/account-data`、
  `GET|POST /admin/clock`、`GET|POST /admin/weather-scenario`、
  `POST /admin/scheduler/tick`、`GET /admin/scheduler/status`、
  `GET /admin/proactive-decisions`、`POST /admin/proactive/evaluate`、`GET /admin/audit`

`POST` 写操作支持 `Idempotency-Key`（聊天、导入确认、工单提交）；
更新支持 `expected_version`，冲突返回 409。

## 10. 环境变量

见 [`.env.example`](../../.env.example)（含 `MODEL_MODE`、`MODEL_PROVIDER`、`MODEL_NAME`、
`API_BASE`、`API_KEY`、`DATABASE_URL`、`UPLOAD_DIR`、`APP_TIMEZONE`、请求超时、
`WEATHER_*`、`NOTIFICATION_MODE`、VAPID 占位、`SCHEDULER_*`、`QUIET_HOURS`、`SERVICE_DAILY_CAP`、
`ATLAS_MIN_EVENTS`、`BRAND_MIN_COHORT`）。密钥只由后端读取。
