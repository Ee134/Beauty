"""Vision / OCR adapters for product import.

`mock` recognises only the built-in demo screenshots, by file hash. It never
pretends to read an arbitrary photo. `live` sends the stored image to the
configured model adapter with a strict JSON schema; without credentials it
reports MODEL_UNAVAILABLE instead of falling back to mock.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import Settings, get_settings
from ..knowledge import service as knowledge
from ..models import ImportBatch
from ..services.errors import ModelUnavailableError

MANIFEST_NAME = "manifest.json"


@dataclass
class VisionResult:
    candidates: list[dict[str, Any]]
    raw_text: str | None
    notes: str | None
    provider: str
    mode: str


def manifest_path(settings: Settings) -> Path:
    return Path(settings.fixtures_path) / "imports" / MANIFEST_NAME


def load_manifest(settings: Settings) -> dict[str, Any]:
    path = manifest_path(settings)
    if not path.exists():
        return {"fixtures": []}
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


class MockVisionProvider:
    name = "mock-fixture"
    mode = "mock"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def extract(self, db: Any, *, batch: ImportBatch, settings: Settings) -> dict[str, Any]:
        manifest = load_manifest(settings)
        entry = next(
            (f for f in manifest.get("fixtures", []) if f["sha256"] == batch.file_hash), None
        )
        if entry is None:
            return {
                "candidates": [],
                "raw_text": None,
                "notes": (
                    "mock 模式只识别内置演示截图样本，未包含这张图片。"
                    "请使用「手动添加产品」，或上传演示截图 "
                    + "、".join(f["filename"] for f in manifest.get("fixtures", []))
                ),
                "provider": self.name,
                "mode": self.mode,
            }
        candidates = []
        for item in entry["candidates"]:
            matches = knowledge.match_catalog_products(db, item["raw_name"], limit=3)
            best = matches[0] if matches else None
            candidates.append(
                {
                    "raw_name": item["raw_name"],
                    "brand": item.get("brand"),
                    "quantity": item.get("quantity", 1),
                    "size": item.get("size"),
                    "confidence": item.get("confidence", 0.9),
                    "match_status": "matched" if best and best["score"] >= 0.8 else "low_confidence",
                    "catalog_product_id": best["catalog_product_id"] if best else None,
                    "matched_name": best["name"] if best else None,
                    "match_reasons": best["match_reasons"] if best else ["目录中未找到候选，需手动指定"],
                    "candidates": matches,
                    "evidence_text": item.get("evidence_text"),
                    "is_demo": True,
                }
            )
        return {
            "candidates": candidates,
            "raw_text": entry.get("raw_text"),
            "notes": entry.get("notice")
            or "mock 模式：候选来自内置演示截图样本，不代表真实 OCR/视觉识别能力。",
            "provider": self.name,
            "mode": self.mode,
        }


class LiveVisionProvider:
    name = "model-vision"
    mode = "live"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def extract(self, db: Any, *, batch: ImportBatch, settings: Settings) -> dict[str, Any]:
        from ..agent import prompts
        from ..providers.model import get_model_provider

        provider = get_model_provider(settings)
        if not getattr(provider, "available", False):
            raise ModelUnavailableError(
                "视觉识别未配置可用凭据，imports 无法在 live 模式完成；可显式切换到 VISION_MODE=mock。"
            )
        if not batch.storage_key:
            raise ModelUnavailableError("上传文件已按保留策略删除，无法重新识别。")
        path = settings.upload_path / Path(batch.storage_key).name
        if not path.exists():
            raise ModelUnavailableError("上传文件不存在（可能已过期删除）。")
        data = base64.b64encode(path.read_bytes()).decode("ascii")
        response = provider.complete_json(
            system_prompt=prompts.IMPORT_PROMPT,
            user_payload={"task": "extract_order_lines", "filename": batch.original_filename},
            schema_name="ImportExtraction",
            schema={},
            images=[{"mime": batch.mime_type or "image/png", "data": data}],
        )
        payload = response.payload
        candidates = []
        for item in payload.get("candidates", []) or []:
            matches = knowledge.match_catalog_products(db, str(item.get("raw_name") or ""), limit=3)
            best = matches[0] if matches else None
            candidates.append(
                {
                    "raw_name": item.get("raw_name"),
                    "brand": item.get("brand"),
                    "quantity": item.get("quantity", 1),
                    "size": item.get("size"),
                    "confidence": item.get("confidence", 0.5),
                    "match_status": item.get("match_status", "low_confidence"),
                    "catalog_product_id": best["catalog_product_id"] if best else None,
                    "matched_name": best["name"] if best else None,
                    "match_reasons": (item.get("match_reasons") or [])
                    or (best["match_reasons"] if best else []),
                    "candidates": matches,
                    "evidence_text": item.get("evidence_text"),
                    "is_demo": False,
                }
            )
        return {
            "candidates": candidates,
            "raw_text": payload.get("raw_text"),
            "notes": payload.get("notes"),
            "provider": self.name,
            "mode": self.mode,
        }


def get_vision_provider(settings: Settings | None = None) -> Any:
    settings = settings or get_settings()
    if settings.vision_mode == "live":
        return LiveVisionProvider(settings)
    return MockVisionProvider(settings)
