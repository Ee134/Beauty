"""Ingredient atlas endpoints and combination suitability."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..config import get_settings
from ..models import RoutinePlan, RoutineStep
from ..services import atlas as atlas_service
from ..services import cabinet as cabinet_service
from ..services.errors import ValidationError
from .deps import CurrentAuth, DbSession, SettingsDep

router = APIRouter()


class IngredientFeedbackCreate(BaseModel):
    ingredient_id: str
    statement: str = Field(min_length=1, max_length=500)
    source_message_id: str | None = None


@router.get("/ingredients/atlas")
def get_atlas(
    auth: CurrentAuth,
    db: DbSession,
    settings: SettingsDep,
    min_events: int | None = Query(default=None, ge=1, le=50),
    refresh: bool = Query(default=False),
) -> dict[str, Any]:
    """Generated on demand only; never pushed. Always regenerates so deletions take effect."""
    threshold = min_events or settings.atlas_min_events
    payload = atlas_service.build_payload(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        min_events=threshold,
        persist=True,
    )
    payload["refreshed"] = True
    payload["min_events"] = threshold
    db.commit()
    return payload


@router.get("/ingredients/atlas/latest")
def get_latest_atlas(auth: CurrentAuth, db: DbSession) -> dict[str, Any]:
    view = atlas_service.latest_view(db, tenant_id=auth.tenant_id, user_id=auth.user_id)
    if view is None:
        return {"view": None, "notice": "尚未生成图鉴；主动查看 /ingredients/atlas 时会生成。"}
    return {
        "view": {
            "id": view.id,
            "version": view.version,
            "status": view.status,
            "generated_at": view.generated_at.isoformat() if view.generated_at else None,
        },
        "payload": view.payload,
    }


@router.get("/ingredients/{ingredient_id}")
def get_ingredient(ingredient_id: str, auth: CurrentAuth, db: DbSession) -> dict[str, Any]:
    return atlas_service.get_ingredient(db, ingredient_id)


@router.post("/ingredients/feedback", status_code=201)
def create_ingredient_feedback(
    payload: IngredientFeedbackCreate, auth: CurrentAuth, db: DbSession
) -> dict[str, Any]:
    row = atlas_service.add_ingredient_feedback(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        ingredient_id=payload.ingredient_id,
        statement=payload.statement,
        source_message_id=payload.source_message_id,
        actor=auth.user_id,
    )
    db.commit()
    return {
        "record": {
            "id": row.id,
            "ingredient_id": row.ingredient_id,
            "statement": row.statement,
            "provenance_type": row.provenance_type,
        },
        "notice": "这是你本人的明确陈述，会与统计信号分开显示，不作为因果结论。",
    }


@router.get("/combinations")
def get_combinations(auth: CurrentAuth, db: DbSession) -> dict[str, Any]:
    """Combination suitability for the current cabinet, every note source backed."""
    products = cabinet_service.list_owned(db, tenant_id=auth.tenant_id, user_id=auth.user_id)
    plan = db.execute(
        select(RoutinePlan).where(
            RoutinePlan.tenant_id == auth.tenant_id,
            RoutinePlan.user_id == auth.user_id,
            RoutinePlan.status == "active",
        )
    ).scalar_one_or_none()
    steps = (
        list(db.execute(select(RoutineStep).where(RoutineStep.plan_id == plan.id)).scalars())
        if plan
        else []
    )
    return {
        "plan_version": plan.version if plan else None,
        "steps": [
            {
                "label": s.label,
                "period": s.period,
                "position": s.position,
                "citation_ids": s.citation_ids,
                "review_flag": s.review_flag,
            }
            for s in steps
        ],
        "combination_notes": plan.combination_notes if plan else [],
        "products": [
            {
                "owned_product_id": p.id,
                "name": p.custom_name,
                "ingredient_source_status": p.ingredient_source_status,
                "key_actives": p.key_actives,
            }
            for p in products
        ],
        "notice": (
            "组合建议逐条附来源；资料缺失的产品不参与组合推理。"
            "系统只提供有来源的依据，不替用户判定能否叠用。"
        ),
    }


class CombinationChoice(BaseModel):
    note_index: int = Field(ge=0)
    choice: str
    owned_product_id: str | None = None


@router.post("/combinations/choice")
def choose_combination(
    payload: CombinationChoice, auth: CurrentAuth, db: DbSession
) -> dict[str, Any]:
    settings = get_settings()
    if payload.choice not in {"keep", "space_out", "remove_one"}:
        raise ValidationError("choice 只能是 keep / space_out / remove_one")
    plan = db.execute(
        select(RoutinePlan).where(
            RoutinePlan.tenant_id == auth.tenant_id,
            RoutinePlan.user_id == auth.user_id,
            RoutinePlan.status == "active",
        )
    ).scalar_one_or_none()
    if plan is None:
        raise ValidationError("当前没有生效中的计划")
    if payload.note_index >= len(plan.combination_notes or []):
        raise ValidationError("组合提示序号超出范围")
    note = plan.combination_notes[payload.note_index]
    if payload.choice == "keep":
        return {
            "plan_changed": False,
            "choice": "keep",
            "notice": "已记录：保留当前安排。计划没有变化。",
        }
    # space_out / remove_one -> a new DRAFT, only the user can accept it
    from ..services import routine_service

    exclude = [payload.owned_product_id] if payload.choice == "remove_one" and payload.owned_product_id else []
    draft = routine_service.generate_draft(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        actor=auth.user_id,
        trigger=f"combination_{payload.choice}",
        exclude_owned_ids=exclude,
        extra_reasons=[
            {
                "type": "combination_choice",
                "text": (
                    f"你选择了「{'间隔使用' if payload.choice == 'space_out' else '移除其中一件'}」"
                    f"（组合提示：{note.get('ingredient_inci') or note.get('type')}）。"
                    "本草稿尚未生效，需要你确认接受。"
                ),
                "citation_ids": note.get("citation_ids") or [],
            }
        ],
    )
    db.commit()
    return {
        "plan_changed": False,
        "draft_created": True,
        "choice": payload.choice,
        "plan": routine_service.serialize_plan(db, draft.plan) if draft.plan else None,
        "notice": "已生成新草稿；接受前当前版本继续有效。",
        "mode": settings.model_mode,
    }
