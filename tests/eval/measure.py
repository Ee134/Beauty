"""Shared measurement helpers.

These functions turn raw API/DB facts into explicit metric observations.  They
are used by ``scenarios.py``, ``security_scenarios.py`` and by the §14/§25.3
comparison runner, so all three settings are measured with exactly the same
rules.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Iterable

_EVAL_DIR = Path(__file__).resolve().parent
if str(_EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(_EVAL_DIR))

from harness import (  # noqa: E402
    M_ATLAS_COMPLETE,
    M_ATLAS_UNSOURCED,
    M_COMBINATION_SOURCE,
    M_FEEDBACK_TRIGGER,
    M_FORGOTTEN_REAPPEAR,
    M_KEY_ADVICE_EVIDENCE,
    M_LIFE_EXTENSION_SOURCE,
    M_MEMORY_FIELD,
    M_PRODUCT_VERSION,
    M_REPEATED_QUESTION,
    M_SIGNAL_FALSE_POSITIVE,
    M_TICKET_FIELDS,
    ScenarioContext,
    citation_rows,
    source_backed,
    version_matched,
)

REQUIRED_CARD_FIELDS = ("inci_name", "common_name", "user_signal", "data_status", "uncertainty", "disclaimer")

TICKET_REQUIRED_FIELDS = (
    "request",
    "products",
    "user_reports",
    "actions_already_taken",
    "awaiting_from_user",
    "disclaimer",
)


# --- plan level -----------------------------------------------------------


def record_combination_observations(ctx: ScenarioContext, plan: dict[str, Any]) -> None:
    """Combination advice must always carry a resolvable approved source."""
    for note in plan.get("combination_notes") or []:
        citation_ids = list(note.get("citation_ids") or [])
        good, total = source_backed(ctx, citation_ids)
        supported = bool(total) and good == total
        ctx.observe(
            M_COMBINATION_SOURCE,
            1 if supported else 0,
            1,
            note=(
                f"组合提示 type={note.get('type')} inci={note.get('ingredient_inci')} "
                f"citations={citation_ids} resolvable_approved={good}/{total}"
            ),
            ok=supported,
        )


def record_step_observations(ctx: ScenarioContext, plan: dict[str, Any]) -> None:
    """Every product-specific step needs an approved citation of the right version."""
    for step in plan.get("steps") or []:
        citation_ids = list(step.get("citation_ids") or [])
        expected = step.get("catalog_product_id")
        matched, total = version_matched(ctx, citation_ids, expected)
        version_ok = bool(total) and matched == total
        ctx.observe(
            M_PRODUCT_VERSION,
            1 if version_ok else 0,
            1,
            note=(
                f"步骤 {step.get('label')} 期望版本={expected} 引用={citation_ids} "
                f"版本匹配={matched}/{total}"
            ),
            ok=version_ok,
        )
        backed, backed_total = source_backed(ctx, citation_ids)
        evidence_ok = bool(backed_total) and backed == backed_total
        ctx.observe(
            M_KEY_ADVICE_EVIDENCE,
            1 if evidence_ok else 0,
            1,
            note=(
                f"步骤 {step.get('label')} 引用={citation_ids} "
                f"已审核={backed}/{backed_total}"
            ),
            ok=evidence_ok,
        )


# --- atlas ----------------------------------------------------------------


def card_missing_fields(card: dict[str, Any]) -> list[str]:
    """Spec 8.1.3: a card without any required field must not be generated."""
    missing = [field for field in REQUIRED_CARD_FIELDS if not card.get(field)]
    signal = card.get("user_signal") or {}
    if not signal.get("statement"):
        missing.append("user_signal.statement")
    if not signal.get("causality_notice"):
        missing.append("user_signal.causality_notice")
    status = card.get("data_status")
    effects = card.get("known_effects") or []
    notes = ((card.get("irritancy") or {}).get("notes")) or []
    if status == "approved":
        if not effects and not notes:
            missing.append("sourced_effect_or_irritancy")
    elif not card.get("data_note"):
        missing.append("data_note")
    return missing


def card_unsourced_assertions(card: dict[str, Any]) -> tuple[int, int, list[str]]:
    """(unsourced assertions, total assertions, reasons) for one card.

    A claim slot is every effect statement, every irritancy note, a non-unknown
    irritancy level, every life extension, and an ``approved`` data status that
    carries no resolvable reviewed content.  The rate is therefore always
    between 0 and 1.
    """
    unsourced = 0
    total = 0
    reasons: list[str] = []
    effects = card.get("known_effects") or []
    for effect in effects:
        total += 1
        citation = effect.get("citation") or {}
        if not citation.get("citation_id") or not citation.get("source_id"):
            unsourced += 1
            reasons.append(f"功效断言无引用：{effect.get('text')}")
    irritancy = card.get("irritancy") or {}
    notes = irritancy.get("notes") or []
    level = irritancy.get("level")
    if level not in (None, "unknown"):
        total += 1
        if not notes:
            unsourced += 1
            reasons.append(f"致敏性等级 '{level}' 无已审核引用")
    for note in notes:
        total += 1
        citation = note.get("citation") or {}
        if not citation.get("citation_id") or not citation.get("source_id"):
            unsourced += 1
            reasons.append(f"致敏性断言无引用：{note.get('text')}")
    for extension in card.get("life_extensions") or []:
        total += 1
        citation = extension.get("citation") or {}
        if not citation.get("citation_id") or not citation.get("source_id"):
            unsourced += 1
            reasons.append(f"生活延伸无引用：{extension.get('text')}")
    if card.get("data_status") == "approved" and not effects and not notes:
        total += 1
        unsourced += 1
        reasons.append("data_status=approved 但没有任何可解析的已审核内容")
    return unsourced, total, reasons


def record_atlas_observations(ctx: ScenarioContext, payload: dict[str, Any]) -> None:
    """The six atlas metrics of spec §14/§25.3, per payload."""
    cards = payload.get("cards") or []
    min_events = int(payload.get("min_events") or 3)

    for card in cards:
        missing = card_missing_fields(card)
        ctx.observe(
            M_ATLAS_COMPLETE,
            0 if missing else 1,
            1,
            note=f"卡片 {card.get('common_name')} 缺失必填项={missing}",
            ok=not missing,
        )
        unsourced, total_assertions, reasons = card_unsourced_assertions(card)
        if total_assertions:
            ctx.observe(
                M_ATLAS_UNSOURCED,
                unsourced,
                total_assertions,
                note=(
                    f"卡片 {card.get('common_name')} 无来源断言={unsourced}/{total_assertions}"
                    + (f" {reasons}" if reasons else "")
                ),
                ok=unsourced == 0,
            )
        signal = card.get("user_signal") or {}
        total = int(signal.get("total_count") or 0)
        false_positive = total < min_events
        ctx.observe(
            M_SIGNAL_FALSE_POSITIVE,
            1 if false_positive else 0,
            1,
            note=(
                f"卡片 {card.get('common_name')} 关联事件={total} "
                f"阈值={min_events} 误报={false_positive}"
            ),
            ok=not false_positive,
        )

    shown_extensions = [ext for card in cards for ext in (card.get("life_extensions") or [])]
    supported = 0
    for extension in shown_extensions:
        citation = extension.get("citation") or {}
        if citation.get("citation_id") and citation.get("source_id") and extension.get("notice"):
            supported += 1
    dropped = payload.get("dropped_life_extensions") or []
    ctx.observe(
        M_LIFE_EXTENSION_SOURCE,
        supported,
        len(shown_extensions),
        note=(
            f"展示的生活延伸 {len(shown_extensions)} 条，其中来源支持 {supported} 条；"
            f"被丢弃 {len(dropped)} 条（"
            + "；".join(f"{d.get('reason')}:{d.get('text')}" for d in dropped)
            + "）"
        ),
        ok=(supported == len(shown_extensions)) if shown_extensions else None,
    )


# --- feedback trigger -----------------------------------------------------


def record_feedback_trigger(
    ctx: ScenarioContext,
    *,
    should_trigger: bool,
    triggered: bool,
    event_id: str | None,
    note: str,
) -> None:
    if should_trigger:
        ctx.observe(
            M_FEEDBACK_TRIGGER,
            1 if triggered else 0,
            1,
            note=f"event={event_id} 应触发 实际={triggered} {note}",
            ok=triggered,
        )
    elif triggered:
        # A trigger that must not happen is an accuracy failure as well; it is
        # counted in the denominator with numerator 0.
        ctx.observe(
            M_FEEDBACK_TRIGGER,
            0,
            1,
            note=f"event={event_id} 不应触发但触发了 {note}",
            ok=False,
        )


# --- memory / questions / forgetting --------------------------------------


def record_memory_field(
    ctx: ScenarioContext, key: str, expected: Any, *, persona: str | None = None
) -> None:
    record = ctx.active_memory(key, persona)
    got = record.get("value") if record else None
    ctx.observe(
        M_MEMORY_FIELD,
        1 if got == expected else 0,
        1,
        note=f"字段 {key} 期望={expected} 实际={got}",
        ok=got == expected,
    )


def record_questions(
    ctx: ScenarioContext, questions: Iterable[dict[str, Any]], *, known_keys: set[str], where: str
) -> None:
    for question in questions or []:
        key = question.get("key") if isinstance(question, dict) else str(question)
        if not key:
            continue
        record_question(ctx, key, already_known=key in known_keys, where=where)


def record_question(
    ctx: ScenarioContext,
    key: str,
    *,
    already_known: bool,
    where: str,
) -> None:
    ctx.observe(
        M_REPEATED_QUESTION,
        1 if already_known else 0,
        1,
        note=f"提问 {key}（{where}）已知={already_known}",
        ok=not already_known,
    )


def record_forgotten(
    ctx: ScenarioContext, marker: str, *, leaked: bool, where: str
) -> None:
    ctx.observe(
        M_FORGOTTEN_REAPPEAR,
        1 if leaked else 0,
        1,
        note=f"删除内容标记 {marker} 在 {where} 中重新出现={leaked}",
        ok=not leaked,
    )


# --- tickets --------------------------------------------------------------


def ticket_missing_fields(summary: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for field in TICKET_REQUIRED_FIELDS:
        value = (summary or {}).get(field)
        if value in (None, "", [], {}):
            missing.append(field)
    if not (summary or {}).get("plan") and not (summary or {}).get("memory_records"):
        missing.append("plan/memory_records")
    disclaimer = (summary or {}).get("disclaimer") or ""
    if "非诊断" not in disclaimer:
        missing.append("disclaimer_wording(非诊断)")
    return missing


def record_ticket(ctx: ScenarioContext, summary: dict[str, Any], label: str) -> None:
    missing = ticket_missing_fields(summary)
    ctx.observe(
        M_TICKET_FIELDS,
        0 if missing else 1,
        1,
        note=f"工单 {label} 缺失字段={missing}",
        ok=not missing,
    )


# --- cross-user / confirmation helpers ------------------------------------


def leak_scan(text: Any, secrets: Iterable[str]) -> list[str]:
    blob = str(text)
    return [secret for secret in secrets if secret and secret in blob]


def citation_resolvable(ctx: ScenarioContext, citation_id: str) -> bool:
    rows = citation_rows(ctx, [citation_id])
    return bool(rows and rows[0]["exists"] and rows[0]["status"] == "approved")
