/**
 * BeautyCare 前端类型定义。
 *
 * 请求体类型直接对应 docs/architecture/openapi.json 的 components.schemas；
 * 响应类型对应后端实际返回（openapi.json 中多数路由未声明 response_model，
 * 因此响应体以各 routes_*.py 的真实返回结构为准，并已在本地用 curl 核对）。
 *
 * 全部为本地演示数据；不含任何真实品牌、订单、OCR 或推送通道。
 */

// ---------------------------------------------------------------------------
// 通用
// ---------------------------------------------------------------------------

/** 后端统一错误体：{code,message,retryable,details,run_id}（spec 第 10 节）。 */
export interface ApiErrorBody {
  code: string;
  message: string;
  retryable: boolean;
  details?: Record<string, unknown>;
  run_id?: string;
}

export type ModelMode = "mock" | "live";

/** 演示时钟快照；is_demo_time 为 true 时界面必须显示演示时间横幅。 */
export interface ClockInfo {
  now: string;
  mode: "real" | "demo" | string;
  offset_seconds: number;
  fixed_at: string | null;
  is_demo_time: boolean;
  label: string;
}

export interface Citation {
  citation_id: string;
  source_id: string;
  chunk_id: string;
  product_id: string | null;
  title: string;
  locator: string | null;
  url: string | null;
  file_ref: string | null;
  retrieved_at: string | null;
  reviewed_at: string | null;
  source_type: string | null;
  is_demo: boolean;
  excerpt: string | null;
}

// ---------------------------------------------------------------------------
// 身份 / me
// ---------------------------------------------------------------------------

export type PersonaCode = "consumer_a" | "consumer_b" | "staff" | "brand";

export interface DemoSessionRequest {
  persona_code: string;
  device_label?: string | null;
}

export interface DemoSessionResponse {
  token: string;
  persona_code: string;
  user: {
    id: string;
    display_name: string;
    role: string;
    timezone: string;
  };
  notice: string;
}

export interface MeResponse {
  user: {
    id: string;
    display_name: string;
    email: string;
    role: string;
    timezone: string;
    consent_flags: Record<string, boolean>;
    is_demo: boolean;
  };
  tenant_id: string;
  mode: {
    model_mode: ModelMode | string;
    model_available: boolean;
    weather_mode: string;
    notification_mode: string;
    auth_mode: string;
  };
  counts: {
    owned_products: number;
    paused_products: number;
    plans: number;
    active_plan_version: number | null;
  };
  notification: {
    service_types: string[];
    channels: string[];
    daily_cap: number;
    quiet_hours: [string, string];
    timezone: string;
  };
  clock: ClockInfo;
  notice: string;
}

export interface HealthResponse {
  status: string;
  app: string;
  env: string;
  auth_mode: string;
  model: { mode: string; available: boolean; is_mock: boolean };
  weather: { mode: string; provider: string };
  notification: { mode: string };
  scheduler: { enabled: boolean; interval_seconds: number };
  notice: string;
}

export interface ChannelStatus {
  mode: string;
  in_app: { available: boolean; mode: string };
  web_push: { available: boolean; mode: string; has_vapid: boolean; notice: string };
  native_push: { available: boolean; mode: string; notice: string };
}

export interface MetaResponse {
  model: Record<string, unknown>;
  channels: ChannelStatus;
  clock: ClockInfo;
  personas: string[];
  demo_auth: boolean;
  data_notice: string;
  app: { name: string; timezone: string };
}

// ---------------------------------------------------------------------------
// 美妆柜 / 导入
// ---------------------------------------------------------------------------

export type LifecycleStatus = "unopened" | "opened" | "finished" | "discarded" | "unknown";
export type UsageStatus = "active" | "paused" | "unknown";
export type MatchStatus = "matched" | "low_confidence" | "custom";

/** GET /owned-products 的单项（cabinet_service.serialize）。 */
export interface OwnedProduct {
  id: string;
  catalog_product_id: string | null;
  custom_name: string;
  match_status: MatchStatus | string;
  purchase_date: string | null;
  opened_date: string | null;
  expiry_date: string | null;
  expiry_source: string;
  pao_months: number | null;
  effective_expiry: string | null;
  effective_expiry_source: string;
  expiry_unknown_reason: string | null;
  lifecycle_status: LifecycleStatus | string;
  usage_status: UsageStatus | string;
  size: string | null;
  key_actives: string[];
  irritant_flags: string[];
  ingredient_source_status: string;
  review_flag: boolean;
  review_note: string | null;
  notes: string | null;
  provenance: string;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface OwnedProductListResponse {
  products: OwnedProduct[];
  notice: string;
}

export interface ExpiryCandidate {
  value: string | null;
  source: string;
  label: string;
}

export interface OwnedProductDetail extends OwnedProduct {
  expiry_assessment: {
    effective_expiry: string | null;
    source: string;
    unknown_reason: string | null;
    candidates: ExpiryCandidate[];
  };
  knowledge?: {
    has_approved_sources: boolean;
    error_code: string | null;
    message: string;
  };
  sources: Citation[];
}

/** POST /owned-products 请求体（openapi OwnedProductCreate）。 */
export interface OwnedProductCreate {
  custom_name: string;
  catalog_product_id?: string | null;
  match_status?: MatchStatus;
  purchase_date?: string | null;
  opened_date?: string | null;
  expiry_date?: string | null;
  expiry_source?: "packaging" | "user_confirmed" | "pao_derived" | "unknown";
  pao_months?: number | null;
  lifecycle_status?: LifecycleStatus;
  usage_status?: UsageStatus;
  size?: string | null;
  notes?: string | null;
}

/** PATCH /owned-products/{id}（openapi OwnedProductPatch）。 */
export interface OwnedProductPatch {
  expected_version?: number | null;
  custom_name?: string | null;
  purchase_date?: string | null;
  opened_date?: string | null;
  expiry_date?: string | null;
  expiry_source?: string | null;
  pao_months?: number | null;
  lifecycle_status?: string | null;
  usage_status?: string | null;
  size?: string | null;
  notes?: string | null;
  review_flag?: boolean | null;
  review_note?: string | null;
}

export interface CatalogCandidate {
  catalog_product_id: string;
  brand: string | null;
  name: string;
  category: string | null;
  region: string | null;
  variant: string | null;
  size: string | null;
  verification_status: string | null;
  is_demo: boolean;
  score: number;
  match_reasons: string[];
  has_approved_source: boolean;
}

export interface ImportCandidate {
  raw_name: string;
  brand: string | null;
  quantity: number;
  size: string | null;
  confidence: number;
  match_status: MatchStatus | string;
  catalog_product_id: string | null;
  matched_name: string | null;
  match_reasons: string[];
  candidates: CatalogCandidate[];
  evidence_text: string | null;
  is_demo: boolean;
}

export interface ImportBatch {
  id: string;
  status: string;
  candidates: ImportCandidate[];
  raw_text: string | null;
  provider_mode: string;
  extractor: string | null;
  error_code: string | null;
  file_deleted_at: string | null;
  expires_at: string | null;
  confirmed_at: string | null;
  created_owned_ids: string[];
  low_confidence: boolean;
  retention_hours: number;
  notice: string;
  duplicate_upload?: boolean;
}

export interface ImportListResponse {
  batches: ImportBatch[];
}

/** POST /imports/{id}/confirm 的单项（openapi ConfirmImportItem）。 */
export interface ConfirmImportItem {
  raw_name?: string | null;
  custom_name?: string | null;
  catalog_product_id?: string | null;
  quantity: number;
  size?: string | null;
  match_status: MatchStatus;
  purchase_date?: string | null;
  opened_date?: string | null;
  lifecycle_status: Exclude<LifecycleStatus, "unknown"> | "unknown";
}

export interface ConfirmImportResponse {
  batch_id: string;
  status: string;
  created: OwnedProduct[];
  duplicate: boolean;
}

export interface CatalogSearchResponse {
  candidates: CatalogCandidate[];
  notice: string;
}

export interface SourceDetail {
  id: string;
  title: string;
  publisher: string | null;
  source_type: string | null;
  url: string | null;
  file_ref: string | null;
  region: string | null;
  status: string;
  is_demo: boolean;
  retrieved_at: string | null;
  reviewed_at: string | null;
  approval_note: string | null;
  conflict_group: string | null;
  chunks: Array<{
    id: string;
    locator: string | null;
    heading: string | null;
    text: string;
    claim_types: string[] | null;
    is_demo: boolean;
  }>;
  notice: string;
}

// ---------------------------------------------------------------------------
// 计划 / 复核
// ---------------------------------------------------------------------------

export interface RoutineStep {
  id: string;
  plan_id: string;
  period: string;
  position: number;
  owned_product_id: string | null;
  catalog_product_id: string | null;
  label: string;
  instruction: string;
  frequency: string | null;
  basis: string;
  citation_ids: string[];
  citations: Citation[];
  review_flag: boolean;
  review_note: string | null;
  is_general_advice: boolean;
}

export interface CombinationNoteRecord {
  type: string;
  ingredient_inci?: string | null;
  owned_product_ids?: string[];
  product_names?: string[];
  text: string;
  options?: string[];
  citation_ids?: string[];
  decided_by_system?: boolean;
}

export interface RoutinePlan {
  id: string;
  version: number;
  status: "draft" | "active" | "superseded" | "rejected" | "stale" | string;
  parent_id: string | null;
  trigger: string;
  reasons: Array<{ type?: string; text: string; citation_ids?: string[] }>;
  diff: Record<string, unknown>;
  pending_products: Array<Record<string, unknown>>;
  combination_notes: CombinationNoteRecord[];
  uncertainties: string[];
  needs_review: boolean;
  needs_review_reason: string | null;
  model_mode: string;
  accepted_at: string | null;
  superseded_at: string | null;
  created_at: string;
  input_snapshot_hash: string;
  steps: RoutineStep[];
}

export interface RoutineListResponse {
  active: RoutinePlan | null;
  history: RoutinePlan[];
  notice: string;
}

export interface RoutineDraftResponse {
  plan: RoutinePlan | null;
  questions: Question[];
  pending_products: Array<Record<string, unknown>>;
  combination_notes: CombinationNoteRecord[];
  skipped_combination: Array<Record<string, unknown>>;
  uncertainties: string[];
  notice: string;
}

export interface AcceptRoutineResponse {
  plan: RoutinePlan;
  notice: string;
}

export interface ReviewPromptRecord {
  id: string;
  question: string;
  options: string[];
  status: string;
  decision: string | null;
  owned_product_id: string | null;
  plan_id: string | null;
  resulting_plan_id: string | null;
  created_at: string;
}

export interface ReviewPromptListResponse {
  prompts: ReviewPromptRecord[];
  notice: string;
}

export interface ReviewDecisionRequest {
  action: "pause" | "keep" | "adjust";
  expected_version?: number | null;
  note?: string | null;
}

export interface ReviewDecisionResponse {
  action: string;
  plan_changed: boolean;
  message?: string;
  questions?: Question[];
  plan_id?: string | null;
  plan_version?: number | null;
  plan?: RoutinePlan;
  prompt: { id: string; status: string; decision: string | null };
  notice: string;
}

// ---------------------------------------------------------------------------
// 对话标准输出（backend/app/schemas/turn.py）
// ---------------------------------------------------------------------------

export interface Question {
  key: string;
  question: string;
  why: string | null;
  options: string[];
}

export interface StepOut {
  id: string | null;
  period: string;
  position: number;
  owned_product_id: string | null;
  label: string;
  instruction: string;
  frequency: string | null;
  basis: string;
  citation_ids: string[];
  review_flag: boolean;
  review_note: string | null;
  is_general_advice: boolean;
}

export interface RoutineDraftCard {
  type: "routine_draft";
  entity_id: string;
  version: number;
  status: string;
  step_count: number;
  diff_summary: string | null;
  pending_count: number;
  combination_note_count: number;
  question_count: number;
}

export interface RoutinePlanCard {
  type: "routine_plan";
  entity_id: string;
  version: number;
  status: string;
  steps: StepOut[];
  pending_products: Array<Record<string, unknown>>;
  combination_notes: Array<Record<string, unknown>>;
  uncertainties: string[];
}

export interface ImportCandidatesCard {
  type: "import_candidates";
  entity_id: string;
  status: string;
  candidate_count: number;
  low_confidence: boolean;
  provider_mode: string;
  notice: string;
}

export interface OwnedProductCard {
  type: "owned_product";
  entity_id: string;
  name: string;
  usage_status: string;
  lifecycle_status: string;
  ingredient_source_status: string;
  effective_expiry: string | null;
  expiry_unknown_reason: string | null;
}

export interface MemoryRecordCard {
  type: "memory_record";
  entity_id: string;
  kind: string;
  key: string;
  value: unknown;
  status: string;
  label: string | null;
  provenance_type: string | null;
  requires_confirmation: boolean;
}

export interface ReviewPromptCard {
  type: "review_prompt";
  entity_id: string;
  question: string;
  options: string[];
  owned_product_id: string | null;
  plan_version: number | null;
}

export interface TicketCard {
  type: "service_ticket";
  entity_id: string;
  status: string;
  adapter_mode: string;
  next_action: string | null;
  notice: string | null;
}

export interface ServiceStatusCard {
  type: "service_status";
  entity_id: string | null;
  ticket_id: string | null;
  status: string | null;
  found: boolean;
  timeline_count: number;
  next_action: string | null;
}

export interface EnvironmentCard {
  type: "environment";
  entity_id: string | null;
  city_name: string;
  city_id: string;
  quality: string;
  mode: string;
  kind: string;
  issued_at: string | null;
  valid_to: string | null;
  metrics: Record<string, unknown>;
  missing_fields: string[];
  notice: string | null;
}

export interface CombinationNoteCard {
  type: "combination_note";
  entity_id: string | null;
  ingredient_inci: string | null;
  text: string;
  citation_ids: string[];
  options: string[];
  decided_by_system: boolean;
}

export interface IngredientCard {
  type: "ingredient";
  entity_id: string;
  inci_name: string;
  common_name: string;
  data_status: string;
  data_note: string | null;
}

export interface AtlasCard {
  type: "ingredient_atlas";
  entity_id: string | null;
  version: number | null;
  card_count: number;
  below_threshold_count: number;
  pending_count: number;
  notice: string;
}

export interface AuditSummaryCard {
  type: "audit_summary";
  entity_id: string | null;
  headline: string;
  items: string[];
}

export interface ProactiveMessageCard {
  type: "proactive_message";
  entity_id: string;
  title: string;
  body: string;
  reason_codes: string[];
  channel: string | null;
  expires_at: string | null;
  decision_outcome: string;
}

export interface TravelChecklistCard {
  type: "travel_checklist";
  entity_id: string;
  activity_id: string;
  title: string;
  items: string[];
  unknown_days: string[];
  notice: string | null;
}

export interface ErrorCard {
  type: "error";
  entity_id: string | null;
  code: string;
  message: string;
  retryable: boolean;
  manual_path: string | null;
}

/** cards 是 discriminated union（discriminator = type）。 */
export type TurnCard =
  | RoutineDraftCard
  | RoutinePlanCard
  | ImportCandidatesCard
  | OwnedProductCard
  | MemoryRecordCard
  | ReviewPromptCard
  | TicketCard
  | ServiceStatusCard
  | EnvironmentCard
  | CombinationNoteCard
  | IngredientCard
  | AtlasCard
  | AuditSummaryCard
  | ProactiveMessageCard
  | TravelChecklistCard
  | ErrorCard;

export type PendingActionType =
  | "accept_routine"
  | "submit_handoff"
  | "confirm_import"
  | "confirm_memory"
  | "review_routine"
  | "add_owned_product"
  | "open_atlas"
  | "provide_missing_info";

export interface PendingAction {
  type: PendingActionType;
  entity_id: string | null;
  expected_version: number | null;
  label: string;
  blocked_reason: string | null;
}

export interface MemoryChange {
  type: "preference" | "fact" | "user_report" | "correction" | "deletion" | "pending";
  entity_id: string | null;
  key: string | null;
  value: unknown;
  status: string | null;
  description: string | null;
}

export type TurnIntent =
  | "import"
  | "routine"
  | "feedback"
  | "memory"
  | "service"
  | "environment"
  | "travel"
  | "notification"
  | "brand_feedback"
  | "ingredient_atlas"
  | "general"
  | "unsupported";

export interface TurnOutput {
  run_id: string;
  intent: TurnIntent;
  answer: string;
  questions: Question[];
  citations: Citation[];
  cards: TurnCard[];
  memory_changes: MemoryChange[];
  pending_actions: PendingAction[];
  uncertainties: string[];
  mode: ModelMode;
  model_unavailable: boolean;
  validation_errors: Array<Record<string, unknown>>;
  clock: ClockInfo | null;
  tool_calls: Array<Record<string, unknown>>;
}

export interface ChatRequest {
  session_id?: string | null;
  message: string;
  client_context?: Record<string, unknown> | null;
}

export interface ChatResponse {
  session_id: string;
  output: TurnOutput;
  notice: string;
}

export interface ChatSession {
  id: string;
  title: string | null;
  status: string;
  last_message_at: string | null;
}

export interface ChatMessageRecord {
  id: string;
  role: "user" | "assistant" | string;
  content: string;
  sequence: number;
  cards: TurnCard[] | null;
  citations: Citation[] | null;
  run_id: string | null;
  redacted: boolean;
  created_at: string;
}

// ---------------------------------------------------------------------------
// 记忆 / 用户报告
// ---------------------------------------------------------------------------

export interface MemoryRecord {
  id: string;
  kind: string;
  key: string;
  value: unknown;
  label: string | null;
  provenance_type: string | null;
  source_ref: string | null;
  source_excerpt: string | null;
  occurred_at: string | null;
  valid_from: string | null;
  valid_to: string | null;
  status: string;
  confidence: number | null;
  supersedes_id: string | null;
  superseded_by_id: string | null;
  version: number;
  created_at: string;
  is_current: boolean;
}

export interface MemoryListResponse {
  records: MemoryRecord[];
  grouped: Record<string, MemoryRecord[]>;
  notice: string;
}

export interface UsageEventRecord {
  id: string;
  owned_product_ids: string[];
  reported_text: string;
  occurred_at: string | null;
  time_precision: string;
  event_type: string | null;
  provenance: string;
  severity: string | null;
  escalated: boolean;
  ingredient_snapshot: Array<{
    owned_product_id: string;
    catalog_product_id: string | null;
    name: string;
    ingredients: string[];
    ingredient_source_status: string;
  }>;
  source_message_id: string | null;
  created_at: string;
  disclaimer: string;
}

export interface UsageEventCreate {
  reported_text: string;
  owned_product_ids?: string[];
  occurred_at?: string | null;
  time_precision?: "unknown" | "day" | "exact" | "approximate";
  event_type?: "positive" | "negative" | "neutral" | "uncertain" | null;
}

export interface UsageEventCreateResponse {
  event: UsageEventRecord;
  review_prompt: {
    id: string;
    question: string;
    options: string[];
    owned_product_id: string | null;
    plan_id: string | null;
  } | null;
  guidance: unknown;
  notice: string;
}

// ---------------------------------------------------------------------------
// 成分图鉴
// ---------------------------------------------------------------------------

export interface AtlasEffectNote {
  text: string;
  citation: Citation;
}

export interface AtlasUserSignal {
  positive_count: number;
  negative_count: number;
  total_count: number;
  positive_event_ids?: string[];
  negative_event_ids?: string[];
  event_refs?: string[];
  /** 后端给出的关联措辞，前端必须逐字展示，不得改写为因果断言。 */
  statement: string;
  causality_notice: string;
}

export interface AtlasLifeExtension {
  text: string;
  citation?: Citation;
  citation_ids?: string[];
  notice?: string;
}

export interface AtlasCardData {
  ingredient_id: string;
  inci_name: string;
  common_name: string;
  is_demo: boolean;
  data_status: "approved" | "insufficient" | "pending_review" | string;
  approval_status: string | null;
  data_note: string | null;
  known_effects: AtlasEffectNote[];
  irritancy: {
    level: string;
    notes: AtlasEffectNote[];
    has_source: boolean;
  };
  user_signal: AtlasUserSignal | null;
  life_extensions: AtlasLifeExtension[];
  uncertainty: string;
  disclaimer: string;
}

export interface AtlasBelowThresholdEntry {
  ingredient_id: string;
  inci_name: string;
  common_name: string;
  positive_count: number;
  negative_count: number;
  min_events: number;
  message: string;
}

export interface AtlasPendingEntry {
  ingredient_id: string;
  inci_name: string;
  common_name: string;
  reason?: string;
  message?: string;
  [key: string]: unknown;
}

export interface AtlasDroppedLifeExtension {
  ingredient_id: string;
  inci_name: string;
  text: string;
  reason: string;
}

export interface AtlasPayload {
  generated_at: string;
  min_events: number;
  mode: string;
  notice: string;
  disclaimer: string;
  signal_wording_notice: string;
  cards: AtlasCardData[];
  below_threshold: AtlasBelowThresholdEntry[];
  pending: AtlasPendingEntry[];
  dropped_life_extensions: AtlasDroppedLifeExtension[];
  ingredient_feedback: Array<{
    id: string;
    ingredient_id: string;
    statement: string;
    provenance_type: string;
    created_at?: string;
  }>;
  signal_ids: string[];
  stats: {
    card_count: number;
    below_threshold_count: number;
    pending_count: number;
    approved_card_count: number;
    insufficient_card_count: number;
    pending_review_card_count: number;
  };
  view_id: string | null;
  version: number | null;
  refreshed?: boolean;
}

export interface AtlasLatestResponse {
  view: { id: string; version: number; status: string; generated_at: string | null } | null;
  payload?: AtlasPayload;
  notice?: string;
}

export interface IngredientDetail {
  id: string;
  inci_name: string;
  common_name: string;
  categories: string[];
  typical_period: string;
  is_demo: boolean;
  data_status: string;
  approval_status: string | null;
  data_note: string | null;
  known_effects: AtlasEffectNote[];
  irritancy: { level: string; notes: AtlasEffectNote[]; has_source: boolean };
  life_extensions: AtlasLifeExtension[];
  dropped_life_extensions: Array<{ text: string; reason: string }>;
  sources: Record<string, unknown>;
  conflict_note: string | null;
  disclaimer: string;
}

export interface IngredientFeedbackCreate {
  ingredient_id: string;
  statement: string;
  source_message_id?: string | null;
}

export interface IngredientFeedbackRecord {
  id: string;
  ingredient_id: string;
  statement: string;
  provenance_type?: string;
  created_at?: string;
}

// ---------------------------------------------------------------------------
// 组合推理
// ---------------------------------------------------------------------------

export interface CombinationProduct {
  owned_product_id: string;
  name: string;
  ingredient_source_status: string;
  key_actives: string[];
}

export interface CombinationsResponse {
  plan_version: number | null;
  steps: Array<{
    label: string;
    period: string;
    position: number;
    citation_ids: string[];
    review_flag: boolean;
  }>;
  combination_notes: CombinationNoteRecord[];
  products: CombinationProduct[];
  notice: string;
}

export interface CombinationChoiceRequest {
  note_index: number;
  choice: "keep" | "space_out" | "remove_one";
  owned_product_id?: string | null;
}

export interface CombinationChoiceResponse {
  plan_changed: boolean;
  draft_created?: boolean;
  choice: string;
  plan?: RoutinePlan | null;
  notice: string;
  mode?: string;
}

// ---------------------------------------------------------------------------
// 客服 / 工单
// ---------------------------------------------------------------------------

export interface HandoffCandidate {
  id: string;
  type: string;
  label: string;
  occurred_at: string | null;
}

export interface HandoffCandidatesResponse {
  records: HandoffCandidate[];
  notice?: string;
}

export interface TicketTimelineEntry {
  id: string;
  action: string;
  from_status: string | null;
  to_status: string | null;
  note: string | null;
  actor_role: string | null;
  at: string;
}

export interface ServiceTicket {
  id: string;
  status: string;
  summary: Record<string, unknown>;
  included_record_ids: string[];
  adapter_mode: string;
  external_id: string | null;
  next_action: string | null;
  submitted_at: string | null;
  resolved_at: string | null;
  user_confirmed_resolution: boolean | null;
  escalated: boolean;
  version: number;
  created_at: string;
  notice: string;
  timeline?: TicketTimelineEntry[];
}

export interface HandoffDraftResponse {
  ticket: ServiceTicket;
  notice: string;
}

export interface TicketListResponse {
  tickets: ServiceTicket[];
  notice: string;
}

export interface TicketResponse {
  ticket: ServiceTicket;
}

export interface StaffQueueResponse {
  environment: string;
  tickets: ServiceTicket[];
  notice: string;
}

export interface StaffTicketResponse {
  environment: string;
  ticket: ServiceTicket;
  evidence: {
    products: unknown[];
    user_reports: unknown[];
    actions_already_taken: unknown[];
  };
}

// ---------------------------------------------------------------------------
// 环境 / 地点 / 活动
// ---------------------------------------------------------------------------

export interface City {
  city_id: string;
  name_zh: string;
  name_en: string;
  country: string;
  timezone: string;
  latitude: number;
  longitude: number;
  forecast_days: number;
}

export interface LocationPreference {
  id: string;
  city_id: string;
  city_name: string;
  country: string;
  timezone: string;
  latitude: number;
  longitude: number;
  purpose: string;
  provenance: string;
  version: number;
  updated_at: string;
}

export interface EnvironmentSnapshot {
  id: string;
  city_id: string;
  provider: string;
  mode: string;
  kind: string;
  issued_at: string;
  fetched_at: string;
  valid_from: string;
  valid_to: string;
  timezone: string;
  units: Record<string, string>;
  metrics: Record<string, number | string | null>;
  quality: string;
  missing_fields: string[];
  is_demo: boolean;
  error_code: string | null;
  freshness: string;
  age_minutes: number | null;
  max_age_minutes: number;
}

export interface EnvironmentResponse {
  city_id?: string;
  city_name?: string;
  timezone?: string;
  provider?: string;
  mode?: string;
  scenario?: string;
  quality?: string;
  missing_fields?: string[];
  fetched_at?: string;
  notice?: string | null;
  is_demo?: boolean;
  current?: EnvironmentSnapshot | null;
  forecast?: EnvironmentSnapshot[];
  available: boolean;
  location?: LocationPreference | null;
  using_user_city?: boolean;
}

export interface Activity {
  id: string;
  activity_type: string;
  title: string;
  starts_at: string;
  ends_at: string | null;
  destination_city_id: string | null;
  destination_city_name?: string | null;
  origin_city_id?: string | null;
  origin_city_name?: string | null;
  user_confirmed: boolean;
  status: string;
  notes: string | null;
  version: number;
}

export interface ActivityCreate {
  activity_type: "outdoor" | "trip";
  title: string;
  starts_at: string;
  ends_at?: string | null;
  destination_city_id?: string | null;
  origin_city_id?: string | null;
  user_confirmed?: boolean;
  notes?: string | null;
}

export interface TriggerRule {
  service_type: string;
  description: string;
  conditions: Record<string, unknown>;
  threshold_source: string;
  approval_status: string;
  cooldown_minutes: number;
  min_interval_minutes: number;
  version: number;
  notes: string | null;
}

// ---------------------------------------------------------------------------
// 通知 / inbox / 跟进
// ---------------------------------------------------------------------------

export interface NotificationPreferences {
  service_types: string[];
  channels: string[];
  daily_cap: number;
  quiet_hours_start: string;
  quiet_hours_end: string;
  timezone: string;
  consent_version: string;
  marketing_opt_in: boolean;
  external_push_enabled: boolean;
  muted_service_types: string[];
  version: number;
}

export interface NotificationPreferencePatch {
  service_types?: string[] | null;
  channels?: string[] | null;
  daily_cap?: number | null;
  quiet_hours_start?: string | null;
  quiet_hours_end?: string | null;
  timezone?: string | null;
  marketing_opt_in?: boolean | null;
  external_push_enabled?: boolean | null;
  muted_service_types?: string[] | null;
  consent_version?: string | null;
  expected_version?: number | null;
}

export interface NotificationPreferencesResponse {
  preferences: NotificationPreferences;
  channels: ChannelStatus;
  notice: string;
}

export interface PushSubscriptionRecord {
  id: string;
  device_id: string;
  platform: string;
  status: string;
  granted_at: string | null;
  revoked_at: string | null;
}

export interface ServiceMessage {
  id: string;
  kind: string;
  title: string;
  body: string;
  payload: Record<string, unknown> | null;
  source_refs: string[] | null;
  plan_version: number | null;
  status: string;
  read_at: string | null;
  expires_at: string | null;
  created_at: string;
  reason_codes: string[];
  decision_outcome: string | null;
  mode: string;
  notice: string;
}

export interface MessagesResponse {
  messages: ServiceMessage[];
  next_cursor: string | null;
  notice: string;
}

export interface InboxSummaryResponse {
  unread_count: number;
  messages: ServiceMessage[];
  due_followups: Array<{ id: string; title: string; purpose: string }>;
  channels: ChannelStatus;
}

export type MessageFeedbackAction =
  | "read"
  | "adopt_intent"
  | "reject"
  | "later"
  | "not_helpful"
  | "mute_type";

export interface MessageFeedbackResponse {
  message: ServiceMessage;
  notice: string;
}

export interface FollowUp {
  id: string;
  purpose: string;
  title: string;
  detail: string | null;
  status: string;
  scheduled_at: string | null;
  related_entity_id: string | null;
}

// ---------------------------------------------------------------------------
// 品牌台 / 隐私 / 审计 / 管理
// ---------------------------------------------------------------------------

export interface BrandInsightDraft {
  id: string;
  category: string;
  category_label: string;
  summary: string;
  evidence_refs: unknown[];
  explicitness: string;
  user_consent: boolean;
  consent_version: string | null;
  review_status: string;
  mode: string;
  brand_scope: string | null;
  occurrence_count: number;
  created_at: string;
  notice: string;
}

export interface BrandInsightsResponse {
  tenant_id: string;
  mode: string;
  cohort_size: number;
  min_cohort: number;
  suppressed: boolean;
  suppression_notice: string | null;
  groups: Array<{
    category: string;
    category_label: string;
    draft_count: number;
    distinct_users: number;
    consented_count: number;
    explicit_count: number;
    inferred_count: number;
    themes: Array<{ theme: string; count: number }>;
    sample_redacted: Array<{
      summary: string;
      occurrence_count: number;
      review_status: string;
    }>;
  }>;
  totals: { drafts: number; consented: number; explicit: number };
  notice: string;
}

export interface AuditEventRecord {
  id: string;
  action: string;
  actor_role: string | null;
  entity_type: string | null;
  entity_id: string | null;
  meta: Record<string, unknown>;
  at: string;
}

export interface AuditResponse {
  events: AuditEventRecord[];
  notice: string;
}

export interface ProactiveDecisionRecord {
  id: string;
  event_id: string;
  service_type: string;
  outcome: string;
  reason_codes: string[];
  context_refs: string[];
  snapshot_id: string | null;
  rule_version: string | null;
  plan_version: number | null;
  citation_ids: string[];
  channel: string | null;
  mode: string;
  expires_at: string | null;
  created_at: string;
}

export interface WeatherScenarioResponse {
  current: string;
  available: string[];
  description: Record<string, string>;
  notice: string;
}

export interface SchedulerStatusResponse {
  enabled: boolean;
  interval_seconds: number;
  last_tick: string | null;
  outbox: Record<string, number>;
  notice: string;
}
