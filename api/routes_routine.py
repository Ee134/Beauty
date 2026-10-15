"""Routine plans: drafts, acceptance, history and feedback review decisions."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..models import ReviewPrompt
from ..services import routine_service
from ..services.errors import StaleDraftError, ValidationError, not_found
from .deps import CurrentAuth, DbSession

router = APIRouter()


class RoutineDraftRequest(BaseModel):
    trigger: str = "user_request"
    exclude_owned_ids: list[str] = Field(default_factory=list)
    note: str | None = None


class AcceptRoutineRequest(BaseModel):
    expected_version: int | None = None
    allow_stale: bool = False


class ReviewDecisionRequest(BaseModel):
    action: Literal["pause", "keep", "adjust"]
    expected_version: int | None = None
    note: str | None = None


@router.get("/routines")
def list_routines(auth: CurrentAuth, db: DbSession) -> dict[str, Any]:
    plans = routine_service.list_plans(db, tenant_id=auth.tenant_id, user_id=auth.user_id)
    active = next((p for p in plans if p.status == "active"), None)
    return {
        "active": routine_service.serialize_plan(db, active) if active else None,
        "history": [
            routine_service.serialize_plan(
                db, p, include_steps=(p.status in {"active", "draft"})
            )
            for p in plans
        ],
        "notice": "每用户最多一份 active；历史版本只读。",
    }


@router.get("/routines/{plan_id}")
def get_routine(plan_id: str, auth: CurrentAuth, db: DbSession) -> dict[str, Any]:
    plan = routine_service.get_plan(
        db, tenant_id=auth.tenant_id, user_id=auth.user_id, plan_id=plan_id
    )
    return routine_service.serialize_plan(db, plan)


@router.post("/routines/drafts", status_code=201)
def create_draft(
    payload: RoutineDraftRequest, auth: CurrentAuth, db: DbSession
) -> dict[str, Any]:
    draft = routine_service.generate_draft(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        actor=auth.user_id,
        trigger=payload.trigger,
        exclude_owned_ids=payload.exclude_owned_ids,
    )
    db.commit()
    plan = draft.plan
    return {
        "plan": routine_service.serialize_plan(db, plan) if plan else None,
        "questions": draft.questions,
        "pending_products": draft.pending_products,
        "combination_notes": draft.combination_notes,
        "skipped_combination": draft.skipped_combination,
        "uncertainties": draft.uncertainties,
        "notice": "草稿不会自动生效；接受后才成为当前版本。",
    }


@router.post("/routines/{plan_id}/accept")
def accept_routine(
    plan_id: str, payload: AcceptRoutineRequest, auth: CurrentAuth, db: DbSession
) -> dict[str, Any]:
    plan = routine_service.get_plan(
        db, tenant_id=auth.tenant_id, user_id=auth.user_id, plan_id=plan_id
    )
    try:
        routine_service.accept_draft(
            db,
            plan=plan,
            expected_version=payload.expected_version,
            actor=auth.user_id,
            allow_stale=payload.allow_stale,
        )
    except StaleDraftError:
        # keep the "needs review" marker even though the acceptance itself failed
        db.commit()
        raise
    db.commit()
    return {
        "plan": routine_service.serialize_plan(db, plan),
        "notice": "已生效；此前版本进入历史。",
    }


@router.post("/routines/{plan_id}/restore", status_code=201)
def restore_routine(plan_id: str, auth: CurrentAuth, db: DbSession) -> dict[str, Any]:
    plan = routine_service.get_plan(
        db, tenant_id=auth.tenant_id, user_id=auth.user_id, plan_id=plan_id
    )
    draft = routine_service.restore_to_draft(db, plan=plan, actor=auth.user_id)
    db.commit()
    return {
        "plan": routine_service.serialize_plan(db, draft.plan) if draft.plan else None,
        "questions": draft.questions,
        "notice": "从历史版本创建了新的草稿，没有覆盖历史版本。",
    }


@router.get("/review-prompts")
def list_review_prompts(auth: CurrentAuth, db: DbSession) -> dict[str, Any]:
    from sqlalchemy import select

    rows = list(
        db.execute(
            select(ReviewPrompt)
            .where(
                ReviewPrompt.tenant_id == auth.tenant_id,
                ReviewPrompt.user_id == auth.user_id,
            )
            .order_by(ReviewPrompt.created_at.desc())
        ).scalars()
    )
    return {
        "prompts": [
            {
                "id": p.id,
                "question": p.question,
                "options": p.options,
                "status": p.status,
                "decision": p.decision,
                "owned_product_id": p.owned_product_id,
                "plan_id": p.plan_id,
                "resulting_plan_id": p.resulting_plan_id,
                "created_at": p.created_at.isoformat(),
            }
            for p in rows
        ],
        "notice": "负面反馈只会生成复核询问，不会自动修改计划。",
    }


@router.post("/review-prompts/{prompt_id}/decision")
def review_decision(
    prompt_id: str, payload: ReviewDecisionRequest, auth: CurrentAuth, db: DbSession
) -> dict[str, Any]:
    prompt = db.get(ReviewPrompt, prompt_id)
    if (
        prompt is None
        or prompt.tenant_id != auth.tenant_id
        or prompt.user_id != auth.user_id
    ):
        raise not_found("复核问题")
    if prompt.status != "open":
        raise ValidationError("该复核问题已处理")
    result = routine_service.review_decision(
        db, prompt=prompt, action=payload.action, actor=auth.user_id, note=payload.note
    )
    db.commit()
    result["prompt"] = {
        "id": prompt.id,
        "status": prompt.status,
        "decision": prompt.decision,
    }
    if result.get("plan_id"):
        plan = routine_service.get_plan(
            db, tenant_id=auth.tenant_id, user_id=auth.user_id, plan_id=result["plan_id"]
        )
        result["plan"] = routine_service.serialize_plan(db, plan)
    result["notice"] = "计划变更一律需要你显式接受。"
    return result
