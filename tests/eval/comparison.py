"""Three-setting comparison required by spec §14 and §25.3.

The project ships exactly one orchestration (``agent/orchestrator.py`` +
``agent/mock_brain.py``).  A faithful A/B/C *cannot* be built by swapping in
different products, so it is built here honestly as three real, switchable
configurations of the **same** orchestrator, toggled at the documented model
provider factory (``app.agent.orchestrator.get_model_provider``):

* A — 仅当前消息 + 知识检索：planner 只允许知识检索工具；不提供结构化状态/
  事件记忆，也没有任何服务工具（因此不会生成计划、工单或记忆写入）。
* B — 聊天历史 + 知识检索：在 A 的基础上把最近对话拼进检索 query（mock 大脑
  本身是无状态的，所以“历史”只能通过检索输入体现；这一点在报告中明确标注为
  近似实现）。
* C — 结构化状态/事件记忆 + 检索 + 服务工具：项目实际交付的编排（不做任何
  变换）。

All three keep the same model (deterministic mock), catalog, scenarios and
turn budget.  Metrics are aggregated with the same rules for every setting.

§25.3 additionally compares three atlas settings built from real DB fixtures:

* A：无反馈积累，仅产品资料；
* B：有反馈积累，但没有可用的成分来源；
* C：反馈 + 成分来源 + 图鉴（交付配置）。
"""

from __future__ import annotations

import copy
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

_EVAL_DIR = Path(__file__).resolve().parent
_ROOT = _EVAL_DIR.parents[1]
for _p in (str(_EVAL_DIR), str(_ROOT), str(_ROOT / "backend")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from harness import API, CheckResult, Scenario, ScenarioContext  # noqa: E402
from measure import (  # noqa: E402
    record_atlas_observations,
    record_combination_observations,
    record_feedback_trigger,
    record_step_observations,
)

KNOWLEDGE_TOOLS = {"search_knowledge", "get_ingredient_profile"}
STATE_TOOLS = {
    "get_user_context",
    "list_owned_products",
    "get_active_routine",
    "extract_ingredients",
    "get_product_sources",
    "search_catalog",
    "build_ingredient_atlas",
}
SERVICE_TOOLS = {
    "get_service_status",
    "get_environment",
    "get_user_activities",
    "get_notification_status",
}


@dataclass(frozen=True)
class SettingSpec:
    key: str
    label_zh: str
    description_zh: str
    use_knowledge_retrieval: bool
    use_history: bool
    use_structured_state: bool
    use_service_tools: bool

    @property
    def allowed_tools(self) -> set[str]:
        allowed: set[str] = set()
        if self.use_knowledge_retrieval:
            allowed |= KNOWLEDGE_TOOLS
        if self.use_structured_state:
            allowed |= STATE_TOOLS
        if self.use_service_tools:
            allowed |= SERVICE_TOOLS
        return allowed


SETTING_A = SettingSpec(
    "A",
    "A：仅当前消息 + 知识检索",
    "planner 只能请求知识检索；无结构化状态/事件记忆，无服务工具，因此不会产生计划、工单或记忆写入。",
    use_knowledge_retrieval=True,
    use_history=False,
    use_structured_state=False,
    use_service_tools=False,
)
SETTING_B = SettingSpec(
    "B",
    "B：聊天历史 + 知识检索",
    "在 A 的基础上把最近对话拼入检索 query。mock 大脑不消费历史，故此为对“历史+检索”的可切换近似实现。",
    use_knowledge_retrieval=True,
    use_history=True,
    use_structured_state=False,
    use_service_tools=False,
)
SETTING_C = SettingSpec(
    "C",
    "C：结构化状态/事件记忆 + 检索 + 服务工具（交付配置）",
    "项目实际交付的编排；不做任何工具或写入变换。",
    use_knowledge_retrieval=True,
    use_history=True,
    use_structured_state=True,
    use_service_tools=True,
)

SETTINGS = (SETTING_A, SETTING_B, SETTING_C)


def _history_text(payload: dict[str, Any]) -> str:
    conversation = payload.get("conversation") or []
    parts: list[str] = []
    for item in conversation[-6:]:
        content = str(item.get("content") or "")
        if content:
            parts.append(content[:200])
    return " ".join(parts)


class ConfiguredMockProvider:
    """Wraps the mock brain and applies one setting's input/tool policy."""

    mode = "mock"
    provider = "mock"
    available = True

    def __init__(self, spec: SettingSpec, base: Any | None = None) -> None:
        from app.providers.model import MockModelProvider

        self.spec = spec
        self.base = base or MockModelProvider()
        self.name = f"mock-deterministic-v1+setting-{spec.key}"

    def complete_json(self, *, system_prompt, user_payload, schema_name, schema, images=None):
        payload = copy.deepcopy(user_payload)
        if not self.spec.use_history:
            payload.pop("conversation", None)
        if schema_name == "PlannerOutput":
            base_payload = dict(payload)
            if not self.spec.use_structured_state:
                base_payload["context"] = {}
            response = self.base.complete_json(
                system_prompt=system_prompt,
                user_payload=base_payload,
                schema_name=schema_name,
                schema=schema,
                images=images,
            )
            data = dict(response.payload)
            data["tool_requests"] = [
                request
                for request in (data.get("tool_requests") or [])
                if request.get("name") in self.spec.allowed_tools
            ]
            if self.spec.use_knowledge_retrieval and not any(
                request.get("name") == "search_knowledge" for request in data["tool_requests"]
            ):
                query = str(payload.get("message") or "")
                if self.spec.use_history:
                    query = (_history_text(payload) + " " + query).strip()
                data["tool_requests"].append(
                    {"name": "search_knowledge", "args": {"query": query, "limit": 5}}
                )
            if not self.spec.use_service_tools:
                data["write_requests"] = []
            response.payload = data
            return response
        return self.base.complete_json(
            system_prompt=system_prompt,
            user_payload=payload,
            schema_name=schema_name,
            schema=schema,
            images=images,
        )


def provider_for(spec: SettingSpec) -> Callable[[Any], Any]:
    def factory(settings: Any = None) -> ConfiguredMockProvider:
        return ConfiguredMockProvider(spec)

    return factory


# --- §25.3 atlas settings built from real DB fixtures ----------------------


def no_feedback_accumulated(db: Any, settings: Any) -> None:
    """Atlas setting A: remove accumulated feedback, keep product knowledge."""
    from sqlalchemy import delete

    from app.models import (
        IngredientAtlasView,
        IngredientFeedback,
        ReviewPrompt,
        UsageEvent,
        UserIngredientSignal,
    )

    for model in (UsageEvent, UserIngredientSignal, IngredientFeedback, ReviewPrompt, IngredientAtlasView):
        db.execute(delete(model))
    db.flush()


def no_ingredient_sources(db: Any, settings: Any) -> None:
    """Atlas setting B: keep feedback, revoke ingredient-level sources."""
    from sqlalchemy import select

    from app.models import IngredientProfile, KnowledgeSource

    source_ids: set[str] = set()
    for profile in db.execute(select(IngredientProfile)).scalars():
        source_ids.update(profile.source_ids or [])
        for entry in profile.known_effects or []:
            if entry.get("source_id"):
                source_ids.add(entry["source_id"])
        for entry in profile.irritant_notes or []:
            if entry.get("source_id"):
                source_ids.add(entry["source_id"])
        for entry in profile.life_extensions or []:
            if entry.get("source_id"):
                source_ids.add(entry["source_id"])
    for source_id in source_ids:
        source = db.get(KnowledgeSource, source_id)
        if source is not None:
            source.status = "revoked"
    db.flush()


@dataclass(frozen=True)
class AtlasSetting:
    key: str
    label_zh: str
    configure: Callable[[Any, Any], None] | None


ATLAS_SETTINGS = (
    AtlasSetting("A", "A：无反馈积累，仅产品资料", no_feedback_accumulated),
    AtlasSetting("B", "B：有反馈积累，无成分来源", no_ingredient_sources),
    AtlasSetting("C", "C：反馈 + 成分来源 + 图鉴（交付配置）", None),
)


def atlas_probe_scenario(setting: AtlasSetting) -> Scenario:
    """A fixed probe measuring the six §25.3 atlas metrics for one setting."""

    def verify(ctx: ScenarioContext) -> CheckResult:
        notes: list[str] = []
        ctx.evidence["combinations"] = ctx.get(f"{API}/combinations").json()
        plan = ctx.draft(f"atlas-abc-{setting.key}")
        ctx.evidence["plan"] = plan
        payload = ctx.atlas()
        ctx.evidence["payload"] = payload
        record_combination_observations(ctx, plan)
        record_combination_observations(
            ctx, {"combination_notes": ctx.evidence["combinations"]["combination_notes"]}
        )
        record_step_observations(ctx, plan)
        record_atlas_observations(ctx, payload)
        # feedback -> plan review trigger, measured identically in all settings
        product = ctx.cabinet_named("澄泉焕活精华")
        body = ctx.usage_event(
            f"设置 {setting.key} 探针：焕活精华使用后刺痛", [product["id"]], time_precision="unknown"
        )
        triggered = body.get("review_prompt") is not None
        record_feedback_trigger(
            ctx,
            should_trigger=True,
            triggered=triggered,
            event_id=body["event"]["id"],
            note=f"§25.3 探针（设置 {setting.key}）",
        )
        notes.append(
            f"图鉴设置 {setting.key}：卡片={len(payload.get('cards') or [])} "
            f"样本不足={len(payload.get('below_threshold') or [])} "
            f"待审核={len(payload.get('pending') or [])} "
            f"被丢弃延伸={len(payload.get('dropped_life_extensions') or [])}"
        )
        return CheckResult(True, "；".join(notes))

    return Scenario(
        id=f"ATLAS-{setting.key}",
        group="atlas_abc",
        title=f"§25.3 图鉴三设置探针 — {setting.label_zh}",
        turns=[],
        verify=verify,
        persona="consumer_a",
        spec_ref="规格 §25.3",
    )
