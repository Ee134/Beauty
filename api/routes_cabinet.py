"""Cabinet: imports, owned products, catalog search and source viewing."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from ..knowledge import service as knowledge
from ..models import CatalogProduct, KnowledgeChunk, KnowledgeSource, OwnedProduct
from ..services import cabinet as cabinet_service
from ..services import imports as import_service
from ..services.errors import not_found
from .deps import ClockInfo, CurrentAuth, DbSession, IdempotencyKey, SettingsDep
from .validators import to_utc

router = APIRouter()


class OwnedProductCreate(BaseModel):
    _normalise = field_validator("purchase_date", "opened_date", "expiry_date", mode="after")(
        lambda v: to_utc(v)
    )

    custom_name: str = Field(min_length=1, max_length=200)
    catalog_product_id: str | None = None
    match_status: Literal["matched", "low_confidence", "custom"] = "custom"
    purchase_date: datetime | None = None
    opened_date: datetime | None = None
    expiry_date: datetime | None = None
    expiry_source: Literal["packaging", "user_confirmed", "pao_derived", "unknown"] = "unknown"
    pao_months: int | None = Field(default=None, ge=1, le=120)
    lifecycle_status: Literal["unopened", "opened", "finished", "discarded", "unknown"] = "unknown"
    usage_status: Literal["active", "paused", "unknown"] = "active"
    size: str | None = None
    notes: str | None = None


class OwnedProductPatch(BaseModel):
    _normalise = field_validator("purchase_date", "opened_date", "expiry_date", mode="after")(
        lambda v: to_utc(v)
    )

    expected_version: int | None = None
    custom_name: str | None = None
    purchase_date: datetime | None = None
    opened_date: datetime | None = None
    expiry_date: datetime | None = None
    expiry_source: str | None = None
    pao_months: int | None = Field(default=None, ge=1, le=120)
    lifecycle_status: str | None = None
    usage_status: str | None = None
    size: str | None = None
    notes: str | None = None
    review_flag: bool | None = None
    review_note: str | None = None


class ConfirmImportItem(BaseModel):
    _normalise = field_validator("purchase_date", "opened_date", mode="after")(lambda v: to_utc(v))

    raw_name: str | None = None
    custom_name: str | None = None
    catalog_product_id: str | None = None
    quantity: int = Field(default=1, ge=1, le=10)
    size: str | None = None
    match_status: Literal["matched", "low_confidence", "custom"] = "matched"
    purchase_date: datetime | None = None
    opened_date: datetime | None = None
    lifecycle_status: Literal["unopened", "opened", "finished", "discarded", "unknown"] = "unopened"


class ConfirmImportRequest(BaseModel):
    items: list[ConfirmImportItem] = Field(min_length=1)


@router.post("/imports", status_code=201)
async def create_import(
    auth: CurrentAuth,
    db: DbSession,
    settings: SettingsDep,
    idem: IdempotencyKey,
    file: Annotated[UploadFile, File()],
    note: Annotated[str | None, Form()] = None,
) -> dict[str, Any]:
    data = await file.read()
    batch, duplicate = import_service.create_batch(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        data=data,
        filename=file.filename or "upload",
        declared_mime=file.content_type,
        settings=settings,
        idempotency_key=idem,
        actor=auth.user_id,
    )
    db.commit()
    payload = import_service.serialize_batch(batch, settings)
    payload["duplicate_upload"] = duplicate
    if duplicate:
        payload["notice"] = "该文件此前已上传，未重复创建批次（同用户文件去重）。"
    return payload


@router.get("/imports")
def list_imports(auth: CurrentAuth, db: DbSession, settings: SettingsDep) -> dict[str, Any]:
    rows = import_service.list_batches(db, tenant_id=auth.tenant_id, user_id=auth.user_id)
    return {"batches": [import_service.serialize_batch(b, settings) for b in rows]}


@router.get("/imports/{batch_id}")
def get_import(
    batch_id: str, auth: CurrentAuth, db: DbSession, settings: SettingsDep
) -> dict[str, Any]:
    batch = import_service.get_batch(db, tenant_id=auth.tenant_id, user_id=auth.user_id, batch_id=batch_id)
    return import_service.serialize_batch(batch, settings)


@router.post("/imports/{batch_id}/confirm")
def confirm_import(
    batch_id: str,
    payload: ConfirmImportRequest,
    auth: CurrentAuth,
    db: DbSession,
    idem: IdempotencyKey,
) -> dict[str, Any]:
    batch = import_service.get_batch(db, tenant_id=auth.tenant_id, user_id=auth.user_id, batch_id=batch_id)
    result = import_service.confirm_batch(
        db,
        batch=batch,
        items=[item.model_dump() for item in payload.items],
        idempotency_key=idem,
        actor=auth.user_id,
    )
    db.commit()
    return result


@router.get("/owned-products")
def list_owned_products(
    auth: CurrentAuth,
    db: DbSession,
    include_deleted: bool = Query(default=False),
    usage_status: Annotated[list[str] | None, Query()] = None,
) -> dict[str, Any]:
    rows = cabinet_service.list_owned(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        include_deleted=include_deleted,
        usage_status=usage_status,
    )
    return {
        "products": [cabinet_service.serialize(p) for p in rows],
        "notice": "多件同 SKU 各自独立记录；暂停不等于未开封。",
    }


@router.post("/owned-products", status_code=201)
def create_owned_product(
    payload: OwnedProductCreate, auth: CurrentAuth, db: DbSession
) -> dict[str, Any]:
    product = cabinet_service.create_owned(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        actor=auth.user_id,
        **payload.model_dump(),
    )
    db.commit()
    return cabinet_service.serialize(product)


@router.get("/owned-products/{owned_id}")
def get_owned_product(owned_id: str, auth: CurrentAuth, db: DbSession) -> dict[str, Any]:
    product = cabinet_service.get_owned(
        db, tenant_id=auth.tenant_id, user_id=auth.user_id, owned_id=owned_id
    )
    data = cabinet_service.serialize(product)
    data["expiry_assessment"] = cabinet_service.assess_expiry(product).to_dict()
    sources: list[dict[str, Any]] = []
    if product.catalog_product_id:
        catalog = db.get(CatalogProduct, product.catalog_product_id)
        pk = knowledge.load_product_knowledge(db, catalog)
        sources = [citation.to_dict() for citation in knowledge.resolve_citations(
            db, [chunk.id for chunk, _ in pk.usage_instructions + pk.frequencies + pk.order_hints]
        )]
        data["knowledge"] = {
            "has_approved_sources": pk.has_sources,
            "error_code": pk.error_code,
            "message": pk.message,
        }
    data["sources"] = sources
    return data


@router.patch("/owned-products/{owned_id}")
def patch_owned_product(
    owned_id: str, payload: OwnedProductPatch, auth: CurrentAuth, db: DbSession
) -> dict[str, Any]:
    product = cabinet_service.get_owned(
        db, tenant_id=auth.tenant_id, user_id=auth.user_id, owned_id=owned_id
    )
    changes = payload.model_dump(exclude_unset=True, exclude={"expected_version"})
    cabinet_service.update_owned(
        db,
        product,
        expected_version=payload.expected_version,
        changes=changes,
        actor=auth.user_id,
    )
    db.commit()
    return cabinet_service.serialize(product)


@router.delete("/owned-products/{owned_id}")
def delete_owned_product(owned_id: str, auth: CurrentAuth, db: DbSession) -> dict[str, Any]:
    product = cabinet_service.get_owned(
        db, tenant_id=auth.tenant_id, user_id=auth.user_id, owned_id=owned_id
    )
    cabinet_service.delete_owned(db, product, actor=auth.user_id)
    db.commit()
    return {"deleted": True, "id": owned_id, "notice": "软删除，不再参与计划与推理。"}


@router.get("/catalog/search")
def search_catalog(
    auth: CurrentAuth,
    db: DbSession,
    q: str = Query(min_length=1),
    region: str | None = None,
) -> dict[str, Any]:
    results = knowledge.match_catalog_products(db, q, limit=8)
    if region:
        results = [r for r in results if r["region"] == region]
    return {"candidates": results, "notice": "候选需要用户确认后才会入柜。"}


@router.get("/sources/{source_id}")
def get_source(source_id: str, auth: CurrentAuth, db: DbSession) -> dict[str, Any]:
    source = db.get(KnowledgeSource, source_id)
    if source is None:
        raise not_found("来源")
    chunks = list(
        db.execute(select(KnowledgeChunk).where(KnowledgeChunk.source_id == source_id)).scalars()
    )
    return {
        "id": source.id,
        "title": source.title,
        "publisher": source.publisher,
        "source_type": source.source_type,
        "url": source.url,
        "file_ref": source.file_ref,
        "region": source.region,
        "status": source.status,
        "is_demo": source.is_demo,
        "retrieved_at": source.retrieved_at.isoformat() if source.retrieved_at else None,
        "reviewed_at": source.reviewed_at.isoformat() if source.reviewed_at else None,
        "approval_note": source.approval_note,
        "conflict_group": source.conflict_group,
        "chunks": [
            {
                "id": c.id,
                "locator": c.locator,
                "heading": c.heading,
                "text": c.text,
                "claim_types": c.claim_types,
                "is_demo": c.is_demo,
            }
            for c in chunks
        ],
        "notice": (
            "该来源为用户上传截图，只能证明其上传内容，不作为批准功效知识。"
            if source.source_type == "user_upload"
            else "来源按产品版本与地区标注；冲突来源会暂停相关确定性建议。"
        ),
    }


@router.get("/catalog/{catalog_product_id}")
def get_catalog_product(catalog_product_id: str, auth: CurrentAuth, db: DbSession) -> dict[str, Any]:
    product = db.get(CatalogProduct, catalog_product_id)
    if product is None:
        raise not_found("目录产品")
    summary = knowledge.source_status_summary(db, product.id)
    return {
        "id": product.id,
        "brand": product.brand,
        "name": product.name,
        "category": product.category,
        "region": product.region,
        "variant": product.variant,
        "formula_version": product.formula_version,
        "size": product.size,
        "aliases": product.aliases,
        "verification_status": product.verification_status,
        "is_demo": product.is_demo,
        "notes": product.notes,
        "sources": summary,
        "notice": (
            "虚构演示 SKU（DEMO）：不代表任何真实品牌或配方。"
            if product.is_demo
            else "真实 SKU：资料来源为品牌官网公开页面，审核由演示种子流程完成。"
        ),
    }
