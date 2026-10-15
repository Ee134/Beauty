/**
 * 全部后端调用的类型化封装。
 * 路径与请求体来自 docs/architecture/openapi.json（71 个 path），
 * 响应类型来自各 routes_*.py 的真实返回结构（已用 curl 核对）。
 */

import { newIdempotencyKey, request } from "./client";
import type {
  AcceptRoutineResponse,
  Activity,
  ActivityCreate,
  AtlasLatestResponse,
  AtlasPayload,
  AuditResponse,
  BrandInsightDraft,
  BrandInsightsResponse,
  CatalogSearchResponse,
  ChatMessageRecord,
  ChatResponse,
  ChatSession,
  City,
  CombinationChoiceRequest,
  CombinationChoiceResponse,
  CombinationsResponse,
  ConfirmImportItem,
  ConfirmImportResponse,
  DemoSessionResponse,
  EnvironmentResponse,
  FollowUp,
  HandoffCandidatesResponse,
  HandoffDraftResponse,
  HealthResponse,
  ImportBatch,
  ImportListResponse,
  IngredientDetail,
  IngredientFeedbackCreate,
  IngredientFeedbackRecord,
  InboxSummaryResponse,
  LocationPreference,
  MeResponse,
  MemoryListResponse,
  MemoryRecord,
  MessageFeedbackAction,
  MessageFeedbackResponse,
  MessagesResponse,
  MetaResponse,
  NotificationPreferencePatch,
  NotificationPreferencesResponse,
  OwnedProduct,
  OwnedProductCreate,
  OwnedProductDetail,
  OwnedProductListResponse,
  OwnedProductPatch,
  PersonaCode,
  ProactiveDecisionRecord,
  PushSubscriptionRecord,
  ReviewDecisionRequest,
  ReviewDecisionResponse,
  ReviewPromptListResponse,
  RoutineDraftResponse,
  RoutineListResponse,
  RoutinePlan,
  SchedulerStatusResponse,
  ServiceTicket,
  SourceDetail,
  StaffQueueResponse,
  StaffTicketResponse,
  TicketListResponse,
  TicketResponse,
  TriggerRule,
  UsageEventCreate,
  UsageEventCreateResponse,
  UsageEventRecord,
  WeatherScenarioResponse,
  ClockInfo,
} from "./types";

// --- 身份与元信息 -----------------------------------------------------------

export const getHealth = () => request<HealthResponse>("/health", { anonymous: true });

export const getMeta = () => request<MetaResponse>("/meta", { anonymous: true });

/** 演示身份交换：persona_code -> {token,user}。永远不提交 user_id。 */
export const createDemoSession = (persona_code: PersonaCode, device_label?: string) =>
  request<DemoSessionResponse>("/auth/demo-session", {
    method: "POST",
    anonymous: true,
    body: { persona_code, device_label: device_label ?? "web-demo" },
  });

export const getMe = () => request<MeResponse>("/me");

// --- 美妆柜与导入 -----------------------------------------------------------

export const listImports = () => request<ImportListResponse>("/imports");

export const getImport = (batchId: string) => request<ImportBatch>(`/imports/${batchId}`);

/** multipart 上传；字段名为 file（openapi Body_create_import_api_v1_imports_post）。 */
export function createImport(file: File, note?: string): Promise<ImportBatch> {
  const form = new FormData();
  form.append("file", file);
  if (note) {
    form.append("note", note);
  }
  return request<ImportBatch>("/imports", {
    method: "POST",
    formData: form,
    idempotencyKey: newIdempotencyKey(),
  });
}

export const confirmImport = (batchId: string, items: ConfirmImportItem[]) =>
  request<ConfirmImportResponse>(`/imports/${batchId}/confirm`, {
    method: "POST",
    body: { items },
    idempotencyKey: newIdempotencyKey(),
  });

export const listOwnedProducts = (params?: { include_deleted?: boolean; usage_status?: string[] }) => {
  const search = new URLSearchParams();
  if (params?.include_deleted) {
    search.set("include_deleted", "true");
  }
  for (const status of params?.usage_status ?? []) {
    search.append("usage_status", status);
  }
  const query = search.toString();
  return request<OwnedProductListResponse>(`/owned-products${query ? `?${query}` : ""}`);
};

export const createOwnedProduct = (body: OwnedProductCreate) =>
  request<OwnedProduct>("/owned-products", { method: "POST", body });

export const getOwnedProduct = (ownedId: string) =>
  request<OwnedProductDetail>(`/owned-products/${ownedId}`);

export const patchOwnedProduct = (ownedId: string, body: OwnedProductPatch) =>
  request<OwnedProduct>(`/owned-products/${ownedId}`, { method: "PATCH", body });

export const deleteOwnedProduct = (ownedId: string) =>
  request<{ deleted: boolean; id: string; notice: string }>(`/owned-products/${ownedId}`, {
    method: "DELETE",
  });

export const searchCatalog = (q: string, region?: string) => {
  const search = new URLSearchParams({ q });
  if (region) {
    search.set("region", region);
  }
  return request<CatalogSearchResponse>(`/catalog/search?${search.toString()}`);
};

export const getSource = (sourceId: string) => request<SourceDetail>(`/sources/${sourceId}`);

export const getCatalogProduct = (catalogProductId: string) =>
  request<Record<string, unknown>>(`/catalog/${catalogProductId}`);

// --- 计划与复核 -------------------------------------------------------------

export const listRoutines = () => request<RoutineListResponse>("/routines");

export const getRoutine = (planId: string) => request<RoutinePlan>(`/routines/${planId}`);

export const createRoutineDraft = (body: {
  trigger?: string;
  exclude_owned_ids?: string[];
  note?: string | null;
}) =>
  request<RoutineDraftResponse>("/routines/drafts", {
    method: "POST",
    body: { trigger: "user_request", exclude_owned_ids: [], ...body },
    idempotencyKey: newIdempotencyKey(),
  });

export const acceptRoutine = (planId: string, expected_version: number | null, allow_stale = false) =>
  request<AcceptRoutineResponse>(`/routines/${planId}/accept`, {
    method: "POST",
    body: { expected_version, allow_stale },
    idempotencyKey: newIdempotencyKey(),
  });

export const restoreRoutine = (planId: string) =>
  request<RoutineDraftResponse>(`/routines/${planId}/restore`, { method: "POST" });

export const listReviewPrompts = () => request<ReviewPromptListResponse>("/review-prompts");

export const reviewDecision = (promptId: string, body: ReviewDecisionRequest) =>
  request<ReviewDecisionResponse>(`/review-prompts/${promptId}/decision`, {
    method: "POST",
    body,
    idempotencyKey: newIdempotencyKey(),
  });

// --- 对话 -------------------------------------------------------------------

export const listChatSessions = () => request<{ sessions: ChatSession[] }>("/chat/sessions");

export const getSessionMessages = (sessionId: string, limit = 50) =>
  request<{ session_id: string; messages: ChatMessageRecord[] }>(
    `/chat/sessions/${sessionId}/messages?limit=${limit}`,
  );

export const postChatMessage = (body: { session_id?: string | null; message: string }) =>
  request<ChatResponse>("/chat/messages", {
    method: "POST",
    body,
    idempotencyKey: newIdempotencyKey(),
  });

// --- 记忆与用户报告 ---------------------------------------------------------

export const listMemories = (params?: { include_history?: boolean; kind?: string[] }) => {
  const search = new URLSearchParams();
  if (params?.include_history === false) {
    search.set("include_history", "false");
  }
  for (const k of params?.kind ?? []) {
    search.append("kind", k);
  }
  const query = search.toString();
  return request<MemoryListResponse>(`/memories${query ? `?${query}` : ""}`);
};

export const getMemory = (memoryId: string) =>
  request<{ record: MemoryRecord; lineage: Array<{ id: string; status: string; value: unknown }> }>(
    `/memories/${memoryId}`,
  );

export const updateMemory = (memoryId: string, body: { value: unknown; expected_version?: number | null }) =>
  request<{ record: MemoryRecord; superseded?: MemoryRecord; notice: string }>(
    `/memories/${memoryId}`,
    { method: "PATCH", body },
  );

export const deleteMemory = (memoryId: string) =>
  request<{ deleted: boolean; id: string; derived_invalidated: unknown; notice: string }>(
    `/memories/${memoryId}`,
    { method: "DELETE" },
  );

export const listUsageEvents = () =>
  request<{ events: UsageEventRecord[]; notice: string }>("/usage-events");

export const createUsageEvent = (body: UsageEventCreate) =>
  request<UsageEventCreateResponse>("/usage-events", { method: "POST", body });

export const deleteUsageEvent = (eventId: string) =>
  request<{ deleted: boolean; id: string; derived_invalidated: unknown; notice: string }>(
    `/usage-events/${eventId}`,
    { method: "DELETE" },
  );

export const listIngredientFeedback = () =>
  request<{ records: IngredientFeedbackRecord[] }>("/ingredient-feedback");

export const deleteIngredientFeedback = (recordId: string) =>
  request<{ deleted: boolean; id: string }>(`/ingredient-feedback/${recordId}`, { method: "DELETE" });

// --- 成分图鉴 ---------------------------------------------------------------

export const getAtlas = (params?: { min_events?: number; refresh?: boolean }) => {
  const search = new URLSearchParams();
  if (params?.min_events) {
    search.set("min_events", String(params.min_events));
  }
  if (params?.refresh) {
    search.set("refresh", "true");
  }
  const query = search.toString();
  return request<AtlasPayload>(`/ingredients/atlas${query ? `?${query}` : ""}`);
};

export const getLatestAtlas = () => request<AtlasLatestResponse>("/ingredients/atlas/latest");

export const getIngredient = (ingredientId: string) =>
  request<IngredientDetail>(`/ingredients/${ingredientId}`);

export const postIngredientFeedback = (body: IngredientFeedbackCreate) =>
  request<{ record: IngredientFeedbackRecord; notice: string }>("/ingredients/feedback", {
    method: "POST",
    body,
  });

// --- 组合推理 ---------------------------------------------------------------

export const getCombinations = () => request<CombinationsResponse>("/combinations");

export const postCombinationChoice = (body: CombinationChoiceRequest) =>
  request<CombinationChoiceResponse>("/combinations/choice", { method: "POST", body });

// --- 客服 -------------------------------------------------------------------

export const getHandoffCandidates = () => request<HandoffCandidatesResponse>("/handoffs/candidates");

export const createHandoffDraft = (body: { record_ids: string[]; request: string }) =>
  request<HandoffDraftResponse>("/handoffs/drafts", {
    method: "POST",
    body,
    idempotencyKey: newIdempotencyKey(),
  });

export const submitHandoff = (
  ticketId: string,
  body: { expected_version?: number | null; included_record_ids?: string[] | null },
) =>
  request<HandoffDraftResponse>(`/handoffs/${ticketId}/submit`, {
    method: "POST",
    body,
    idempotencyKey: newIdempotencyKey(),
  });

export const listTickets = () => request<TicketListResponse>("/tickets");

export const getTicket = (ticketId: string) => request<TicketResponse>(`/tickets/${ticketId}`);

export const confirmResolution = (ticketId: string, resolved: boolean, note?: string) =>
  request<{ ticket: ServiceTicket; notice: string }>(`/tickets/${ticketId}/resolution`, {
    method: "POST",
    body: { resolved, note: note ?? null },
  });

export const getStaffQueue = () => request<StaffQueueResponse>("/staff/tickets");

export const getStaffTicket = (ticketId: string) =>
  request<StaffTicketResponse>(`/staff/tickets/${ticketId}`);

export const patchStaffTicket = (
  ticketId: string,
  body: { status: string; note?: string | null; expected_version?: number | null },
) =>
  request<{ ticket: ServiceTicket; notice: string }>(`/staff/tickets/${ticketId}`, {
    method: "PATCH",
    body,
  });

// --- 环境 / 地点 / 活动 ------------------------------------------------------

export const listCities = (q?: string) =>
  request<{ cities: City[]; notice: string }>(`/cities${q ? `?q=${encodeURIComponent(q)}` : ""}`);

export const getLocation = () =>
  request<{ location: LocationPreference | null; notice: string }>("/location-preferences");

export const putLocation = (body: {
  city_id: string;
  purpose?: "home" | "travel" | "unset";
  provenance?: "manual" | "device_precise";
  consent_ref?: string | null;
  expected_version?: number | null;
}) =>
  request<{ location: LocationPreference; notice: string }>("/location-preferences", {
    method: "PUT",
    body: { purpose: "home", provenance: "manual", ...body },
  });

export const listActivities = () =>
  request<{ activities: Activity[]; notice: string }>("/activities");

export const createActivity = (body: ActivityCreate) =>
  request<{ activity: Activity; notice: string }>("/activities", { method: "POST", body });

export const patchActivity = (
  activityId: string,
  body: Partial<ActivityCreate> & { status?: string; expected_version?: number | null },
) =>
  request<{ activity: Activity; notice: string }>(`/activities/${activityId}`, {
    method: "PATCH",
    body,
  });

export const cancelActivity = (activityId: string) =>
  request<{ activity: Activity; cancelled: boolean }>(`/activities/${activityId}`, {
    method: "DELETE",
  });

export const getEnvironment = (cityId?: string) =>
  request<EnvironmentResponse>(`/environment${cityId ? `?city_id=${encodeURIComponent(cityId)}` : ""}`);

export const listTriggerRules = () =>
  request<{ rules: TriggerRule[]; notice: string }>("/trigger-rules");

export const getForecastFor = (cityId: string, date: string) =>
  request<{
    found: boolean;
    day: EnvironmentSnapshotDay | null;
    notice: string;
    available_days: string[];
  }>(`/environment/forecast-for?city_id=${encodeURIComponent(cityId)}&date=${encodeURIComponent(date)}`);

interface EnvironmentSnapshotDay {
  metrics: Record<string, number | string | null>;
  missing_fields?: string[];
  valid_from?: string;
  [key: string]: unknown;
}

// --- 通知 -------------------------------------------------------------------

export const getNotificationPreferences = () =>
  request<NotificationPreferencesResponse>("/notification-preferences");

export const putNotificationPreferences = (body: NotificationPreferencePatch) =>
  request<{ preferences: NotificationPreferencesResponse["preferences"]; notice: string }>(
    "/notification-preferences",
    { method: "PUT", body },
  );

export const listPushSubscriptions = () =>
  request<{ subscriptions: PushSubscriptionRecord[]; notice: string }>("/push-subscriptions");

export const createPushSubscription = (body: {
  endpoint: string;
  keys?: Record<string, unknown> | null;
  device_id?: string;
  platform?: string;
}) =>
  request<{ subscription: { id: string; device_id: string; status: string; platform: string }; notice: string }>(
    "/push-subscriptions",
    { method: "POST", body },
  );

export const revokePushSubscription = (subscriptionId?: string) =>
  request<{ revoked: number; notice: string }>(
    `/push-subscriptions${subscriptionId ? `?subscription_id=${subscriptionId}` : ""}`,
    { method: "DELETE" },
  );

export const listMessages = (params?: { limit?: number; cursor?: string | null }) => {
  const search = new URLSearchParams();
  if (params?.limit) {
    search.set("limit", String(params.limit));
  }
  if (params?.cursor) {
    search.set("cursor", params.cursor);
  }
  const query = search.toString();
  return request<MessagesResponse>(`/messages${query ? `?${query}` : ""}`);
};

export const postMessageFeedback = (
  messageId: string,
  action: MessageFeedbackAction,
  note?: string,
) =>
  request<MessageFeedbackResponse>(`/messages/${messageId}/feedback`, {
    method: "POST",
    body: { action, note: note ?? null },
  });

export const listFollowups = () => request<{ followups: FollowUp[] }>("/followups");

export const createFollowup = (body: {
  title: string;
  purpose?: string;
  detail?: string | null;
  scheduled_at?: string | null;
  related_entity_id?: string | null;
}) => request<{ followup: { id: string; title: string; status: string }; notice: string }>("/followups", {
  method: "POST",
  body: { purpose: "check_in", ...body },
});

export const patchFollowup = (followupId: string, status: "pending" | "done" | "cancelled") =>
  request<{ followup: { id: string; status: string } }>(`/followups/${followupId}`, {
    method: "PATCH",
    body: { status },
  });

export const getInboxSummary = () => request<InboxSummaryResponse>("/inbox/summary");

// --- 品牌台 -----------------------------------------------------------------

export const createBrandDraft = (body: {
  category: "source_gap" | "service_gap" | "explicit_product_request" | "feature_request";
  summary: string;
  evidence_refs?: Array<Record<string, unknown>>;
  explicitness?: "explicit" | "inferred";
  brand_scope?: string | null;
}) =>
  request<{ draft: BrandInsightDraft; notice: string }>("/brand-feedback/drafts", {
    method: "POST",
    body: { evidence_refs: [], explicitness: "explicit", ...body },
  });

export const listBrandDrafts = () =>
  request<{ drafts: BrandInsightDraft[] }>("/brand-feedback/drafts");

export const brandFeedbackConsent = (draftId: string, granted: boolean, scope?: string) =>
  request<{ draft: BrandInsightDraft; notice: string }>(`/brand-feedback/${draftId}/consent`, {
    method: "POST",
    body: { granted, scope: scope ?? null },
  });

export const getBrandInsights = () => request<BrandInsightsResponse>("/brand/insights");

// --- 隐私 -------------------------------------------------------------------

export const exportData = () => request<Record<string, unknown>>("/privacy/export");

export const deleteAccountData = () =>
  request<{ deleted?: boolean; counts?: Record<string, number>; notice?: string }>(
    "/privacy/account-data",
    { method: "DELETE" },
  );

// --- 演示/管理控制 ----------------------------------------------------------

export const getClock = () =>
  request<{ clock: ClockInfo; notice: string }>("/admin/clock");

export const setClock = (body: { mode: "real" | "demo"; day?: number; offset_hours?: number; label?: string }) =>
  request<{ clock: ClockInfo; notice: string }>("/admin/clock", { method: "POST", body });

export const getWeatherScenario = () => request<WeatherScenarioResponse>("/admin/weather-scenario");

export const setWeatherScenario = (name: string) =>
  request<{ current: string; notice: string }>("/admin/weather-scenario", {
    method: "POST",
    body: { name },
  });

export const schedulerTick = () =>
  request<{ summary: Record<string, unknown>; notice: string }>("/admin/scheduler/tick", {
    method: "POST",
    body: {},
  });

export const getSchedulerStatus = () => request<SchedulerStatusResponse>("/admin/scheduler/status");

export const getProactiveDecisions = () =>
  request<{ decisions: ProactiveDecisionRecord[]; notice: string }>("/admin/proactive-decisions");

export const evaluateProactive = () =>
  request<{ decisions: unknown[]; notice: string }>("/admin/proactive/evaluate", {
    method: "POST",
    body: {},
  });

export const getAudit = () => request<AuditResponse>("/admin/audit");
