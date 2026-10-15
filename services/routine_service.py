"""Routine plan generation, versioning and acceptance.

Only approved, version matched sources may produce a step. Products without
usable sources go to the pending list and are never arranged. Combination notes
are always quoted from an approved source; the system never decides on its own
whether two products may be layered.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..knowledge import service as knowledge
from ..models import CatalogProduct, OwnedProduct, ReviewPrompt, RoutinePlan, RoutineStep
from . import audit
from . import cabinet as cabinet_service
from . import memory_service
from .atlas import combo_reasoning
from .clock import now as clock_now
from .errors import StaleDraftError, ValidationError, VersionConflictError, not_found

PERIODS = ("morning", "evening", "weekly", "as_needed")

ORDER_HINT_RANK = {
    "first_step": 0,
    "after_cleanser": 1,
    "after_toner": 2,
    "after_serum": 3,
    "before_sunscreen": 4,
    "after_moisturizer": 5,
    "last_step_morning": 6,
    "last_step_evening": 6,
}

CATEGORY_PRIORITY = {
    "sunscreen": 100,
    "cleanser": 90,
    "moisturizer": 80,
    "treatment": 60,
    "toner": 55,
    "serum": 50,
    "exfoliant": 40,
    "mask": 30,
}


@dataclass
class DraftResult:
    plan: RoutinePlan
    steps: list[RoutineStep]
    pending_products: list[dict[str, Any]]
    combination_notes: list[dict[str, Any]]
    skipped_combination: list[dict[str, Any]]
    questions: list[dict[str, Any]] = field(default_factory=list)
    reasons: list[dict[str, Any]] = field(default_factory=list)
    uncertainties: list[str] = field(default_factory=list)


def _snapshot_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()


def _active_plan(db: Session, *, tenant_id: str, user_id: str) -> RoutinePlan | None:
    return db.execute(
        select(RoutinePlan).where(
            RoutinePlan.tenant_id == tenant_id,
            RoutinePlan.user_id == user_id,
            RoutinePlan.status == "active",
        )
    ).scalar_one_or_none()


def _plan_steps(db: Session, plan_id: str) -> list[RoutineStep]:
    return list(
        db.execute(
            select(RoutineStep)
            .where(RoutineStep.plan_id == plan_id)
            .order_by(RoutineStep.period, RoutineStep.position)
        ).scalars()
    )


def _next_version(db: Session, *, tenant_id: str, user_id: str) -> int:
    rows = list(
        db.execute(
            select(RoutinePlan.version).where(
                RoutinePlan.tenant_id == tenant_id, RoutinePlan.user_id == user_id
            )
        ).scalars()
    )
    return (max(rows) + 1) if rows else 1


def _period_for(knowledge_periods: Sequence[str], catalog: CatalogProduct | None) -> str:
    hints = set(knowledge_periods or [])
    if "evening" in hints and "morning" not in hints:
        return "evening"
    if "morning" in hints and "evening" not in hints:
        return "morning"
    if "as_needed" in hints and not (hints & {"morning", "evening"}):
        return "as_needed"
    if catalog and catalog.category == "sunscreen":
        return "morning"
    return "both"


def _build_step_payload(
    db: Session, product: OwnedProduct, catalog: CatalogProduct | None
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    pk = knowledge.load_product_knowledge(db, catalog)
    if pk.error_code == "SOURCE_CONFLICT":
        return None, {
            "owned_product_id": product.id,
            "name": product.custom_name,
            "reason": "SOURCE_CONFLICT",
            "message": pk.message,
        }
    if not pk.has_sources or not pk.usage_instructions:
        return None, {
            "owned_product_id": product.id,
            "name": product.custom_name,
            "reason": "SOURCE_MISSING",
            "message": pk.message or "没有已审核的使用说明，无法生成步骤。",
        }
    usage_chunk, usage_source = pk.usage_instructions[0]
    frequency_chunk, frequency_source = (pk.frequencies[0] if pk.frequencies else (None, None))
    citation_ids = [usage_chunk.id]
    if frequency_chunk is not None:
        citation_ids.append(frequency_chunk.id)
    structured = usage_chunk.structured or {}
    period = _period_for(pk.period_hints, catalog)
    if structured.get("period") in PERIODS and structured.get("period") != "any":
        period = structured["period"]
    order_hint = structured.get("order_hint")
    rank = ORDER_HINT_RANK.get(str(order_hint), 50)
    if product.usage_status == "paused" or product.lifecycle_status in {"finished", "discarded"}:
        return None, {
            "owned_product_id": product.id,
            "name": product.custom_name,
            "reason": "PRODUCT_NOT_USABLE",
            "message": "该产品当前处于暂停/已用完/已丢弃状态，不排入计划。",
        }
    basis = f"依据《{usage_source.title}》{usage_chunk.locator or ''}".strip()
    instruction = usage_chunk.text.strip()
    frequency_text = None
    if frequency_chunk is not None:
        frequency_text = (frequency_chunk.structured or {}).get("frequency_text") or frequency_chunk.text.strip()
        basis += f"；频率依据《{frequency_source.title}》"
    return (
        {
            "owned_product_id": product.id,
            "catalog_product_id": catalog.id if catalog else None,
            "label": product.custom_name,
            "instruction": instruction,
            "frequency": frequency_text,
            "basis": basis,
            "citation_ids": citation_ids,
            "period": period,
            "rank": rank,
            "category": (catalog.category if catalog else "unknown"),
            "review_flag": bool(product.review_flag),
            "review_note": product.review_note,
            "is_general_advice": False,
        },
        None,
    )


def generate_draft(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    actor: str | None = None,
    trigger: str = "user_request",
    exclude_owned_ids: Sequence[str] = (),
    extra_reasons: Sequence[dict[str, Any]] = (),
    source_plan: RoutinePlan | None = None,
) -> DraftResult:
    products = [
        p
        for p in cabinet_service.list_owned(db, tenant_id=tenant_id, user_id=user_id)
        if p.id not in set(exclude_owned_ids)
    ]
    active = _active_plan(db, tenant_id=tenant_id, user_id=user_id)
    max_steps = memory_service.get_active_value(
        db, tenant_id=tenant_id, user_id=user_id, key="routine.max_steps"
    )
    questions: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    step_payloads: list[dict[str, Any]] = []
    reasons: list[dict[str, Any]] = list(extra_reasons)
    uncertainties: list[str] = []

    if not products:
        return DraftResult(
            plan=None,  # type: ignore[arg-type]
            steps=[],
            pending_products=[],
            combination_notes=[],
            skipped_combination=[],
            questions=[
                {
                    "key": "cabinet.empty",
                    "question": "美妆柜里还没有产品。你想先手动添加，还是上传一张订单截图？",
                    "why": "没有产品就无法生成有来源依据的计划。",
                }
            ],
            reasons=[{"type": "no_products", "text": "柜内没有可用产品。"}],
        )

    for product in products:
        catalog = db.get(CatalogProduct, product.catalog_product_id) if product.catalog_product_id else None
        payload, problem = _build_step_payload(db, product, catalog)
        if payload is not None:
            step_payloads.append(payload)
        elif problem is not None:
            pending.append(problem)

    # an explicitly confirmed period preference is applied before trimming, and the
    # affected steps are reported instead of being silently merged away
    preferred_period = memory_service.get_active_value(
        db, tenant_id=tenant_id, user_id=user_id, key="routine.preferred_period"
    )
    if preferred_period in {"morning", "evening"} and step_payloads:
        allowed = {preferred_period, "as_needed", "weekly"}
        kept = [step for step in step_payloads if step["period"] in allowed]
        dropped_by_period = [step for step in step_payloads if step["period"] not in allowed]
        if kept:
            step_payloads = kept
            if dropped_by_period:
                reasons.append(
                    {
                        "type": "preferred_period_applied",
                        "text": (
                            f"按你确认的偏好「只在{'晨间' if preferred_period == 'morning' else '晚间'}使用」，"
                            f"本版本不安排其它时段的产品。产品没有被合并，只是不在此版本中。"
                        ),
                        "preferred_period": preferred_period,
                        "dropped": [
                            {"owned_product_id": step["owned_product_id"], "label": step["label"]}
                            for step in dropped_by_period
                        ],
                    }
                )
        else:
            uncertainties.append(
                "你的时段偏好会移除所有已确认资料支持的步骤，因此本版本仍然保留了完整时段安排。"
            )

    notes, skipped = combo_reasoning(db, products)

    if not step_payloads:
        questions.append(
            {
                "key": "sources.missing",
                "question": "柜内产品目前都没有已审核的使用说明。要不要先补充产品信息或联系我们核实？",
                "why": "没有已审核资料时不会生成任何使用频率或功效建议。",
            }
        )

    if max_steps is None and len(step_payloads) > 6:
        questions.append(
            {
                "key": "routine.max_steps",
                "question": "你希望每天保留几个步骤？",
                "why": "步骤上限会影响计划如何取舍，且会被保存为长期偏好。",
            }
        )

    # --- trimming -------------------------------------------------------
    dropped: list[dict[str, Any]] = []
    ordered = sorted(
        step_payloads,
        key=lambda s: (
            {"morning": 0, "both": 1, "evening": 2, "weekly": 3, "as_needed": 4}.get(s["period"], 5),
            s["rank"],
            -CATEGORY_PRIORITY.get(s["category"], 10),
            s["label"],
        ),
    )
    if max_steps is not None and len(ordered) > int(max_steps):
        limit = int(max_steps)
        keep = sorted(
            ordered,
            key=lambda s: (
                -CATEGORY_PRIORITY.get(s["category"], 10),
                s["rank"],
                s["label"],
            ),
        )[:limit]
        keep_ids = {s["owned_product_id"] for s in keep}
        dropped = [s for s in ordered if s["owned_product_id"] not in keep_ids]
        ordered = [s for s in ordered if s["owned_product_id"] in keep_ids]
        reasons.append(
            {
                "type": "max_steps_applied",
                "text": (
                    f"按你确认的偏好「每日常规步骤上限 = {limit}」，本版本只保留 {limit} 个步骤。"
                    "没有把两件产品合并成一步，也没有为凑够步骤而加入资料不足的产品。"
                ),
                "dropped": [
                    {"owned_product_id": s["owned_product_id"], "label": s["label"]} for s in dropped
                ],
            }
        )
        uncertainties.append(
            "被移除的步骤仍在你的美妆柜中，只是暂时不在本计划内；如需恢复请重新生成计划。"
        )

    if pending:
        reasons.append(
            {
                "type": "pending_products",
                "text": "以下产品资料不足或有冲突，未排入计划，进入待确认列表。",
                "items": pending,
            }
        )
        uncertainties.append("待确认产品不会出现在计划中，也不会参与组合推理。")

    for note in notes:
        validation = knowledge.validate_citations(db, note.get("citation_ids", []), require=True)
        if not validation.ok:
            uncertainties.append(
                f"组合提示「{note.get('ingredient_inci') or note.get('type')}」因引用校验失败被移除。"
            )
    notes = [
        n
        for n in notes
        if knowledge.validate_citations(db, n.get("citation_ids", []), require=True).ok
    ]

    # --- persist --------------------------------------------------------
    input_snapshot = {
        "products": [
            {
                "id": p.id,
                "catalog_product_id": p.catalog_product_id,
                "usage_status": p.usage_status,
                "lifecycle_status": p.lifecycle_status,
                "version": p.version,
            }
            for p in products
        ],
        "max_steps": max_steps,
        "preferences": memory_service.active_records(
            db, tenant_id=tenant_id, user_id=user_id, kinds=["explicit_preference", "confirmed_fact"]
        )
        and [
            {"key": r.key, "value": r.value.get("value")}
            for r in memory_service.active_records(
                db, tenant_id=tenant_id, user_id=user_id, kinds=["explicit_preference", "confirmed_fact"]
            )
        ],
        "excluded": sorted(set(exclude_owned_ids)),
    }
    snapshot_hash = _snapshot_hash(input_snapshot)

    if source_plan is not None:
        parent = active or source_plan
        version = _next_version(db, tenant_id=tenant_id, user_id=user_id)
        plan = RoutinePlan(
            tenant_id=tenant_id,
            user_id=user_id,
            version=version,
            status="draft",
            parent_id=parent.id if parent else None,
            input_snapshot_hash=snapshot_hash,
            reasons=reasons,
            pending_products=pending,
            combination_notes=notes,
            uncertainties=uncertainties,
            trigger=trigger,
        )
    else:
        version = _next_version(db, tenant_id=tenant_id, user_id=user_id)
        plan = RoutinePlan(
            tenant_id=tenant_id,
            user_id=user_id,
            version=version,
            status="draft",
            parent_id=active.id if active else None,
            input_snapshot_hash=snapshot_hash,
            reasons=reasons,
            pending_products=pending,
            combination_notes=notes,
            uncertainties=uncertainties,
            trigger=trigger,
        )
    db.add(plan)
    db.flush()

    steps: list[RoutineStep] = []
    positions: dict[str, int] = {}
    for payload in ordered:
        period = payload["period"]
        positions[period] = positions.get(period, 0) + 1
        step = RoutineStep(
            plan_id=plan.id,
            period=period,
            position=positions[period],
            owned_product_id=payload["owned_product_id"],
            catalog_product_id=payload["catalog_product_id"],
            label=payload["label"],
            instruction=payload["instruction"],
            frequency=payload["frequency"],
            basis=payload["basis"],
            citation_ids=payload["citation_ids"],
            review_flag=payload["review_flag"],
            review_note=payload["review_note"],
            is_general_advice=payload["is_general_advice"],
        )
        db.add(step)
        steps.append(step)
    db.flush()

    diff = compute_diff(db, previous=active, steps=steps)
    plan.diff = diff
    if dropped:
        plan.reasons = [*plan.reasons, {"type": "dropped_steps", "items": [
            {"label": s["label"], "owned_product_id": s["owned_product_id"]} for s in dropped
        ]}]
    db.flush()

    audit.record(
        db,
        action="routine.draft_created",
        actor_user_id=actor or user_id,
        tenant_id=tenant_id,
        entity_type="routine_plan",
        entity_id=plan.id,
        meta={"version": plan.version, "steps": len(steps), "pending": len(pending), "trigger": trigger},
    )
    return DraftResult(
        plan=plan,
        steps=steps,
        pending_products=pending,
        combination_notes=notes,
        skipped_combination=skipped,
        questions=questions,
        reasons=plan.reasons,
        uncertainties=uncertainties,
    )


def compute_diff(
    db: Session, *, previous: RoutinePlan | None, steps: Sequence[RoutineStep]
) -> dict[str, Any]:
    if previous is None:
        return {
            "base_version": None,
            "added": [{"label": s.label, "period": s.period, "reason": "新计划" } for s in steps],
            "removed": [],
            "changed": [],
            "summary": f"首次计划，共 {len(steps)} 个步骤。",
        }
    old_steps = _plan_steps(db, previous.id)
    old_by_product = {s.owned_product_id: s for s in old_steps if s.owned_product_id}
    new_by_product = {s.owned_product_id: s for s in steps if s.owned_product_id}
    added = [
        {"label": s.label, "period": s.period, "reason": "新加入"}
        for pid, s in new_by_product.items()
        if pid not in old_by_product
    ]
    removed = [
        {"label": s.label, "period": s.period, "reason": "本版本未包含"}
        for pid, s in old_by_product.items()
        if pid not in new_by_product
    ]
    changed = []
    for pid, new_step in new_by_product.items():
        old_step = old_by_product.get(pid)
        if old_step is None:
            continue
        deltas = []
        if old_step.period != new_step.period:
            deltas.append({"field": "period", "from": old_step.period, "to": new_step.period})
        if old_step.instruction != new_step.instruction:
            deltas.append({"field": "instruction", "from": old_step.instruction, "to": new_step.instruction})
        if old_step.frequency != new_step.frequency:
            deltas.append({"field": "frequency", "from": old_step.frequency, "to": new_step.frequency})
        if deltas:
            changed.append({"label": new_step.label, "deltas": deltas})
    return {
        "base_version": previous.version,
        "added": added,
        "removed": removed,
        "changed": changed,
        "summary": f"相对 v{previous.version}：新增 {len(added)}、移除 {len(removed)}、调整 {len(changed)}。",
    }


def validate_for_acceptance(db: Session, plan: RoutinePlan) -> list[dict[str, Any]]:
    """Acceptance time re-validation. Returns the list of blocking problems."""
    problems: list[dict[str, Any]] = []
    steps = _plan_steps(db, plan.id)
    for step in steps:
        if not step.owned_product_id:
            continue
        product = db.get(OwnedProduct, step.owned_product_id)
        if product is None or product.deleted_at is not None:
            problems.append(
                {"step": step.label, "code": "PRODUCT_DELETED", "message": "引用的产品已被删除。"}
            )
            continue
        if product.usage_status != "active" or product.lifecycle_status in {"finished", "discarded"}:
            problems.append(
                {
                    "step": step.label,
                    "code": "PRODUCT_NOT_USABLE",
                    "message": "引用的产品已暂停或已用完，计划需要复核。",
                }
            )
        validation = knowledge.validate_citations(
            db, step.citation_ids, expected_product_id=step.catalog_product_id, require=True
        )
        if not validation.ok:
            problems.append(
                {
                    "step": step.label,
                    "code": validation.error_code or "SOURCE_MISSING",
                    "message": "引用的资料来源已撤销或与产品版本不符。",
                    "details": validation.to_dict(),
                }
            )
    return problems


def accept_draft(
    db: Session,
    *,
    plan: RoutinePlan,
    expected_version: int | None,
    actor: str | None = None,
    allow_stale: bool = False,
) -> RoutinePlan:
    if plan.status != "draft":
        raise VersionConflictError(
            "该草稿已被处理（可能已接受或被替换），请刷新查看当前版本。",
            details={"status": plan.status, "plan_id": plan.id},
        )
    if expected_version is not None and plan.version != expected_version:
        raise VersionConflictError(
            "计划版本不一致，请刷新后重试",
            details={"expected": expected_version, "actual": plan.version},
        )
    problems = validate_for_acceptance(db, plan)
    if problems and not allow_stale:
        plan.needs_review = True
        plan.needs_review_reason = "；".join(p["message"] for p in problems)
        db.flush()
        raise StaleDraftError(
            "计划内容已失效（产品状态或资料来源发生变化），请复核后重新生成。",
            details={"problems": problems},
        )
    current = _active_plan(db, tenant_id=plan.tenant_id, user_id=plan.user_id)
    if current is not None and current.id != plan.id:
        current.status = "superseded"
        current.superseded_at = clock_now(db)
        db.flush()
    plan.status = "active"
    plan.accepted_at = clock_now(db)
    plan.needs_review = False
    db.flush()
    audit.record(
        db,
        action="routine.accepted",
        actor_user_id=actor or plan.user_id,
        tenant_id=plan.tenant_id,
        entity_type="routine_plan",
        entity_id=plan.id,
        meta={"version": plan.version, "superseded": current.id if current else None},
    )
    return plan


def restore_to_draft(
    db: Session, *, plan: RoutinePlan, actor: str | None = None
) -> DraftResult:
    """Restore a historical version as a NEW draft; never overwrite the past."""
    if plan.tenant_id is None:
        raise not_found("计划")
    return generate_draft(
        db,
        tenant_id=plan.tenant_id,
        user_id=plan.user_id,
        actor=actor,
        trigger=f"restore_v{plan.version}",
        source_plan=plan,
        extra_reasons=[
            {
                "type": "restored_from_history",
                "text": f"本草稿基于历史版本 v{plan.version} 重新生成；历史版本保持只读。",
            }
        ],
    )


def review_decision(
    db: Session,
    *,
    prompt: ReviewPrompt,
    action: str,
    actor: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """Handle a feedback review prompt. The plan only changes after explicit choice."""
    if prompt.status != "open":
        raise ValidationError("该复核问题已处理")
    if action not in {"pause", "keep", "adjust"}:
        raise ValidationError("action 只能是 pause / keep / adjust")
    plan = db.get(RoutinePlan, prompt.plan_id) if prompt.plan_id else None
    result: dict[str, Any] = {"action": action, "plan_changed": False}
    now = clock_now(db)
    if action == "keep":
        prompt.status = "resolved"
        prompt.decision = "keep"
        prompt.decision_note = note
        prompt.resolved_at = now
        db.flush()
        result.update(
            {
                "message": "已记录：保持当前计划不变。负面反馈保留在记忆中，后续生成计划时会带上复核标记。",
                "plan_id": plan.id if plan else None,
                "plan_version": plan.version if plan else None,
            }
        )
        audit.record(
            db,
            action="routine.review_keep",
            actor_user_id=actor or prompt.user_id,
            tenant_id=prompt.tenant_id,
            entity_type="review_prompt",
            entity_id=prompt.id,
            meta={},
        )
        return result
    if action == "adjust":
        prompt.status = "resolved"
        prompt.decision = "adjust"
        prompt.decision_note = note
        prompt.resolved_at = now
        db.flush()
        result.update(
            {
                "message": "需要再确认两点信息后生成新草稿。",
                "questions": [
                    {
                        "key": "review.timing",
                        "question": "刺痛是在使用后多久出现的？",
                        "why": "发生时间会影响是否需要改变使用频率或间隔。",
                    },
                    {
                        "key": "review.combination",
                        "question": "当时还同时使用了哪些产品？",
                        "why": "同一时段的其他产品会影响如何调整步骤。",
                    },
                ],
                "plan_id": plan.id if plan else None,
                "plan_version": plan.version if plan else None,
            }
        )
        audit.record(
            db,
            action="routine.review_adjust",
            actor_user_id=actor or prompt.user_id,
            tenant_id=prompt.tenant_id,
            entity_type="review_prompt",
            entity_id=prompt.id,
            meta={},
        )
        return result

    # pause -> new DRAFT only, requires explicit acceptance
    draft = generate_draft(
        db,
        tenant_id=prompt.tenant_id,
        user_id=prompt.user_id,
        actor=actor,
        trigger="feedback_review_pause",
        exclude_owned_ids=[prompt.owned_product_id] if prompt.owned_product_id else [],
        extra_reasons=[
            {
                "type": "feedback_review",
                "text": (
                    "根据你的选择，新草稿暂停了该步骤。本草稿尚未生效，需要你确认接受。"
                    "反馈仍保留在记忆中。"
                ),
                "owned_product_id": prompt.owned_product_id,
            }
        ],
    )
    prompt.status = "resolved"
    prompt.decision = "pause"
    prompt.decision_note = note
    prompt.resolved_at = now
    prompt.resulting_plan_id = draft.plan.id
    db.flush()
    result.update(
        {
            "message": "已生成新草稿（尚未生效），请确认后接受。",
            "plan_id": draft.plan.id,
            "plan_version": draft.plan.version,
            "plan_changed": False,
            "draft_created": True,
        }
    )
    audit.record(
        db,
        action="routine.review_pause_draft",
        actor_user_id=actor or prompt.user_id,
        tenant_id=prompt.tenant_id,
        entity_type="review_prompt",
        entity_id=prompt.id,
        meta={"draft_plan_id": draft.plan.id},
    )
    return result


def get_plan(db: Session, *, tenant_id: str, user_id: str, plan_id: str) -> RoutinePlan:
    row = db.get(RoutinePlan, plan_id)
    if row is None or row.tenant_id != tenant_id or row.user_id != user_id:
        raise not_found("计划")
    return row


def list_plans(db: Session, *, tenant_id: str, user_id: str) -> list[RoutinePlan]:
    return list(
        db.execute(
            select(RoutinePlan)
            .where(RoutinePlan.tenant_id == tenant_id, RoutinePlan.user_id == user_id)
            .order_by(RoutinePlan.version.desc())
        ).scalars()
    )


def serialize_step(db: Session, step: RoutineStep) -> dict[str, Any]:
    citations = [c.to_dict() for c in knowledge.resolve_citations(db, step.citation_ids)]
    return {
        "id": step.id,
        "plan_id": step.plan_id,
        "period": step.period,
        "position": step.position,
        "owned_product_id": step.owned_product_id,
        "catalog_product_id": step.catalog_product_id,
        "label": step.label,
        "instruction": step.instruction,
        "frequency": step.frequency,
        "basis": step.basis,
        "citation_ids": list(step.citation_ids or []),
        "citations": citations,
        "review_flag": step.review_flag,
        "review_note": step.review_note,
        "is_general_advice": step.is_general_advice,
    }


def serialize_plan(db: Session, plan: RoutinePlan, *, include_steps: bool = True) -> dict[str, Any]:
    steps = _plan_steps(db, plan.id) if include_steps else []
    return {
        "id": plan.id,
        "version": plan.version,
        "status": plan.status,
        "parent_id": plan.parent_id,
        "trigger": plan.trigger,
        "reasons": plan.reasons,
        "diff": plan.diff,
        "pending_products": plan.pending_products,
        "combination_notes": plan.combination_notes,
        "uncertainties": plan.uncertainties,
        "needs_review": plan.needs_review,
        "needs_review_reason": plan.needs_review_reason,
        "model_mode": plan.model_mode,
        "accepted_at": plan.accepted_at.isoformat() if plan.accepted_at else None,
        "superseded_at": plan.superseded_at.isoformat() if plan.superseded_at else None,
        "created_at": plan.created_at.isoformat(),
        "input_snapshot_hash": plan.input_snapshot_hash,
        "steps": [serialize_step(db, s) for s in steps],
    }
