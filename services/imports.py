"""Import pipeline: validated upload, candidate extraction, confirmed cabinet write."""

from __future__ import annotations

import hashlib
import io
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any, Sequence

from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..models import CatalogProduct, ImportBatch, OwnedProduct
from ..providers.vision import get_vision_provider
from ..services import audit
from ..services import cabinet as cabinet_service
from ..services.clock import now as clock_now
from ..services.errors import ImportFailedError, ValidationError, not_found

FORMAT_TO_MIME = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
EXTENSION_TO_FORMAT = {
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".png": "PNG",
    ".webp": "WEBP",
}


def validate_upload(
    data: bytes, *, filename: str, declared_mime: str | None, settings: Settings
) -> tuple[str, str, bytes]:
    """Returns (mime, format, sanitized_bytes). EXIF is stripped by re-encoding."""
    if not data:
        raise ImportFailedError("上传文件为空")
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise ImportFailedError(f"文件超过 {settings.max_upload_mb} MB 限制")
    safe_name = Path(filename or "upload").name
    if safe_name != (filename or "").split("/")[-1] or ".." in (filename or ""):
        raise ImportFailedError("文件名包含路径穿越字符")
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            detected = (image.format or "").upper()
            width, height = image.size
            if width * height > settings.max_upload_pixels:
                raise ImportFailedError(f"图片像素超过 {settings.max_upload_pixels} 限制")
            if detected not in FORMAT_TO_MIME:
                raise ImportFailedError(f"不支持的图片格式：{detected or 'unknown'}")
            expected = EXTENSION_TO_FORMAT.get(Path(safe_name).suffix.lower())
            if expected and expected != detected:
                raise ImportFailedError(
                    f"文件扩展名与实际格式不一致（扩展名 {expected}，实际 {detected}）"
                )
            mime = FORMAT_TO_MIME[detected]
            if declared_mime and declared_mime not in settings.allowed_upload_types:
                raise ImportFailedError(f"不支持的 Content-Type：{declared_mime}")
            clean = image.convert("RGB") if detected == "JPEG" else image
            buffer = io.BytesIO()
            save_format = "JPEG" if detected == "JPEG" else detected
            if save_format == "JPEG":
                clean.save(buffer, format="JPEG", quality=90)
            else:
                clean.save(buffer, format=save_format)
            return mime, detected, buffer.getvalue()
    except UnidentifiedImageError as exc:
        raise ImportFailedError("文件不是有效的图片（可能是伪扩展名）") from exc
    except ImportFailedError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ImportFailedError(f"图片处理失败：{type(exc).__name__}") from exc


def create_batch(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    data: bytes,
    filename: str,
    declared_mime: str | None,
    settings: Settings | None = None,
    idempotency_key: str | None = None,
    actor: str | None = None,
) -> tuple[ImportBatch, bool]:
    settings = settings or get_settings()
    file_hash = hashlib.sha256(data).hexdigest()
    existing = db.execute(
        select(ImportBatch).where(
            ImportBatch.tenant_id == tenant_id,
            ImportBatch.user_id == user_id,
            ImportBatch.file_hash == file_hash,
            ImportBatch.status != "failed",
        )
    ).scalar_one_or_none()
    if existing is not None:
        audit.record(
            db,
            action="import.deduplicated",
            actor_user_id=actor or user_id,
            tenant_id=tenant_id,
            entity_type="import_batch",
            entity_id=existing.id,
            meta={"file_hash": file_hash},
        )
        return existing, True
    if idempotency_key:
        by_key = db.execute(
            select(ImportBatch).where(
                ImportBatch.tenant_id == tenant_id,
                ImportBatch.user_id == user_id,
                ImportBatch.idempotency_key == idempotency_key,
            )
        ).scalar_one_or_none()
        if by_key is not None:
            return by_key, True

    mime, fmt, clean_bytes = validate_upload(
        data, filename=filename, declared_mime=declared_mime, settings=settings
    )
    storage_name = f"{uuid.uuid4().hex}.{fmt.lower()}"
    path = settings.upload_path / storage_name
    path.write_bytes(clean_bytes)

    batch = ImportBatch(
        tenant_id=tenant_id,
        user_id=user_id,
        file_hash=file_hash,
        storage_key=storage_name,
        original_filename=Path(filename).name,
        mime_type=mime,
        byte_size=len(clean_bytes),
        status="processing",
        provider_mode=settings.vision_mode,
        extractor=settings.vision_provider,
        expires_at=clock_now(db) + timedelta(hours=settings.import_retention_hours),
        idempotency_key=idempotency_key,
    )
    db.add(batch)
    db.flush()

    provider = get_vision_provider(settings)
    try:
        result = provider.extract(db, batch=batch, settings=settings)
    except Exception as exc:  # noqa: BLE001
        batch.status = "failed"
        batch.error_code = getattr(exc, "code", "IMPORT_FAILED")
        db.flush()
        audit.record(
            db,
            action="import.failed",
            actor_user_id=actor or user_id,
            tenant_id=tenant_id,
            entity_type="import_batch",
            entity_id=batch.id,
            meta={"error": type(exc).__name__},
        )
        return batch, False
    batch.candidates = result["candidates"]
    batch.raw_text = result.get("raw_text")
    batch.provider_mode = result.get("mode", settings.vision_mode)
    batch.extractor = result.get("provider")
    batch.status = "ready"
    db.flush()
    audit.record(
        db,
        action="import.extracted",
        actor_user_id=actor or user_id,
        tenant_id=tenant_id,
        entity_type="import_batch",
        entity_id=batch.id,
        meta={
            "candidates": len(batch.candidates),
            "provider_mode": batch.provider_mode,
            "raw_text_length": len(batch.raw_text or ""),
        },
    )
    return batch, False


def get_batch(db: Session, *, tenant_id: str, user_id: str, batch_id: str) -> ImportBatch:
    row = db.get(ImportBatch, batch_id)
    if row is None or row.tenant_id != tenant_id or row.user_id != user_id:
        raise not_found("导入批次")
    return row


def list_batches(db: Session, *, tenant_id: str, user_id: str, limit: int = 20) -> list[ImportBatch]:
    return list(
        db.execute(
            select(ImportBatch)
            .where(ImportBatch.tenant_id == tenant_id, ImportBatch.user_id == user_id)
            .order_by(ImportBatch.created_at.desc())
            .limit(limit)
        ).scalars()
    )


def confirm_batch(
    db: Session,
    *,
    batch: ImportBatch,
    items: Sequence[dict[str, Any]],
    idempotency_key: str | None = None,
    actor: str | None = None,
) -> dict[str, Any]:
    """Transactionally write confirmed instances. Repeating the request is a no-op."""
    if batch.status == "confirmed":
        products = [
            db.get(OwnedProduct, pid)
            for pid in (batch.created_owned_ids or [])
        ]
        return {
            "batch_id": batch.id,
            "status": batch.status,
            "created": [cabinet_service.serialize(p) for p in products if p is not None],
            "duplicate": True,
            "notice": "该批次已确认，重复确认不会重复入柜。",
        }
    if batch.status not in {"ready", "uploaded"}:
        raise ImportFailedError(f"批次状态为 {batch.status}，无法确认")
    if idempotency_key and batch.idempotency_key == idempotency_key and batch.status == "confirmed":
        return {"batch_id": batch.id, "status": batch.status, "created": [], "duplicate": True}
    if not items:
        raise ValidationError("至少需要确认一件产品")

    candidate_pool = {c.get("raw_name"): c for c in (batch.candidates or [])}
    created: list[OwnedProduct] = []
    for index, item in enumerate(items):
        catalog_id = item.get("catalog_product_id")
        catalog: CatalogProduct | None = db.get(CatalogProduct, catalog_id) if catalog_id else None
        if catalog_id and catalog is None:
            raise ValidationError(f"第 {index + 1} 行：目录产品不存在")
        if catalog is None and not item.get("custom_name"):
            suggestion = candidate_pool.get(item.get("raw_name") or "")
            if suggestion and suggestion.get("catalog_product_id"):
                catalog = db.get(CatalogProduct, suggestion["catalog_product_id"])
            if catalog is None:
                raise ValidationError(f"第 {index + 1} 行：未指定产品名称且没有匹配候选")
        quantity = int(item.get("quantity") or 1)
        if not (1 <= quantity <= 10):
            raise ValidationError(f"第 {index + 1} 行：数量必须在 1–10 之间")
        for _ in range(quantity):
            owned = cabinet_service.create_owned(
                db,
                tenant_id=batch.tenant_id,
                user_id=batch.user_id,
                custom_name=item.get("custom_name") or (catalog.name if catalog else "未命名产品"),
                catalog_product_id=catalog.id if catalog else None,
                match_status=item.get("match_status") or ("matched" if catalog else "custom"),
                purchase_date=item.get("purchase_date"),
                opened_date=item.get("opened_date"),
                size=item.get("size") or (catalog.size if catalog else None),
                lifecycle_status=item.get("lifecycle_status") or "unopened",
                usage_status="active",
                provenance="import",
                import_batch_id=batch.id,
                actor=actor,
            )
            created.append(owned)
    # A second identical file hash must not create new instances (AC02), handled by dedupe.
    batch.created_owned_ids = [p.id for p in created]
    batch.status = "confirmed"
    batch.confirmed_at = clock_now(db)
    batch.idempotency_key = idempotency_key or batch.idempotency_key
    db.flush()
    audit.record(
        db,
        action="import.confirmed",
        actor_user_id=actor,
        tenant_id=batch.tenant_id,
        entity_type="import_batch",
        entity_id=batch.id,
        meta={"created": len(created)},
    )
    return {
        "batch_id": batch.id,
        "status": batch.status,
        "created": [cabinet_service.serialize(p) for p in created],
        "duplicate": False,
    }


def serialize_batch(batch: ImportBatch, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    low_confidence = any(
        (c.get("match_status") != "matched") or (c.get("confidence", 1) < 0.7)
        for c in (batch.candidates or [])
    )
    return {
        "id": batch.id,
        "status": batch.status,
        "candidates": batch.candidates,
        "raw_text": batch.raw_text,
        "provider_mode": batch.provider_mode,
        "extractor": batch.extractor,
        "error_code": batch.error_code,
        "file_deleted_at": batch.file_deleted_at.isoformat() if batch.file_deleted_at else None,
        "expires_at": batch.expires_at.isoformat() if batch.expires_at else None,
        "confirmed_at": batch.confirmed_at.isoformat() if batch.confirmed_at else None,
        "created_owned_ids": list(batch.created_owned_ids or []),
        "low_confidence": low_confidence,
        "retention_hours": settings.import_retention_hours,
        "notice": "截图在确认后按保留策略删除；识别结果为候选，必须由你确认才会写入美妆柜。",
    }
