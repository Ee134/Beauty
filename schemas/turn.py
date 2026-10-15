"""Typed agent I/O. Cards and pending actions are discriminated unions, not free JSON."""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

INTENTS = Literal[
    "import",
    "routine",
    "feedback",
    "memory",
    "service",
    "environment",
    "travel",
    "notification",
    "brand_feedback",
    "ingredient_atlas",
    "general",
    "unsupported",
]


class Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StepOut(Base):
    id: str | None = None
    period: str
    position: int
    owned_product_id: str | None = None
    label: str
    instruction: str
    frequency: str | None = None
    basis: str
    citation_ids: list[str] = Field(default_factory=list)
    review_flag: bool = False
    review_note: str | None = None
    is_general_advice: bool = False


class CitationOut(Base):
    citation_id: str
    source_id: str
    chunk_id: str
    product_id: str | None = None
    title: str
    locator: str | None = None
    url: str | None = None
    file_ref: str | None = None
    retrieved_at: str | None = None
    reviewed_at: str | None = None
    source_type: str | None = None
    is_demo: bool = False
    excerpt: str | None = None


# --- cards ---------------------------------------------------------------


class RoutineDraftCard(Base):
    type: Literal["routine_draft"] = "routine_draft"
    entity_id: str
    version: int
    status: str
    step_count: int
    diff_summary: str | None = None
    pending_count: int = 0
    combination_note_count: int = 0
    question_count: int = 0


class RoutinePlanCard(Base):
    type: Literal["routine_plan"] = "routine_plan"
    entity_id: str
    version: int
    status: str
    steps: list[StepOut] = Field(default_factory=list)
    pending_products: list[dict[str, Any]] = Field(default_factory=list)
    combination_notes: list[dict[str, Any]] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)


class ImportCandidatesCard(Base):
    type: Literal["import_candidates"] = "import_candidates"
    entity_id: str
    status: str
    candidate_count: int
    low_confidence: bool = False
    provider_mode: str = "mock"
    notice: str = "mock 模式：候选来自内置演示截图样本，不代表真实识别能力。"


class OwnedProductCard(Base):
    type: Literal["owned_product"] = "owned_product"
    entity_id: str
    name: str
    usage_status: str
    lifecycle_status: str
    ingredient_source_status: str
    effective_expiry: str | None = None
    expiry_unknown_reason: str | None = None


class MemoryRecordCard(Base):
    type: Literal["memory_record"] = "memory_record"
    entity_id: str
    kind: str
    key: str
    value: Any = None
    status: str
    label: str | None = None
    provenance_type: str | None = None
    requires_confirmation: bool = False


class ReviewPromptCard(Base):
    type: Literal["review_prompt"] = "review_prompt"
    entity_id: str
    question: str
    options: list[str] = Field(default_factory=list)
    owned_product_id: str | None = None
    plan_version: int | None = None


class TicketCard(Base):
    type: Literal["service_ticket"] = "service_ticket"
    entity_id: str
    status: str
    adapter_mode: str
    next_action: str | None = None
    notice: str | None = None


class EnvironmentCard(Base):
    type: Literal["environment"] = "environment"
    entity_id: str | None = None
    city_name: str
    city_id: str
    quality: str
    mode: str
    kind: str
    issued_at: str | None = None
    valid_to: str | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    notice: str | None = None


class ChecklistCard(Base):
    type: Literal["travel_checklist"] = "travel_checklist"
    entity_id: str
    activity_id: str
    title: str
    items: list[str] = Field(default_factory=list)
    unknown_days: list[str] = Field(default_factory=list)
    notice: str | None = None


class ProactiveMessageCard(Base):
    type: Literal["proactive_message"] = "proactive_message"
    entity_id: str
    title: str
    body: str
    reason_codes: list[str] = Field(default_factory=list)
    channel: str | None = None
    expires_at: str | None = None
    decision_outcome: str = "send"


class CombinationNoteCard(Base):
    type: Literal["combination_note"] = "combination_note"
    entity_id: str | None = None
    ingredient_inci: str | None = None
    text: str
    citation_ids: list[str] = Field(default_factory=list)
    options: list[str] = Field(default_factory=list)
    decided_by_system: bool = False


class IngredientCard(Base):
    type: Literal["ingredient"] = "ingredient"
    entity_id: str
    inci_name: str
    common_name: str
    data_status: str
    data_note: str | None = None


class AtlasCard(Base):
    type: Literal["ingredient_atlas"] = "ingredient_atlas"
    entity_id: str | None = None
    version: int | None = None
    card_count: int = 0
    below_threshold_count: int = 0
    pending_count: int = 0
    notice: str = "图鉴在你主动查看时生成，不会自动推送。"


class ServiceStatusCard(Base):
    type: Literal["service_status"] = "service_status"
    entity_id: str | None = None
    ticket_id: str | None = None
    status: str | None = None
    found: bool = True
    timeline_count: int = 0
    next_action: str | None = None


class AuditSummaryCard(Base):
    type: Literal["audit_summary"] = "audit_summary"
    entity_id: str | None = None
    headline: str
    items: list[str] = Field(default_factory=list)


class ErrorCard(Base):
    type: Literal["error"] = "error"
    entity_id: str | None = None
    code: str
    message: str
    retryable: bool = False
    manual_path: str | None = None


Card = Annotated[
    Union[
        RoutineDraftCard,
        RoutinePlanCard,
        ImportCandidatesCard,
        OwnedProductCard,
        MemoryRecordCard,
        ReviewPromptCard,
        TicketCard,
        EnvironmentCard,
        ChecklistCard,
        ProactiveMessageCard,
        CombinationNoteCard,
        IngredientCard,
        AtlasCard,
        ServiceStatusCard,
        AuditSummaryCard,
        ErrorCard,
    ],
    Field(discriminator="type"),
]


class PendingAction(Base):
    type: Literal[
        "accept_routine",
        "submit_handoff",
        "confirm_import",
        "confirm_memory",
        "review_routine",
        "add_owned_product",
        "open_atlas",
        "provide_missing_info",
    ]
    entity_id: str | None = None
    expected_version: int | None = None
    label: str
    blocked_reason: str | None = None


class Question(Base):
    key: str
    question: str
    why: str | None = None
    options: list[str] = Field(default_factory=list)


class MemoryChange(Base):
    type: Literal["preference", "fact", "user_report", "correction", "deletion", "pending"]
    entity_id: str | None = None
    key: str | None = None
    value: Any = None
    status: str | None = None
    description: str | None = None


class TurnOutput(Base):
    """Standard output (spec 9.3)."""

    run_id: str
    intent: INTENTS
    answer: str
    questions: list[Question] = Field(default_factory=list)
    citations: list[CitationOut] = Field(default_factory=list)
    cards: list[Card] = Field(default_factory=list)
    memory_changes: list[MemoryChange] = Field(default_factory=list)
    pending_actions: list[PendingAction] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    mode: Literal["mock", "live"] = "mock"
    model_unavailable: bool = False
    validation_errors: list[dict[str, Any]] = Field(default_factory=list)
    clock: dict[str, Any] | None = None
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)


class WriteRequest(Base):
    """A draft-only write the model is allowed to ask for. Never executed blindly."""

    tool: Literal[
        "draft_routine",
        "draft_handoff",
        "propose_memory",
        "record_usage_event",
        "create_followup",
        "draft_brand_feedback",
        "propose_proactive_service",
    ]
    args: dict[str, Any] = Field(default_factory=dict)


class PlannerOutput(Base):
    """First call: intent + minimal read-only tool requests + draft-only writes."""

    intent: INTENTS
    tool_requests: list[dict[str, Any]] = Field(default_factory=list)
    write_requests: list["WriteRequest"] = Field(default_factory=list)
    questions: list[Question] = Field(default_factory=list)
    reasoning_summary: str | None = None


class ComposeOutput(Base):
    answer: str
    questions: list[Question] = Field(default_factory=list)
    memory_proposals: list[dict[str, Any]] = Field(default_factory=list)
    write_requests: list[WriteRequest] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    citation_ids: list[str] = Field(default_factory=list)


PlannerOutput.model_rebuild()
ComposeOutput.model_rebuild()
