"""Service handoff, tickets and the demo staff console."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..services import tickets as ticket_service
from .deps import BrandAuth, CurrentAuth, DbSession, IdempotencyKey, StaffAuth

router = APIRouter()


class HandoffDraftRequest(BaseModel):
    record_ids: list[str] = Field(default_factory=list)
    request: str = Field(min_length=1, max_length=1000)


class HandoffSubmitRequest(BaseModel):
    expected_version: int | None = None
    included_record_ids: list[str] | None = None


class TicketPatchRequest(BaseModel):
    status: Literal["submitted", "awaiting_user", "in_review", "resolved", "cancelled"]
    note: str | None = None
    expected_version: int | None = None


class ResolutionConfirm(BaseModel):
    resolved: bool
    note: str | None = None


@router.get("/handoffs/candidates")
def handoff_candidates(auth: CurrentAuth, db: DbSession) -> dict[str, Any]:
    return ticket_service.suggest_records(db, tenant_id=auth.tenant_id, user_id=auth.user_id)


@router.post("/handoffs/drafts", status_code=201)
def create_handoff_draft(
    payload: HandoffDraftRequest, auth: CurrentAuth, db: DbSession
) -> dict[str, Any]:
    ticket = ticket_service.draft_handoff(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        included_record_ids=payload.record_ids,
        request_text=payload.request,
        actor=auth.user_id,
    )
    db.commit()
    return {
        "ticket": ticket_service.serialize_ticket(db, ticket),
        "notice": "这是预览草稿：确认提交前不会产生任何工单状态变化。",
    }


@router.post("/handoffs/{ticket_id}/submit")
def submit_handoff(
    ticket_id: str,
    payload: HandoffSubmitRequest,
    auth: CurrentAuth,
    db: DbSession,
    idem: IdempotencyKey,
) -> dict[str, Any]:
    ticket = ticket_service.get_ticket(
        db, tenant_id=auth.tenant_id, user_id=auth.user_id, ticket_id=ticket_id
    )
    ticket_service.submit_handoff(
        db,
        ticket=ticket,
        expected_version=payload.expected_version,
        included_record_ids=payload.included_record_ids,
        actor=auth.user_id,
    )
    db.commit()
    return {
        "ticket": ticket_service.serialize_ticket(db, ticket),
        "notice": (
            "已提交到本地演示工作台（adapter_mode=local_demo）。"
            "这不代表任何品牌方已收到，也不代表问题已解决。"
        ),
    }


@router.get("/tickets")
def list_tickets(auth: CurrentAuth, db: DbSession) -> dict[str, Any]:
    rows = ticket_service.list_tickets(db, tenant_id=auth.tenant_id, user_id=auth.user_id)
    return {
        "tickets": [ticket_service.serialize_ticket(db, t, include_timeline=False) for t in rows],
        "notice": "状态来自本地演示工作台。",
    }


@router.get("/tickets/{ticket_id}")
def get_ticket(ticket_id: str, auth: CurrentAuth, db: DbSession) -> dict[str, Any]:
    ticket = ticket_service.get_ticket(
        db, tenant_id=auth.tenant_id, user_id=auth.user_id, ticket_id=ticket_id
    )
    return {"ticket": ticket_service.serialize_ticket(db, ticket)}


@router.post("/tickets/{ticket_id}/resolution")
def confirm_resolution(
    ticket_id: str, payload: ResolutionConfirm, auth: CurrentAuth, db: DbSession
) -> dict[str, Any]:
    ticket = ticket_service.get_ticket(
        db, tenant_id=auth.tenant_id, user_id=auth.user_id, ticket_id=ticket_id
    )
    ticket_service.confirm_resolution(
        db, ticket=ticket, resolved=payload.resolved, note=payload.note, actor=auth.user_id
    )
    db.commit()
    return {
        "ticket": ticket_service.serialize_ticket(db, ticket),
        "notice": "解决与否以你的确认为准，不以客服状态自动认定。",
    }


@router.get("/staff/tickets")
def staff_queue(auth: StaffAuth, db: DbSession) -> dict[str, Any]:
    rows = ticket_service.staff_queue(db, tenant_id=auth.tenant_id)
    return {
        "environment": "模拟业务环境（本地演示工作台）",
        "tickets": [ticket_service.serialize_ticket(db, t) for t in rows],
        "notice": "演示客服视图：明确标识为本地模拟环境，不对应任何真实品牌客服系统。",
    }


@router.get("/staff/tickets/{ticket_id}")
def staff_ticket(ticket_id: str, auth: StaffAuth, db: DbSession) -> dict[str, Any]:
    from ..models import ServiceTicket

    row = db.get(ServiceTicket, ticket_id)
    if row is None or row.tenant_id != auth.tenant_id:
        from ..services.errors import not_found

        raise not_found("工单")
    return {
        "environment": "模拟业务环境（本地演示工作台）",
        "ticket": ticket_service.serialize_ticket(db, row),
        "evidence": {
            "products": (row.summary or {}).get("products", []),
            "user_reports": (row.summary or {}).get("user_reports", []),
            "actions_already_taken": (row.summary or {}).get("actions_already_taken", []),
        },
    }


@router.patch("/staff/tickets/{ticket_id}")
def staff_update_ticket(
    ticket_id: str, payload: TicketPatchRequest, auth: StaffAuth, db: DbSession
) -> dict[str, Any]:
    from ..models import ServiceTicket

    row = db.get(ServiceTicket, ticket_id)
    if row is None or row.tenant_id != auth.tenant_id:
        from ..services.errors import not_found

        raise not_found("工单")
    ticket_service.staff_update(
        db,
        ticket=row,
        status=payload.status,
        note=payload.note,
        actor_user_id=auth.user_id,
        actor_role=auth.role,
    )
    db.commit()
    return {
        "ticket": ticket_service.serialize_ticket(db, row),
        "notice": "客服标记 resolved 不等于用户已确认解决。",
    }
