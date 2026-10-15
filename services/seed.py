"""Reproducible seed data.

Everything fictional is labelled is_demo=true and carries a DEMO marker in its
name or source title. Real SKUs (3) carry a real, fetched URL and an explicit
approval_note saying the review was done by the demo seeding pipeline, not by
the brand.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import (
    CatalogProduct,
    City,
    IngredientProfile,
    KnowledgeChunk,
    KnowledgeSource,
    MemoryRecord,
    NotificationPreference,
    OwnedProduct,
    Tenant,
    TriggerRule,
    User,
)
from ..environment import service as env_service
from ..knowledge import service as knowledge
from . import cabinet as cabinet_service
from . import routine_service
from . import usage_events as usage_service
from .clock import now as clock_now
from .errors import ValidationError

DEMO_TENANT = "DEMO-TENANT-1"

PERSONAS: dict[str, dict[str, Any]] = {
    "consumer_a": {
        "email": "demo_user_a@example.invalid",
        "display_name": "演示用户 A（反馈积累充分）",
        "role": "consumer",
    },
    "consumer_b": {
        "email": "demo_user_b@example.invalid",
        "display_name": "演示用户 B（反馈样本不足）",
        "role": "consumer",
    },
    "staff": {
        "email": "demo_staff@example.invalid",
        "display_name": "演示客服（本地演示工作台）",
        "role": "staff",
    },
    "brand": {
        "email": "demo_brand@example.invalid",
        "display_name": "演示品牌运营（合成汇总）",
        "role": "brand",
    },
}


def _load(settings: Settings, *parts: str) -> dict[str, Any]:
    path = Path(settings.data_dir).joinpath(*parts)
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _content_hash(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def is_seeded(db: Session) -> bool:
    return db.execute(select(Tenant).where(Tenant.name == "BeautyCare 演示租户")).scalar_one_or_none() is not None


def seed_catalog(db: Session, settings: Settings) -> dict[str, Any]:
    products_doc = _load(settings, "catalog", "products.json")
    demo_sources = _load(settings, "sources", "demo_sources.json")
    demo_ingredients = _load(settings, "sources", "demo_ingredients.json")
    real = _load(settings, "sources", "real_sources.json")

    key_to_product: dict[str, CatalogProduct] = {}
    for item in products_doc["products"]:
        product = CatalogProduct(
            brand=item["brand"],
            name=item["name"],
            category=item["category"],
            region=item["region"],
            variant=item.get("variant"),
            formula_version=item.get("formula_version"),
            size=item.get("size"),
            aliases=item.get("aliases", []),
            verification_status=item["verification_status"],
            is_demo=item["is_demo"],
            notes=item.get("notes"),
        )
        db.add(product)
        db.flush()
        key_to_product[item["key"]] = product

    # real products (with nested source payloads)
    for item in real["products"]:
        product = CatalogProduct(
            brand=item["brand"],
            name=item["name"],
            category=item["category"],
            region=item["region"],
            variant=item.get("variant"),
            formula_version=item.get("formula_version"),
            size=item.get("size"),
            aliases=item.get("aliases", []),
            verification_status=item["verification_status"],
            is_demo=item["is_demo"],
            notes=item.get("notes"),
        )
        db.add(product)
        db.flush()
        key_to_product[item["key"]] = product
        src = item["source"]
        source = KnowledgeSource(
            catalog_product_id=product.id,
            source_type=src["source_type"],
            title=src["title"],
            publisher=src.get("publisher"),
            url=src.get("url"),
            file_ref=src.get("file_ref"),
            region=src.get("region", "CN"),
            applies_to_variant=src.get("applies_to_variant"),
            retrieved_at=_dt(src.get("retrieved_at")),
            reviewed_at=_dt(src.get("reviewed_at")),
            status=src["status"],
            content_hash=_content_hash(json.dumps(src["chunks"], ensure_ascii=False)),
            approval_note=src.get("approval_note"),
            is_demo=src.get("is_demo", False),
        )
        db.add(source)
        db.flush()
        _assert_source_allowed(source, settings)
        _add_chunks(db, source, product.id, src["chunks"])

    source_key_to_id: dict[str, str] = {}

    def add_sources(doc: dict[str, Any]) -> None:
        for src in doc["sources"]:
            product = key_to_product.get(src.get("product_key") or "")
            source = KnowledgeSource(
                catalog_product_id=product.id if product else None,
                source_type=src["source_type"],
                title=src["title"],
                publisher=src.get("publisher"),
                url=src.get("url"),
                file_ref=src.get("file_ref"),
                region=src.get("region", "CN"),
                applies_to_variant=src.get("applies_to_variant"),
                retrieved_at=_dt(src.get("retrieved_at")),
                reviewed_at=_dt(src.get("reviewed_at")),
                status=src["status"],
                content_hash=_content_hash(json.dumps(src["chunks"], ensure_ascii=False)),
                approval_note=src.get("approval_note"),
                conflict_group=src.get("conflict_group"),
                is_demo=src.get("is_demo", True),
            )
            db.add(source)
            db.flush()
            _assert_source_allowed(source, settings)
            source_key_to_id[src["key"]] = source.id
            _add_chunks(db, source, product.id if product else None, src["chunks"])

    add_sources(demo_sources)
    add_sources(demo_ingredients)
    add_sources(real)

    # ingredient profiles: demo + real
    ingredient_key_to_id: dict[str, str] = {}
    for entry in demo_ingredients["ingredients"] + real["ingredients"]:
        profile = IngredientProfile(
            inci_name=entry["inci_name"],
            common_name=entry["common_name"],
            known_effects=[
                {"text": e["text"], "source_id": source_key_to_id[e["source_key"]]}
                for e in entry.get("effects", [])
                if e.get("source_key") in source_key_to_id
            ],
            irritant_level=entry.get("irritant_level", "unknown"),
            irritant_notes=[
                {"text": e["text"], "source_id": source_key_to_id[e["source_key"]]}
                for e in entry.get("irritant_notes", [])
                if e.get("source_key") in source_key_to_id
            ],
            life_extensions=[
                {
                    "kind": e["kind"],
                    "text": e["text"],
                    "source_id": source_key_to_id[e["source_key"]],
                    "locator": e.get("locator"),
                }
                for e in entry.get("life_extensions", [])
                if e.get("source_key") in source_key_to_id
            ],
            source_ids=[
                source_key_to_id[k] for k in entry.get("source_keys", []) if k in source_key_to_id
            ],
            approval_status=entry.get("approval_status", "pending"),
            conflict_flag=entry.get("conflict_flag", False),
            conflict_note=entry.get("conflict_note"),
            is_demo=entry.get("is_demo", True),
            categories=entry.get("categories", []),
            typical_period=entry.get("typical_period"),
        )
        db.add(profile)
        db.flush()
        ingredient_key_to_id[entry["key"]] = profile.id

    # cities
    cities_doc = _load(settings, "sources", "cities.json")
    city_ids: dict[str, str] = {}
    for city in cities_doc["cities"]:
        row = City(
            city_id=city["city_id"],
            name_zh=city["name_zh"],
            name_en=city["name_en"],
            country=city["country"],
            timezone=city["timezone"],
            latitude=city["latitude"],
            longitude=city["longitude"],
            forecast_days=city["forecast_days"],
        )
        db.add(row)
        db.flush()
        city_ids[city["city_id"]] = row.id

    # trigger rules
    rules_doc = _load(settings, "sources", "trigger_rules.json")
    for rule in rules_doc["rules"]:
        db.add(
            TriggerRule(
                service_type=rule["service_type"],
                description=rule["description"],
                conditions=rule["conditions"],
                threshold_source=rule["threshold_source"],
                approval_status=rule["approval_status"],
                cooldown_minutes=rule["cooldown_minutes"],
                min_interval_minutes=rule["min_interval_minutes"],
                notes=rule.get("notes"),
            )
        )
    db.flush()
    return {
        "products": key_to_product,
        "sources": source_key_to_id,
        "ingredients": ingredient_key_to_id,
        "cities": city_ids,
    }


def _assert_source_allowed(source: KnowledgeSource, settings: Settings) -> None:
    ok, reason = knowledge.source_url_allowed(source.url, settings.allowed_domain_list)
    if not ok:
        raise ValidationError(
            f"来源《{source.title}》被拒绝：{reason}。请更新 ALLOWED_SOURCE_DOMAINS 或修正来源链接。"
        )


def _add_chunks(
    db: Session, source: KnowledgeSource, product_id: str | None, chunks: list[dict[str, Any]]
) -> None:
    for idx, chunk in enumerate(chunks):
        db.add(
            KnowledgeChunk(
                source_id=source.id,
                catalog_product_id=product_id,
                locator=chunk.get("locator"),
                heading=chunk.get("heading"),
                text=chunk["text"],
                claim_types=chunk.get("claim_types", []),
                structured=chunk.get("structured", {}),
                content_hash=_content_hash(chunk["text"]),
                token_count=len(chunk["text"]),
                is_demo=source.is_demo,
            )
        )
    db.flush()


def seed_users(db: Session) -> dict[str, User]:
    tenant = db.execute(select(Tenant).where(Tenant.name == "BeautyCare 演示租户")).scalar_one_or_none()
    if tenant is None:
        tenant = Tenant(name="BeautyCare 演示租户", kind="demo")
        db.add(tenant)
        db.flush()
    users: dict[str, User] = {}
    for code, spec in PERSONAS.items():
        user = db.execute(select(User).where(User.email == spec["email"])).scalar_one_or_none()
        if user is None:
            user = User(
                tenant_id=tenant.id,
                email=spec["email"],
                display_name=spec["display_name"],
                role=spec["role"],
                timezone="Asia/Shanghai",
                consent_flags={"service_reminders": False, "marketing": False, "brand_sharing": False},
                is_demo=True,
            )
            db.add(user)
            db.flush()
            db.add(
                NotificationPreference(
                    tenant_id=tenant.id,
                    user_id=user.id,
                    service_types=["travel_support"],
                    channels=["in_app"],
                    daily_cap=1,
                    quiet_hours_start="22:00",
                    quiet_hours_end="08:00",
                    timezone=user.timezone,
                    consent_version="consent-v1",
                    marketing_opt_in=False,
                    external_push_enabled=False,
                )
            )
            db.flush()
        users[code] = user
    return users


CABINET_A: list[dict[str, Any]] = [
    {"key": "D01", "opened": -60, "purchase": -70, "lifecycle": "opened"},
    {"key": "D02", "opened": -55, "purchase": -65, "lifecycle": "opened"},
    {"key": "D03", "opened": -40, "purchase": -50, "lifecycle": "opened"},
    {"key": "D04", "opened": -30, "purchase": -45, "lifecycle": "opened"},
    {"key": "D05", "opened": -20, "purchase": -35, "lifecycle": "opened"},
    {"key": "D07", "opened": -25, "purchase": -40, "lifecycle": "opened"},
    {"key": "D09", "opened": -18, "purchase": -30, "lifecycle": "opened"},
    {"key": "D10", "opened": -12, "purchase": -22, "lifecycle": "opened"},
    {"key": "D11", "opened": -10, "purchase": -20, "lifecycle": "opened"},
    {"key": "D12", "opened": None, "purchase": -5, "lifecycle": "unopened"},
]


def seed_consumer_a(db: Session, users: dict[str, User], catalog: dict[str, Any]) -> dict[str, Any]:
    user = users["consumer_a"]
    products: dict[str, OwnedProduct] = {}
    base = clock_now(db)
    for spec in CABINET_A:
        product = catalog["products"][spec["key"]]
        owned = cabinet_service.create_owned(
            db,
            tenant_id=user.tenant_id,
            user_id=user.id,
            custom_name=product.name,
            catalog_product_id=product.id,
            match_status="matched",
            purchase_date=base + timedelta(days=spec["purchase"]) if spec.get("purchase") else None,
            opened_date=base + timedelta(days=spec["opened"]) if spec.get("opened") else None,
            expiry_source="unknown",
            lifecycle_status=spec["lifecycle"],
            usage_status="active",
            provenance="demo_seed",
        )
        products[spec["key"]] = owned

    # preferences seeded as explicit user statements (demo data)
    for key, value in (("routine.budget_monthly", 300.0), ("routine.preferred_period", "both")):
        db.add(
            MemoryRecord(
                tenant_id=user.tenant_id,
                user_id=user.id,
                kind="explicit_preference",
                key=key,
                value={"value": value, "label": key},
                provenance_type="explicit_user_statement",
                source_excerpt="演示种子数据：用户明确表达的偏好",
                valid_from=base,
                status="active",
            )
        )
    db.flush()

    env_service.set_location(
        db, tenant_id=user.tenant_id, user_id=user.id, city_id="CN-GZ", purpose="home", actor=user.id
    )

    draft = routine_service.generate_draft(
        db,
        tenant_id=user.tenant_id,
        user_id=user.id,
        actor=user.id,
        trigger="seed_initial",
    )
    plan = draft.plan
    if plan is not None:
        routine_service.accept_draft(db, plan=plan, expected_version=plan.version, actor=user.id)

    events: list[dict[str, Any]] = [
        {"key": "D01", "text": "用完澄泉温和洁面啫喱感觉挺舒服，不紧绷。", "type": "positive", "days": -26},
        {"key": "D02", "text": "澄泉平衡爽肤水用着不错，拍完吸收很快。", "type": "positive", "days": -24},
        {"key": "D04", "text": "澄泉舒缓精华很舒服，脸部没有不适。", "type": "positive", "days": -22},
        {"key": "D07", "text": "澄泉水润保湿乳挺好用的，保湿够。", "type": "positive", "days": -20},
        {"key": "D09", "text": "修护晚霜用了一周，感觉不错。", "type": "positive", "days": -18},
        {"key": "D11", "text": "点涂凝胶挺润的，局部使用没有不适。", "type": "positive", "days": -16},
        {"key": "D03", "text": "昨晚用了澄泉光感精华后有点刺痛。", "type": "negative", "days": -9, "precision": "day"},
        {"key": "D10", "text": "用了去角质凝胶，脸颊有轻微刺痛。", "type": "negative", "days": -7, "precision": "day"},
        {"key": "D03", "text": "又用了一次光感精华，还是有点刺痛感。", "type": "negative", "days": -5, "precision": "day"},
        {"key": "D05", "text": "焕活精华用了之后有点干，还有轻微刺痛。", "type": "negative", "days": -4, "precision": "day"},
        {"key": "D05", "text": "第二次用焕活精华，脸颊又开始刺痛。", "type": "negative", "days": -3, "precision": "day"},
        {"key": "D05", "text": "焕活精华第三次使用，还是刺痛。", "type": "negative", "days": -2, "precision": "day"},
    ]
    created = []
    for spec in events:
        product = products[spec["key"]]
        event, prompt, _guidance = usage_service.create_event(
            db,
            tenant_id=user.tenant_id,
            user_id=user.id,
            reported_text=spec["text"],
            owned_product_ids=[product.id],
            occurred_at=base + timedelta(days=spec["days"]),
            time_precision=spec.get("precision", "day"),
            event_type=spec["type"],
            actor=user.id,
        )
        created.append({"event_id": event.id, "prompt_id": prompt.id if prompt else None, "type": spec["type"]})

    return {
        "user_id": user.id,
        "products": {k: v.id for k, v in products.items()},
        "plan_id": plan.id if plan else None,
        "plan_version": plan.version if plan else None,
        "events": created,
    }


def seed_consumer_b(db: Session, users: dict[str, User], catalog: dict[str, Any]) -> dict[str, Any]:
    user = users["consumer_b"]
    base = clock_now(db)
    product = catalog["products"]["D07"]
    owned = cabinet_service.create_owned(
        db,
        tenant_id=user.tenant_id,
        user_id=user.id,
        custom_name=product.name,
        catalog_product_id=product.id,
        match_status="matched",
        purchase_date=base - timedelta(days=12),
        opened_date=base - timedelta(days=10),
        lifecycle_status="opened",
        usage_status="active",
        provenance="demo_seed",
    )
    env_service.set_location(
        db, tenant_id=user.tenant_id, user_id=user.id, city_id="CN-SH", purpose="home", actor=user.id
    )
    draft = routine_service.generate_draft(
        db, tenant_id=user.tenant_id, user_id=user.id, actor=user.id, trigger="seed_initial"
    )
    if draft.plan is not None:
        routine_service.accept_draft(db, plan=draft.plan, expected_version=draft.plan.version, actor=user.id)
    event, _prompt, _guidance = usage_service.create_event(
        db,
        tenant_id=user.tenant_id,
        user_id=user.id,
        reported_text="用了水润保湿乳之后有一点闷。",
        owned_product_ids=[owned.id],
        occurred_at=base - timedelta(days=3),
        time_precision="day",
        event_type="negative",
        actor=user.id,
    )
    return {"user_id": user.id, "products": {"D07": owned.id}, "events": [event.id]}


def seed_all(db: Session, settings: Settings, *, include_consumers: bool = True) -> dict[str, Any]:
    if is_seeded(db):
        raise ValidationError("数据库已包含演示数据，请先重置（scripts/reset_db.sh）")
    catalog = seed_catalog(db, settings)
    users = seed_users(db)
    result: dict[str, Any] = {
        "tenant_id": users["consumer_a"].tenant_id,
        "personas": {code: {"user_id": u.id, "email": u.email, "role": u.role} for code, u in users.items()},
        "catalog": {k: v.id for k, v in catalog["products"].items()},
    }
    if include_consumers:
        result["consumer_a"] = seed_consumer_a(db, users, catalog)
        result["consumer_b"] = seed_consumer_b(db, users, catalog)
    db.flush()
    return result
