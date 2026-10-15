/**
 * 由 scripts/export_openapi.py 从 FastAPI 的 OpenAPI 契约自动生成。
 * 请勿手工修改：重新运行 `./.venv/bin/python -m scripts.export_openapi` 即可。
 */

export type AcceptRoutineRequest = {
  "expected_version"?: number | null;
  "allow_stale"?: boolean;
};

export type ActivityCreate = {
  "activity_type": "outdoor" | "trip";
  "title": string;
  "starts_at": string;
  "ends_at"?: string | null;
  "destination_city_id"?: string | null;
  "origin_city_id"?: string | null;
  "user_confirmed"?: boolean;
  "notes"?: string | null;
};

export type ActivityPatch = {
  "expected_version"?: number | null;
  "title"?: string | null;
  "starts_at"?: string | null;
  "ends_at"?: string | null;
  "status"?: "planned" | "cancelled" | "completed" | "expired" | null;
  "notes"?: string | null;
  "user_confirmed"?: boolean | null;
  "destination_city_id"?: string | null;
};

export type Body_create_import_api_v1_imports_post = {
  "file": string;
  "note"?: string | null;
};

export type BrandConsentRequest = {
  "granted": boolean;
  "scope"?: string | null;
};

export type BrandDraftRequest = {
  "category": "source_gap" | "service_gap" | "explicit_product_request" | "feature_request";
  "summary": string;
  "evidence_refs"?: Array<Record<string, unknown>>;
  "explicitness"?: "explicit" | "inferred";
  "brand_scope"?: string | null;
};

export type ChatRequest = {
  "session_id"?: string | null;
  "message": string;
  "client_context"?: Record<string, unknown> | null;
};

export type ClockRequest = {
  "mode"?: string;
  "fixed_at"?: string | null;
  "offset_hours"?: number | null;
  "label"?: string | null;
  "day"?: number | null;
};

export type CombinationChoice = {
  "note_index": number;
  "choice": string;
  "owned_product_id"?: string | null;
};

export type ConfirmImportItem = {
  "raw_name"?: string | null;
  "custom_name"?: string | null;
  "catalog_product_id"?: string | null;
  "quantity"?: number;
  "size"?: string | null;
  "match_status"?: "matched" | "low_confidence" | "custom";
  "purchase_date"?: string | null;
  "opened_date"?: string | null;
  "lifecycle_status"?: "unopened" | "opened" | "finished" | "discarded" | "unknown";
};

export type ConfirmImportRequest = {
  "items": Array<ConfirmImportItem>;
};

export type DemoSessionRequest = {
  "persona_code": string;
  "device_label"?: string | null;
};

export type FollowUpCreate = {
  "purpose"?: string;
  "title": string;
  "detail"?: string | null;
  "scheduled_at"?: string | null;
  "related_entity_id"?: string | null;
  "consent_ref"?: string | null;
};

export type FollowUpPatch = {
  "status": "pending" | "done" | "cancelled";
};

export type HTTPValidationError = {
  "detail"?: Array<ValidationError>;
};

export type HandoffDraftRequest = {
  "record_ids"?: Array<string>;
  "request": string;
};

export type HandoffSubmitRequest = {
  "expected_version"?: number | null;
  "included_record_ids"?: Array<string> | null;
};

export type IngredientFeedbackCreate = {
  "ingredient_id": string;
  "statement": string;
  "source_message_id"?: string | null;
};

export type LocationRequest = {
  "city_id": string;
  "purpose"?: "home" | "travel" | "unset";
  "provenance"?: "manual" | "device_precise";
  "consent_ref"?: string | null;
  "expected_version"?: number | null;
};

export type MemoryUpdate = {
  "value"?: unknown;
  "expected_version"?: number | null;
};

export type MessageFeedbackRequest = {
  "action": "read" | "adopt_intent" | "reject" | "later" | "not_helpful" | "mute_type";
  "note"?: string | null;
};

export type NotificationPreferencePatch = {
  "service_types"?: Array<string> | null;
  "channels"?: Array<string> | null;
  "daily_cap"?: number | null;
  "quiet_hours_start"?: string | null;
  "quiet_hours_end"?: string | null;
  "timezone"?: string | null;
  "marketing_opt_in"?: boolean | null;
  "external_push_enabled"?: boolean | null;
  "muted_service_types"?: Array<string> | null;
  "consent_version"?: string | null;
  "expected_version"?: number | null;
};

export type OwnedProductCreate = {
  "custom_name": string;
  "catalog_product_id"?: string | null;
  "match_status"?: "matched" | "low_confidence" | "custom";
  "purchase_date"?: string | null;
  "opened_date"?: string | null;
  "expiry_date"?: string | null;
  "expiry_source"?: "packaging" | "user_confirmed" | "pao_derived" | "unknown";
  "pao_months"?: number | null;
  "lifecycle_status"?: "unopened" | "opened" | "finished" | "discarded" | "unknown";
  "usage_status"?: "active" | "paused" | "unknown";
  "size"?: string | null;
  "notes"?: string | null;
};

export type OwnedProductPatch = {
  "expected_version"?: number | null;
  "custom_name"?: string | null;
  "purchase_date"?: string | null;
  "opened_date"?: string | null;
  "expiry_date"?: string | null;
  "expiry_source"?: string | null;
  "pao_months"?: number | null;
  "lifecycle_status"?: string | null;
  "usage_status"?: string | null;
  "size"?: string | null;
  "notes"?: string | null;
  "review_flag"?: boolean | null;
  "review_note"?: string | null;
};

export type PushSubscriptionRequest = {
  "endpoint": string;
  "keys"?: Record<string, unknown> | null;
  "device_id"?: string;
  "platform"?: string;
};

export type ResolutionConfirm = {
  "resolved": boolean;
  "note"?: string | null;
};

export type ReviewDecisionRequest = {
  "action": "pause" | "keep" | "adjust";
  "expected_version"?: number | null;
  "note"?: string | null;
};

export type RoutineDraftRequest = {
  "trigger"?: string;
  "exclude_owned_ids"?: Array<string>;
  "note"?: string | null;
};

export type TicketPatchRequest = {
  "status": "submitted" | "awaiting_user" | "in_review" | "resolved" | "cancelled";
  "note"?: string | null;
  "expected_version"?: number | null;
};

export type UsageEventCreate = {
  "reported_text": string;
  "owned_product_ids"?: Array<string>;
  "occurred_at"?: string | null;
  "time_precision"?: "unknown" | "day" | "exact" | "approximate";
  "event_type"?: "positive" | "negative" | "neutral" | "uncertain" | null;
};

export type ValidationError = {
  "loc": Array<string | number>;
  "msg": string;
  "type": string;
  "input"?: unknown;
  "ctx"?: Record<string, unknown>;
};

export type WeatherScenarioRequest = {
  "name": string;
};

export interface ApiPaths {
  /** GET */
  "/": 'GET';
  /** GET, POST */
  "/api/v1/activities": 'GET, POST';
  /** DELETE, PATCH */
  "/api/v1/activities/{activity_id}": 'DELETE, PATCH';
  /** GET */
  "/api/v1/admin/audit": 'GET';
  /** GET, POST */
  "/api/v1/admin/clock": 'GET, POST';
  /** GET */
  "/api/v1/admin/proactive-decisions": 'GET';
  /** POST */
  "/api/v1/admin/proactive/evaluate": 'POST';
  /** GET */
  "/api/v1/admin/scheduler/status": 'GET';
  /** POST */
  "/api/v1/admin/scheduler/tick": 'POST';
  /** GET, POST */
  "/api/v1/admin/weather-scenario": 'GET, POST';
  /** POST */
  "/api/v1/auth/demo-session": 'POST';
  /** GET, POST */
  "/api/v1/brand-feedback/drafts": 'GET, POST';
  /** POST */
  "/api/v1/brand-feedback/{draft_id}/consent": 'POST';
  /** GET */
  "/api/v1/brand/insights": 'GET';
  /** GET */
  "/api/v1/catalog/search": 'GET';
  /** GET */
  "/api/v1/catalog/{catalog_product_id}": 'GET';
  /** POST */
  "/api/v1/chat/messages": 'POST';
  /** GET */
  "/api/v1/chat/sessions": 'GET';
  /** GET */
  "/api/v1/chat/sessions/{session_id}/messages": 'GET';
  /** GET */
  "/api/v1/cities": 'GET';
  /** GET */
  "/api/v1/combinations": 'GET';
  /** POST */
  "/api/v1/combinations/choice": 'POST';
  /** GET */
  "/api/v1/environment": 'GET';
  /** GET */
  "/api/v1/environment/forecast-for": 'GET';
  /** GET, POST */
  "/api/v1/followups": 'GET, POST';
  /** PATCH */
  "/api/v1/followups/{followup_id}": 'PATCH';
  /** GET */
  "/api/v1/handoffs/candidates": 'GET';
  /** POST */
  "/api/v1/handoffs/drafts": 'POST';
  /** POST */
  "/api/v1/handoffs/{ticket_id}/submit": 'POST';
  /** GET */
  "/api/v1/health": 'GET';
  /** GET, POST */
  "/api/v1/imports": 'GET, POST';
  /** GET */
  "/api/v1/imports/{batch_id}": 'GET';
  /** POST */
  "/api/v1/imports/{batch_id}/confirm": 'POST';
  /** GET */
  "/api/v1/inbox/summary": 'GET';
  /** GET */
  "/api/v1/ingredient-feedback": 'GET';
  /** DELETE, GET */
  "/api/v1/ingredient-feedback/{record_id}": 'DELETE, GET';
  /** GET */
  "/api/v1/ingredients/atlas": 'GET';
  /** GET */
  "/api/v1/ingredients/atlas/latest": 'GET';
  /** POST */
  "/api/v1/ingredients/feedback": 'POST';
  /** GET */
  "/api/v1/ingredients/{ingredient_id}": 'GET';
  /** GET, PUT */
  "/api/v1/location-preferences": 'GET, PUT';
  /** GET */
  "/api/v1/me": 'GET';
  /** GET */
  "/api/v1/memories": 'GET';
  /** DELETE, GET, PATCH */
  "/api/v1/memories/{memory_id}": 'DELETE, GET, PATCH';
  /** GET */
  "/api/v1/messages": 'GET';
  /** POST */
  "/api/v1/messages/{message_id}/feedback": 'POST';
  /** GET */
  "/api/v1/meta": 'GET';
  /** GET, PUT */
  "/api/v1/notification-preferences": 'GET, PUT';
  /** GET, POST */
  "/api/v1/owned-products": 'GET, POST';
  /** DELETE, GET, PATCH */
  "/api/v1/owned-products/{owned_id}": 'DELETE, GET, PATCH';
  /** DELETE */
  "/api/v1/privacy/account-data": 'DELETE';
  /** GET */
  "/api/v1/privacy/export": 'GET';
  /** DELETE, GET, POST */
  "/api/v1/push-subscriptions": 'DELETE, GET, POST';
  /** DELETE */
  "/api/v1/push-subscriptions/{subscription_id}": 'DELETE';
  /** GET */
  "/api/v1/review-prompts": 'GET';
  /** POST */
  "/api/v1/review-prompts/{prompt_id}/decision": 'POST';
  /** GET */
  "/api/v1/routines": 'GET';
  /** POST */
  "/api/v1/routines/drafts": 'POST';
  /** GET */
  "/api/v1/routines/{plan_id}": 'GET';
  /** POST */
  "/api/v1/routines/{plan_id}/accept": 'POST';
  /** POST */
  "/api/v1/routines/{plan_id}/restore": 'POST';
  /** GET */
  "/api/v1/sources/{source_id}": 'GET';
  /** GET */
  "/api/v1/staff/tickets": 'GET';
  /** GET, PATCH */
  "/api/v1/staff/tickets/{ticket_id}": 'GET, PATCH';
  /** GET */
  "/api/v1/tickets": 'GET';
  /** GET */
  "/api/v1/tickets/{ticket_id}": 'GET';
  /** POST */
  "/api/v1/tickets/{ticket_id}/resolution": 'POST';
  /** GET */
  "/api/v1/trigger-rules": 'GET';
  /** GET, POST */
  "/api/v1/usage-events": 'GET, POST';
  /** DELETE */
  "/api/v1/usage-events/{event_id}": 'DELETE';
  /** GET */
  "/icons/{name}": 'GET';
  /** GET */
  "/manifest.webmanifest": 'GET';
  /** GET */
  "/sw.js": 'GET';
  /** GET */
  "/{full_path}": 'GET';
}
