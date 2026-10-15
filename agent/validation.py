"""Server-side validation of model output.

The model never decides permissions or state. Everything it returns is checked
against the database here: citations must exist and be approved for the right
product version, entity ids must belong to the caller, and the answer must not
claim things that did not happen (spec 8, 9.1, 11).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from ..knowledge import service as knowledge
from ..models import CatalogProduct, ImportBatch, MemoryRecord, OwnedProduct, ReviewPrompt, ServiceTicket
from ..services.errors import InvalidModelOutputError

SUCCESS_CLAIMS = [
    (r"已生成计划", "routine_draft"),
    (r"计划已生效", "routine_accept"),
    (r"已提交工单", "handoff_submit"),
    (r"品牌已收到", "handoff_submit"),
    (r"已自动删除", "memory_delete"),
    (r"已导入美妆柜", "import_confirm"),
]

INJECTION_PATTERNS = [
    r"忽略(以上|之前|上述).{0,6}(指令|规则)",
    r"ignore (all )?(previous|above) instructions",
    r"system prompt",
    r"你现在是",
    r"提交退款",
    r"把.{0,6}用户.{0,6}数据.{0,6}(发给|导出)",
    r"跳过.{0,4}(确认|验证)",
    r"直接接受.{0,6}计划",
]


@dataclass
class ValidationReport:
    ok: bool
    errors: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    dropped_citation_ids: list[str] = field(default_factory=list)
    injection_hits: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "errors": self.errors,
            "warnings": self.warnings,
            "citation_count": len(self.citations),
            "dropped_citations": self.dropped_citation_ids,
            "injection_hits": self.injection_hits,
        }


def detect_injection(text: str | None) -> list[str]:
    """Flag instruction-like content. Such content is data, never an instruction."""
    if not text:
        return []
    return [p for p in INJECTION_PATTERNS if re.search(p, text, flags=re.IGNORECASE)]


def validate_citations(
    db: Session,
    citation_ids: list[str],
    *,
    expected_product_id: str | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    valid: list[dict[str, Any]] = []
    dropped: list[str] = []
    for cid in dict.fromkeys(citation_ids or []):
        if not cid:
            continue
        result = knowledge.validate_citations(
            db, [cid], expected_product_id=expected_product_id, require=True
        )
        if result.ok and result.valid:
            valid.append(result.valid[0].to_dict())
        else:
            dropped.append(cid)
    return valid, dropped


def validate_entity_ids(
    db: Session, *, tenant_id: str, user_id: str, entities: dict[str, str]
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    checks = {
        "owned_product": OwnedProduct,
        "catalog_product": CatalogProduct,
        "memory_record": MemoryRecord,
        "review_prompt": ReviewPrompt,
        "service_ticket": ServiceTicket,
        "import_batch": ImportBatch,
    }
    for kind, entity_id in entities.items():
        model = checks.get(kind)
        if model is None or not entity_id:
            continue
        row = db.get(model, entity_id)
        if row is None:
            errors.append({"code": "UNKNOWN_ENTITY", "kind": kind, "entity_id": entity_id})
            continue
        row_tenant = getattr(row, "tenant_id", None)
        row_user = getattr(row, "user_id", None)
        if row_tenant is not None and row_tenant != tenant_id:
            errors.append({"code": "CROSS_TENANT_ENTITY", "kind": kind, "entity_id": entity_id})
        elif row_user is not None and row_user != user_id:
            errors.append({"code": "CROSS_USER_ENTITY", "kind": kind, "entity_id": entity_id})
    return errors


def check_answer_consistency(answer: str, write_results: dict[str, Any]) -> list[str]:
    """The answer must not claim an action that failed or never ran."""
    problems: list[str] = []
    for pattern, action in SUCCESS_CLAIMS:
        if not re.search(pattern, answer or ""):
            continue
        if action in {"routine_accept", "handoff_submit", "memory_delete", "import_confirm"}:
            problems.append(
                f"回答中出现了「{pattern}」，但该动作只能由用户通过确认 API 触发；请改写为草稿或待确认状态。"
            )
        elif action == "routine_draft" and (write_results.get("routine_draft") or {}).get("error"):
            problems.append("计划草稿创建失败，但回答声称已生成。")
    return problems


def sanitize_answer(answer: str, write_results: dict[str, Any]) -> str:
    """Deterministic rewrite when the model over-claims. Never silently keeps a lie."""
    text = answer or ""
    routine = write_results.get("routine_draft") or {}
    if routine.get("error") and re.search(r"已(为)?你生成计划草稿", text):
        text += f"\n（更正：计划草稿实际未生成，原因：{routine['error']}）"
    handoff = write_results.get("handoff_draft") or {}
    if handoff.get("error") and re.search(r"已(生成|提交)交接", text):
        text += f"\n（更正：交接草稿实际未生成，原因：{handoff['error']}）"
    return text


def validate_turn(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    answer: str,
    citation_ids: list[str],
    write_results: dict[str, Any],
    entity_refs: dict[str, str] | None = None,
    retrieved_texts: list[str] | None = None,
) -> ValidationReport:
    report = ValidationReport(ok=True)
    valid_citations, dropped = validate_citations(db, citation_ids)
    report.citations = valid_citations
    report.dropped_citation_ids = dropped
    if dropped:
        report.ok = False
        report.errors.append(
            {
                "code": "SOURCE_MISSING",
                "message": "模型返回了不存在的引用，相关建议已被阻止。",
                "citation_ids": dropped,
            }
        )
    entity_errors = validate_entity_ids(
        db, tenant_id=tenant_id, user_id=user_id, entities=entity_refs or {}
    )
    if entity_errors:
        report.ok = False
        report.errors.extend(entity_errors)
    consistency = check_answer_consistency(answer, write_results)
    if consistency:
        report.ok = False
        report.errors.extend({"code": "INVALID_MODEL_OUTPUT", "message": m} for m in consistency)
    for text in retrieved_texts or []:
        hits = detect_injection(text)
        if hits:
            report.injection_hits.extend(hits)
    if report.injection_hits:
        report.warnings.append(
            "检索/上传内容中包含类似指令的文本，已按不可信数据处理，未改变权限或执行任何写入。"
        )
    return report


def ensure_valid(report: ValidationReport) -> None:
    if not report.ok:
        raise InvalidModelOutputError(
            "模型输出未通过服务端校验。", details={"errors": report.errors}
        )
