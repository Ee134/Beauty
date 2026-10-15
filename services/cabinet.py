"""Cabinet: owned product instances, lifecycle/usage state and date rules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..knowledge import service as knowledge
from ..models import CatalogProduct, KnowledgeChunk, KnowledgeSource, OwnedProduct
from . import audit
from .clock import now as clock_now
from .errors import NotFoundError, ValidationError, not_found

LIFECYCLE = {"unopened", "opened", "finished", "discarded", "unknown"}
USAGE = {"active", "paused", "unknown"}

_MONTH_DAYS = 30.4375


def add_months(dt: datetime, months: int) -> datetime:
    return dt + timedelta(days=months * _MONTH_DAYS)


@dataclass
class ExpiryAssessment:
    effective_expiry: datetime | None
    source: str
    unknown_reason: str | None
    candidates: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "effective_expiry": self.effective_expiry.isoformat() if self.effective_expiry else None,
            "source": self.source,
            "unknown_reason": self.unknown_reason,
            "candidates": [
                {**c, "value": c["value"].isoformat() if c["value"] else None} for c in self.candidates
            ],
        }


def assess_expiry(product: OwnedProduct) -> ExpiryAssessment:
    """PAO is only computed when BOTH the opened date and the packaging PAO are known.

    A missing date stays unknown: nothing is guessed from the product category.
    """
    candidates: list[dict[str, Any]] = []
    if product.expiry_date is not None:
        candidates.append(
            {
                "value": product.expiry_date,
                "source": product.expiry_source or "packaging",
                "label": "包装/用户确认到期日",
            }
        )
    if product.opened_date is not None and product.pao_months:
        candidates.append(
            {
                "value": add_months(product.opened_date, int(product.pao_months)),
                "source": "pao_derived",
                "label": f"开封后 {product.pao_months} 个月（PAO）",
            }
        )
    if not candidates:
        reason = (
            "缺少包装有效期，且未同时确认开封日期与 PAO，无法计算。"
            if not (product.opened_date and product.pao_months)
            else "无可用的到期约束。"
        )
        return ExpiryAssessment(None, "unknown", reason, [])
    effective = min(c["value"] for c in candidates)
    source = "pao_derived"
    for c in candidates:
        if c["value"] == effective:
            source = c["source"]
            break
    return ExpiryAssessment(effective, source, None, candidates)


def extract_product_ingredients(db: Session, catalog_product_id: str) -> dict[str, Any]:
    """Ingredients are only taken from approved sources for this product version."""
    pk = knowledge.load_product_knowledge(db, db.get(CatalogProduct, catalog_product_id))
    actives = [i["inci"] for i in pk.ingredients]
    irritants = [i["inci"] for i in pk.irritants]
    citations = sorted({i["citation_id"] for i in pk.ingredients + pk.irritants})
    return {
        "actives": actives,
        "irritants": irritants,
        "citation_ids": citations,
        "has_sources": pk.has_sources,
        "error_code": pk.error_code,
        "message": pk.message,
    }


def sync_ingredient_linkage(db: Session, product: OwnedProduct) -> None:
    if not product.catalog_product_id:
        product.ingredient_source_status = "unmatched"
        product.key_actives = []
        product.irritant_flags = []
        return
    info = extract_product_ingredients(db, product.catalog_product_id)
    if info["error_code"] == "SOURCE_CONFLICT":
        product.ingredient_source_status = "conflict"
    elif not info["has_sources"]:
        product.ingredient_source_status = "missing"
    elif not info["actives"] and not info["irritants"]:
        product.ingredient_source_status = "no_ingredient_data"
    else:
        product.ingredient_source_status = "available"
    product.key_actives = info["actives"]
    product.irritant_flags = info["irritants"]


def list_owned(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    include_deleted: bool = False,
    usage_status: Sequence[str] | None = None,
) -> list[OwnedProduct]:
    stmt = select(OwnedProduct).where(
        OwnedProduct.tenant_id == tenant_id, OwnedProduct.user_id == user_id
    )
    if not include_deleted:
        stmt = stmt.where(OwnedProduct.deleted_at.is_(None))
    if usage_status:
        stmt = stmt.where(OwnedProduct.usage_status.in_(list(usage_status)))
    return list(db.execute(stmt.order_by(OwnedProduct.created_at)).scalars())


def get_owned(db: Session, *, tenant_id: str, user_id: str, owned_id: str) -> OwnedProduct:
    row = db.get(OwnedProduct, owned_id)
    if row is None or row.tenant_id != tenant_id or row.user_id != user_id or row.deleted_at:
        raise not_found("产品实例")
    return row


def create_owned(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    custom_name: str,
    catalog_product_id: str | None = None,
    match_status: str = "custom",
    purchase_date: datetime | None = None,
    opened_date: datetime | None = None,
    expiry_date: datetime | None = None,
    expiry_source: str = "unknown",
    pao_months: int | None = None,
    lifecycle_status: str = "unknown",
    usage_status: str = "active",
    size: str | None = None,
    notes: str | None = None,
    provenance: str = "manual",
    import_batch_id: str | None = None,
    actor: str | None = None,
) -> OwnedProduct:
    if lifecycle_status not in LIFECYCLE:
        raise ValidationError(f"lifecycle_status 非法：{lifecycle_status}")
    if usage_status not in USAGE:
        raise ValidationError(f"usage_status 非法：{usage_status}")
    catalog = db.get(CatalogProduct, catalog_product_id) if catalog_product_id else None
    if catalog_product_id and catalog is None:
        raise ValidationError("catalog_product_id 不存在")
    product = OwnedProduct(
        tenant_id=tenant_id,
        user_id=user_id,
        catalog_product_id=catalog.id if catalog else None,
        custom_name=custom_name or (catalog.name if catalog else "未命名产品"),
        match_status=match_status,
        purchase_date=purchase_date,
        opened_date=opened_date,
        expiry_date=expiry_date,
        expiry_source=expiry_source,
        pao_months=pao_months,
        lifecycle_status=lifecycle_status,
        usage_status=usage_status,
        size=size or (catalog.size if catalog else None),
        notes=notes,
        provenance=provenance,
        import_batch_id=import_batch_id,
    )
    db.add(product)
    db.flush()
    sync_ingredient_linkage(db, product)
    audit.record(
        db,
        action="owned_product.created",
        actor_user_id=actor or user_id,
        tenant_id=tenant_id,
        entity_type="owned_product",
        entity_id=product.id,
        meta={"provenance": provenance, "match_status": match_status},
    )
    return product


EDITABLE_FIELDS = {
    "custom_name",
    "purchase_date",
    "opened_date",
    "expiry_date",
    "expiry_source",
    "pao_months",
    "lifecycle_status",
    "usage_status",
    "size",
    "notes",
    "review_flag",
    "review_note",
}


def update_owned(
    db: Session,
    product: OwnedProduct,
    *,
    expected_version: int | None,
    changes: dict[str, Any],
    actor: str | None = None,
) -> OwnedProduct:
    from .errors import VersionConflictError

    if expected_version is not None and product.version != expected_version:
        raise VersionConflictError(
            "产品实例已被更新，请刷新后重试",
            details={"expected": expected_version, "actual": product.version},
        )
    unknown = set(changes) - EDITABLE_FIELDS
    if unknown:
        raise ValidationError("不支持修改的字段：" + "、".join(sorted(unknown)))
    for key, value in changes.items():
        if key == "lifecycle_status" and value not in LIFECYCLE:
            raise ValidationError(f"lifecycle_status 非法：{value}")
        if key == "usage_status" and value not in USAGE:
            raise ValidationError(f"usage_status 非法：{value}")
        setattr(product, key, value)
    if "lifecycle_status" in changes and product.lifecycle_status == "opened" and not product.opened_date:
        product.opened_date = clock_now(db)
    product.version += 1
    db.flush()
    audit.record(
        db,
        action="owned_product.updated",
        actor_user_id=actor,
        tenant_id=product.tenant_id,
        entity_type="owned_product",
        entity_id=product.id,
        meta={"fields": sorted(changes)},
    )
    return product


def delete_owned(db: Session, product: OwnedProduct, *, actor: str | None = None) -> None:
    product.deleted_at = clock_now(db)
    db.flush()
    audit.record(
        db,
        action="owned_product.deleted",
        actor_user_id=actor,
        tenant_id=product.tenant_id,
        entity_type="owned_product",
        entity_id=product.id,
        meta={},
    )


def serialize(product: OwnedProduct, db: Session | None = None) -> dict[str, Any]:
    expiry = assess_expiry(product)
    return {
        "id": product.id,
        "catalog_product_id": product.catalog_product_id,
        "custom_name": product.custom_name,
        "match_status": product.match_status,
        "purchase_date": product.purchase_date.isoformat() if product.purchase_date else None,
        "opened_date": product.opened_date.isoformat() if product.opened_date else None,
        "expiry_date": product.expiry_date.isoformat() if product.expiry_date else None,
        "expiry_source": product.expiry_source,
        "pao_months": product.pao_months,
        "effective_expiry": expiry.effective_expiry.isoformat() if expiry.effective_expiry else None,
        "effective_expiry_source": expiry.source,
        "expiry_unknown_reason": expiry.unknown_reason,
        "lifecycle_status": product.lifecycle_status,
        "usage_status": product.usage_status,
        "size": product.size,
        "key_actives": list(product.key_actives or []),
        "irritant_flags": list(product.irritant_flags or []),
        "ingredient_source_status": product.ingredient_source_status,
        "review_flag": product.review_flag,
        "review_note": product.review_note,
        "notes": product.notes,
        "provenance": product.provenance,
        "version": product.version,
        "created_at": product.created_at.isoformat(),
        "updated_at": product.updated_at.isoformat(),
    }


def usable_ids(products: Iterable[OwnedProduct]) -> set[str]:
    return {
        p.id
        for p in products
        if p.usage_status == "active" and p.lifecycle_status not in {"finished", "discarded"}
    }
