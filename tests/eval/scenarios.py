"""48 multi-turn evaluation scenarios (spec §14).

Groups and counts are fixed by the spec:

* import             8   EV01–EV08
* routine           10   EV09–EV18
* memory             8   EV19–EV26
* feedback+handoff  10   EV27–EV36
* out-of-scope      4    EV37–EV40
* ingredient atlas   8   EV41–EV48

Each scenario declares 1–4 first-person Chinese user turns plus a
machine-checkable ``verify`` function.  Verification asserts observable
behaviour only: HTTP status codes, intents, cards, wording rules, and database
state read through the real session factory.  The model's own opinion of itself
is never used as evidence.

``tests/ac`` already encodes the acceptance criteria; these scenarios are
independent multi-turn conversations, not copies.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_EVAL_DIR = Path(__file__).resolve().parent
_ROOT = _EVAL_DIR.parents[1]
for _p in (str(_EVAL_DIR), str(_ROOT), str(_ROOT / "backend")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from harness import (  # noqa: E402
    API,
    CheckResult,
    M_FORGOTTEN_REAPPEAR,
    M_UNCONFIRMED_CHANGE,
    Scenario,
    ScenarioContext,
    citation_rows,
    new_idempotency_key,
    require,
    source_backed,
)
from measure import (  # noqa: E402
    record_atlas_observations,
    record_questions,
    record_combination_observations,
    record_feedback_trigger,
    record_forgotten,
    record_memory_field,
    record_question,
    record_step_observations,
    record_ticket,
)

# --- small check helper ---------------------------------------------------


class Check:
    def __init__(self, ctx: ScenarioContext) -> None:
        self.ctx = ctx
        self.problems: list[str] = []

    def expect(self, condition: Any, message: str) -> bool:
        if not condition:
            self.problems.append(message)
        return bool(condition)

    def eq(self, got: Any, want: Any, message: str) -> bool:
        return self.expect(got == want, f"{message}（实际 {got!r}，期望 {want!r}）")

    def contains(self, haystack: Any, needle: str, message: str) -> bool:
        return self.expect(needle in str(haystack), f"{message}（未找到 {needle!r}）")

    def result(self, ok_detail: str = "全部断言通过") -> CheckResult:
        return CheckResult(not self.problems, "；".join(self.problems) if self.problems else ok_detail)


def _routine_draft_card(turn) -> dict[str, Any] | None:
    for card in turn.cards:
        if card.get("type") == "routine_draft":
            return card
    return None


def _accept_plan(ctx: ScenarioContext, plan_id: str, version: int, *, key_prefix: str = "accept"):
    response = ctx.post(f"{API}/routines/{plan_id}/accept", json={"expected_version": version})
    require(response.status_code == 200, f"accept 失败：{response.status_code} {response.text}")
    return response


def _upload(ctx: ScenarioContext, fixture: str):
    data = ctx.session.upload_bytes(fixture)
    return ctx.post(
        f"{API}/imports",
        files={"file": (fixture, data, "image/png")},
    )


def _confirm(ctx: ScenarioContext, batch: dict[str, Any], items: list[dict[str, Any]], *, idem: str | None = None):
    headers = {"Idempotency-Key": idem} if idem else None
    return ctx.post(f"{API}/imports/{batch['id']}/confirm", json={"items": items}, headers=headers)


def _known_question_keys(ctx: ScenarioContext) -> set[str]:
    known: set[str] = set()
    for record in ctx.memories():
        if record["status"] == "active":
            known.add(record["key"])
    return known


def _plan_citations(plan: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for step in plan.get("steps") or []:
        out.extend(step.get("citation_ids") or [])
    return out


# =====================================================================
# import group — EV01 … EV08
# =====================================================================


def ev01_setup(ctx: ScenarioContext) -> None:
    ctx.evidence["before"] = len(ctx.owned_products())
    response = _upload(ctx, "demo_order_screenshot_1.png")
    require(response.status_code == 201, f"上传失败：{response.text}")
    ctx.evidence["batch"] = response.json()


def ev01_between0(ctx: ScenarioContext) -> None:
    """Snapshot the cabinet right before the user's explicit confirmation turn."""
    ctx.evidence["before_confirm"] = len(ctx.owned_products())


def ev01_between1(ctx: ScenarioContext) -> None:
    batch = ctx.evidence["batch"]
    items = [
        {
            "raw_name": candidate["raw_name"],
            "custom_name": candidate["raw_name"] + "（我的备注）" if index == 1 else candidate["raw_name"],
            "quantity": 1,
            "catalog_product_id": candidate["catalog_product_id"],
            "match_status": "matched",
        }
        for index, candidate in enumerate(batch["candidates"])
    ]
    response = _confirm(ctx, batch, items)
    require(response.status_code == 200, f"确认失败：{response.text}")
    ctx.evidence["confirm"] = response.json()


def ev01_verify(ctx: ScenarioContext) -> CheckResult:
    check = Check(ctx)
    batch = ctx.evidence["batch"]
    check.eq(batch["status"], "ready", "批次状态应为 ready")
    check.eq(len(batch["candidates"]), 2, "应识别出两件候选")
    check.eq(batch["provider_mode"], "mock", "mock 模式必须显式标注")
    check.eq(ctx.evidence["before_confirm"], ctx.evidence["before"], "确认前不得写入美妆柜")
    created = ctx.evidence["confirm"]["created"]
    check.eq(len(created), 2, "确认后应精确创建两件实例")
    check.eq(len(ctx.owned_products()), ctx.evidence["before"] + 2, "美妆柜实例数应增加两件")
    check.contains([p["custom_name"] for p in created], "（我的备注）", "用户的名称修正应保留")
    return check.result("两件商品在确认前零写入、确认后精确入柜")


def ev02_setup(ctx: ScenarioContext) -> None:
    ctx.evidence["before"] = len(ctx.owned_products())
    response = _upload(ctx, "demo_order_screenshot_1.png")
    require(response.status_code == 201, response.text)
    ctx.evidence["first"] = response.json()


def ev02_between0(ctx: ScenarioContext) -> None:
    response = _upload(ctx, "demo_order_screenshot_1.png")
    require(response.status_code == 201, response.text)
    ctx.evidence["second"] = response.json()


def ev02_between1(ctx: ScenarioContext) -> None:
    batch = ctx.evidence["first"]
    items = [
        {"raw_name": c["raw_name"], "quantity": 1, "catalog_product_id": c["catalog_product_id"]}
        for c in batch["candidates"]
    ]
    first = _confirm(ctx, batch, items)
    require(first.status_code == 200, first.text)
    key = new_idempotency_key("confirm-retry")
    retry = _confirm(ctx, batch, items, idem=key)
    require(retry.status_code == 200, retry.text)
    ctx.evidence["after_first"] = len(ctx.owned_products())
    ctx.evidence["retry"] = retry.json()


def ev02_verify(ctx: ScenarioContext) -> CheckResult:
    check = Check(ctx)
    first, second = ctx.evidence["first"], ctx.evidence["second"]
    check.eq(second["id"], first["id"], "同一文件的第二次上传应复用同一批次")
    check.eq(second.get("duplicate_upload"), True, "重复上传必须标记为重复")
    check.eq(ctx.evidence["after_first"], ctx.evidence["before"] + 2, "确认应新增两件")
    check.eq(ctx.evidence["retry"].get("duplicate"), True, "重复确认必须返回 duplicate")
    check.eq(len(ctx.owned_products()), ctx.evidence["before"] + 2, "重复确认不得新增实例")
    return check.result("重复上传与重复确认都不重复入柜")


def ev03_setup(ctx: ScenarioContext) -> None:
    search = ctx.get(f"{API}/catalog/search", params={"q": "澄泉光感精华"})
    require(search.status_code == 200, search.text)
    candidates = search.json()["candidates"]
    ctx.evidence["candidate_ids"] = [c["catalog_product_id"] for c in candidates]
    v1 = ctx.catalog_id("DEMO-SR-03-v1")
    v2 = ctx.catalog_id("DEMO-SR-03-v2")
    ctx.evidence["v1"], ctx.evidence["v2"] = v1, v2
    product = ctx.add_owned("澄泉光感精华 v1（旧配方）", catalog_product_id=v1, match_status="matched")
    detail = ctx.get(f"{API}/owned-products/{product['id']}").json()
    ctx.evidence["detail"] = detail


def ev03_verify(ctx: ScenarioContext) -> CheckResult:
    check = Check(ctx)
    ids = set(ctx.evidence["candidate_ids"])
    check.expect(len(ids) >= 2, "同名不同版本应同时作为候选，不自动合并")
    check.expect(ctx.evidence["v1"] in ids and ctx.evidence["v2"] in ids, "两个版本都应出现在候选里")
    detail = ctx.evidence["detail"]
    check.eq(detail["catalog_product_id"], ctx.evidence["v1"], "入柜实例只能引用确认的版本")
    source_products = {c["product_id"] for c in detail["sources"]}
    check.eq(source_products, {ctx.evidence["v1"]}, "引用资料必须全部属于确认的版本")
    check.expect(
        all(
            "v1" in ((c.get("locator") or "") + (c["title"] or ""))
            for c in detail["sources"]
        ),
        "来源定位应指向 v1 版本",
    )
    for turn in ctx.outputs:
        check.expect("v2" not in turn.answer or "不会" in turn.answer or "候选" in turn.answer,
                     "对话不得把 v2 资料当作已确认版本")
    return check.result("同名不同版本保持候选状态，引用只指向确认版本")


def ev04_between1(ctx: ScenarioContext) -> None:
    product = ctx.add_owned("朋友送的手工面霜", match_status="custom")
    ctx.evidence["product"] = product
    plan = ctx.draft("eval-ev04")
    ctx.evidence["plan"] = plan


def ev04_verify(ctx: ScenarioContext) -> CheckResult:
    check = Check(ctx)
    product = ctx.evidence["product"]
    plan = ctx.evidence["plan"]
    pending = {p["owned_product_id"]: p for p in plan.get("pending_products") or []}
    check.expect(product["id"] in pending, "目录未匹配的产品必须进入待确认列表")
    if product["id"] in pending:
        check.eq(pending[product["id"]]["reason"], "SOURCE_MISSING", "未匹配产品的原因是资料缺失")
        check.contains(pending[product["id"]].get("message", ""), "资料", "待确认说明应解释缺少资料")
    check.expect(
        all(step["owned_product_id"] != product["id"] for step in plan["steps"]),
        "资料缺失的产品不得生成步骤",
    )
    check.expect(
        all(product["id"] not in (note.get("owned_product_ids") or []) for note in plan.get("combination_notes") or []),
        "资料缺失的产品不得参与组合推理",
    )
    for turn in ctx.outputs:
        check.eq(turn.status_code, 200, "对话应正常返回")
        for forbidden in ("已自动加入美妆柜", "已为你安排"):
            check.expect(forbidden not in turn.answer, f"对话不得声称「{forbidden}」")
    return check.result("手动添加的未匹配产品进入待确认，不参与计划与组合推理")


def ev05_setup(ctx: ScenarioContext) -> None:
    ctx.evidence["before"] = len(ctx.owned_products())
    data = ctx.session.make_png("NOT-A-DEMO-FIXTURE")
    response = ctx.post(f"{API}/imports", files={"file": ("my_photo.png", data, "image/png")})
    require(response.status_code == 201, response.text)
    ctx.evidence["batch"] = response.json()


def ev05_verify(ctx: ScenarioContext) -> CheckResult:
    check = Check(ctx)
    batch = ctx.evidence["batch"]
    check.expect(batch["candidates"] == [], "mock 模式不得声称识别任意图片")
    check.contains(str(batch.get("notes") or batch), "mock", "应明示 mock 不识别任意图片")
    check.eq(len(ctx.owned_products()), ctx.evidence["before"], "未确认不得写入美妆柜")
    for turn in ctx.outputs:
        check.expect(turn.status_code == 200, "对话应正常返回而不是报错")
    with ctx.db() as session:
        from sqlalchemy import select

        from app.models import OwnedProduct

        total = len([p for p in session.execute(select(OwnedProduct)).scalars() if p.custom_name == "my_photo.png"])
        check.eq(total, 0, "不得用文件名伪造产品")
    return check.result("任意图片在 mock 模式下不识别、不写入")


def ev06_setup(ctx: ScenarioContext) -> None:
    ctx.evidence["before"] = len(ctx.owned_products())
    with ctx.db() as session:
        from sqlalchemy import func, select

        from app.models import OwnedProduct

        ctx.evidence["global_before"] = int(
            session.execute(select(func.count()).select_from(OwnedProduct)).scalar_one()
        )
    response = _upload(ctx, "demo_order_screenshot_2.png")
    require(response.status_code == 201, response.text)
    ctx.evidence["batch"] = response.json()


def ev06_verify(ctx: ScenarioContext) -> CheckResult:
    check = Check(ctx)
    check.expect(ctx.evidence["batch"]["candidates"], "演示截图应能识别候选")
    check.eq(len(ctx.owned_products()), ctx.evidence["before"], "未确认前数据库不得新增用户产品")
    with ctx.db() as session:
        from sqlalchemy import func, select

        from app.models import OwnedProduct

        after = session.execute(select(func.count()).select_from(OwnedProduct)).scalar_one()
        check.eq(int(after), ctx.evidence["global_before"], "全局实例数不得变化（含他人数据）")
    check.eq(ctx.evidence["batch"]["status"], "ready", "批次仍处于待确认状态")
    return check.result("确认前数据库没有任何新增")


def ev07_setup(ctx: ScenarioContext) -> None:
    response = _upload(ctx, "demo_order_screenshot_1.png")
    require(response.status_code == 201, response.text)
    batch = response.json()
    items = [
        {"raw_name": c["raw_name"], "quantity": 1, "catalog_product_id": c["catalog_product_id"]}
        for c in batch["candidates"]
    ]
    confirm = _confirm(ctx, batch, items)
    require(confirm.status_code == 200, confirm.text)
    ctx.evidence["created"] = [p["id"] for p in confirm.json()["created"]]
    ctx.evidence["active_before"] = ctx.active_plan()["version"]


def ev07_after(ctx: ScenarioContext) -> None:
    plan = ctx.draft("eval-ev07")
    ctx.evidence["plan"] = plan
    ctx.evidence["active_after"] = ctx.active_plan()["version"]


def ev07_verify(ctx: ScenarioContext) -> CheckResult:
    check = Check(ctx)
    plan = ctx.evidence["plan"]
    step_products = {step["owned_product_id"] for step in plan["steps"]}
    check.expect(step_products, "应为新导入的产品生成步骤")
    check.expect(bool(step_products & set(ctx.evidence["created"])), "新导入的产品应进入计划")
    check.eq(plan["status"], "draft", "草稿在接受前不生效")
    check.eq(ctx.evidence["active_after"], ctx.evidence["active_before"], "接受前当前版本不变")
    record_step_observations(ctx, plan)
    return check.result("新产品加入后生成草稿，未接受前当前版本不变")


def ev08_setup(ctx: ScenarioContext) -> None:
    response = _upload(ctx, "demo_order_screenshot_2.png")
    require(response.status_code == 201, response.text)
    ctx.evidence["batch"] = response.json()
    ctx.evidence["before"] = len(ctx.owned_products())


def ev08_after(ctx: ScenarioContext) -> None:
    batch = ctx.evidence["batch"]
    c0, c1 = batch["candidates"][0], batch["candidates"][1]
    items = [
        {"raw_name": c0["raw_name"], "quantity": 2, "catalog_product_id": c0["catalog_product_id"]},
        {"raw_name": c1["raw_name"], "quantity": 1, "catalog_product_id": c1["catalog_product_id"]},
    ]
    key = new_idempotency_key("ev08")
    first = _confirm(ctx, batch, items, idem=key)
    require(first.status_code == 200, first.text)
    ctx.evidence["created"] = first.json()["created"]
    ctx.evidence["after_first"] = len(ctx.owned_products())
    retry = _confirm(ctx, batch, items, idem=key)
    ctx.evidence["retry"] = retry
    bad = _confirm(
        ctx,
        batch,
        [{"raw_name": c0["raw_name"], "quantity": 0, "catalog_product_id": c0["catalog_product_id"]}],
    )
    ctx.evidence["bad"] = bad
    ctx.evidence["after_bad"] = len(ctx.owned_products())


def ev08_verify(ctx: ScenarioContext) -> CheckResult:
    check = Check(ctx)
    check.eq(len(ctx.evidence["created"]), 3, "数量 2 + 1 应创建三件实例")
    check.eq(ctx.evidence["retry"].status_code, 200, "幂等重试应返回 200")
    check.eq(ctx.evidence["after_first"], ctx.evidence["after_bad"], "非法数量请求不得写入")
    check.eq(ctx.evidence["bad"].status_code, 422, "数量 0 应被拒绝（422）")
    check.eq(len(ctx.owned_products()), ctx.evidence["before"] + 3, "实例总数只应增加三件")
    return check.result("数量校验与幂等重试都按预期工作")


# =====================================================================
# routine group — EV09 … EV18
# =====================================================================


def ev09_setup(ctx: ScenarioContext) -> None:
    ctx.evidence["active_before"] = ctx.active_plan()


def ev09_between1(ctx: ScenarioContext) -> None:
    card = _routine_draft_card(ctx.outputs[0])
    require(card is not None, "第一轮对话没有生成计划草稿卡片")
    ctx.evidence["draft_card"] = card
    ctx.evidence["active_before_accept"] = ctx.active_plan()["version"]
    response = _accept_plan(ctx, card["entity_id"], card["version"])
    ctx.evidence["accepted"] = response.json()["plan"]


def ev09_verify(ctx: ScenarioContext) -> CheckResult:
    check = Check(ctx)
    card = ctx.evidence["draft_card"]
    check.eq(card["type"], "routine_draft", "第一轮应返回草稿卡片")
    check.eq(card["status"], "draft", "卡片状态应为草稿")
    check.eq(ctx.evidence["active_before_accept"], ctx.evidence["active_before"]["version"],
             "接受前当前版本不变")
    record_questions(ctx, ctx.outputs[0].questions, known_keys=set(), where="EV09 首轮")
    routines = ctx.routines()
    check.eq(routines["active"]["id"], card["entity_id"], "接受后草稿成为当前版本")
    history = {p["id"]: p["status"] for p in routines["history"]}
    check.eq(history[ctx.evidence["active_before"]["id"]], "superseded", "旧版本应进入历史")
    return check.result("草稿生成→显式接受→版本切换正确")


def ev10_verify(ctx: ScenarioContext) -> CheckResult:
    check = Check(ctx)
    draft_card = _routine_draft_card(ctx.outputs[0])
    check.expect(draft_card is not None, "第一轮应生成草稿")
    if draft_card:
        check.expect(draft_card["step_count"] <= 3, "三步偏好应立即生效于草稿")
    changes = {(m["key"], m["value"]) for m in ctx.outputs[0].memory_changes}
    check.expect(("routine.max_steps", 3) in changes, "三轮偏好应写入记忆 proposal")
    record_memory_field(ctx, "routine.max_steps", 3)
    records = [m for m in ctx.memories() if m["key"] == "routine.max_steps" and m["status"] == "active"]
    check.eq(len(records), 1, "同一偏好只应有一条 active 记录")
    # no repeated question about an answered field
    asked_second = {q["key"] for q in ctx.outputs[1].questions}
    record_questions(
        ctx, ctx.outputs[0].questions, known_keys=set(), where="EV10 首轮（偏好尚未确认）"
    )
    record_questions(
        ctx, ctx.outputs[1].questions, known_keys={"routine.max_steps"}, where="EV10 第二轮（偏好已确认）"
    )
    check.expect("routine.max_steps" not in asked_second, "已确认的步骤上限不得再次追问")
    return check.result("显式三步偏好被保存、立即生效且不再追问")


def ev11_setup(ctx: ScenarioContext) -> None:
    from app.services.clock import now as clock_now

    with ctx.db() as session:
        from sqlalchemy import select

        from app.models import MemoryRecord, User

        user = session.execute(select(User).where(User.email == "demo_user_a@example.invalid")).scalar_one()
        session.add(
            MemoryRecord(
                tenant_id=user.tenant_id,
                user_id=user.id,
                kind="explicit_preference",
                key="routine.max_steps",
                value={"value": 3, "label": "routine.max_steps"},
                provenance_type="explicit_user_statement",
                source_excerpt="评测夹具：用户此前已明确确认三步上限",
                valid_from=clock_now(session),
                status="active",
            )
        )
        session.flush()
        session.commit()
    ctx.evidence["before"] = ctx.active_plan()["version"]


def ev11_after(ctx: ScenarioContext) -> None:
    response = ctx.draft_response("eval-ev11")
    ctx.evidence["plan"] = response["plan"]
    ctx.evidence["draft_questions"] = response["questions"]


def ev11_verify(ctx: ScenarioContext) -> CheckResult:
    check = Check(ctx)
    plan = ctx.evidence["plan"]
    check.expect(len(plan["steps"]) <= 3, "已知的三步偏好应被复用")
    check.expect("routine.max_steps" not in {q["key"] for q in plan.get("questions") or []},
                 "不得重复追问已确认的步骤上限")
    record_questions(
        ctx,
        ctx.evidence.get("draft_questions") or [],
        known_keys={"routine.max_steps"},
        where="EV11 /routines/drafts（三步已确认）",
    )
    seen_keys: set[str] = set()
    for turn in ctx.outputs:
        for question in turn.questions:
            record_question(ctx, question["key"], already_known=question["key"] in seen_keys,
                            where=f"{ctx.case_id} 轮次")
            seen_keys.add(question["key"])
    for question in plan.get("questions") or []:
        record_question(ctx, question["key"], already_known=True, where="/routines/drafts")
    record_memory_field(ctx, "routine.max_steps", 3)
    return check.result("已知偏好被复用，未重复追问（重复追问率观测见指标表）")


def ev12_verify(ctx: ScenarioContext) -> CheckResult:
    check = Check(ctx)
    changes = {(m["key"], m["value"]) for m in ctx.outputs[0].memory_changes}
    check.expect(("routine.budget_monthly", 500.0) in changes, "预算更新应写入记忆")
    record_memory_field(ctx, "routine.budget_monthly", 500.0)
    records = [m for m in ctx.memories() if m["key"] == "routine.budget_monthly"]
    active = [m for m in records if m["status"] == "active"]
    history = [m for m in records if m["status"] == "superseded"]
    check.eq(len(active), 1, "只能有一条 active 预算")
    check.eq(active[0]["value"], 500.0, "active 预算应为最新值")
    check.expect(any(m["value"] == 300.0 for m in history), "旧预算只应出现在历史里")
    for turn in ctx.outputs[1:]:
        check.expect("500" in turn.answer or "预算" in turn.answer, "后续轮次应反映新预算")
    return check.result("预算更新后新值生效、旧值仅存在于历史")


def ev13_setup(ctx: ScenarioContext) -> None:
    ctx.evidence["active_before"] = ctx.active_plan()["version"]


def ev13_after(ctx: ScenarioContext) -> None:
    response = ctx.draft_response("eval-ev13-not-accepted")
    ctx.evidence["plan"] = response["plan"]
    ctx.evidence["draft_questions"] = response["questions"]
    ctx.evidence["routines"] = ctx.routines()


def ev13_verify(ctx: ScenarioContext) -> CheckResult:
    check = Check(ctx)
    plan = ctx.evidence["plan"]
    check.eq(plan["status"], "draft", "草稿状态")
    check.eq(ctx.evidence["routines"]["active"]["version"], ctx.evidence["active_before"],
             "未接受的草稿不得改变当前版本")
    check.expect(ctx.evidence["routines"]["active"]["id"] != plan["id"], "active 与草稿是不同计划")
    drafts = [p for p in ctx.evidence["routines"]["history"] if p["status"] == "draft"]
    check.expect(drafts, "草稿应出现在历史列表中（未生效）")
    record_step_observations(ctx, plan)
    record_questions(
        ctx, ctx.evidence.get("draft_questions") or [],
        known_keys=set(), where="EV13 /routines/drafts",
    )
    for turn in ctx.outputs:
        check.expect("已生效" not in turn.answer, "对话不得声称草稿已生效")
    return check.result("未接受的 v2 不影响 v1 生效")


def ev14_setup(ctx: ScenarioContext) -> None:
    first = ctx.draft("eval-ev14-a")
    second = ctx.draft("eval-ev14-b")
    ctx.evidence["first"], ctx.evidence["second"] = first, second
    ok = ctx.post(f"{API}/routines/{first['id']}/accept", json={"expected_version": first["version"]})
    stale = ctx.post(f"{API}/routines/{second['id']}/accept", json={"expected_version": second["version"] - 1})
    second_ok = ctx.post(f"{API}/routines/{second['id']}/accept", json={"expected_version": second["version"]})
    replay = ctx.post(f"{API}/routines/{first['id']}/accept", json={"expected_version": first["version"]})
    ctx.evidence["responses"] = {
        "first": ok.status_code,
        "stale": stale.status_code,
        "stale_code": stale.json().get("code") if stale.status_code == 409 else None,
        "second": second_ok.status_code,
        "replay": replay.status_code,
    }
    ctx.evidence["routines"] = ctx.routines()


def ev14_verify(ctx: ScenarioContext) -> CheckResult:
    check = Check(ctx)
    responses = ctx.evidence["responses"]
    check.eq(responses["first"], 200, "接受第一份草稿应成功")
    check.eq(responses["stale"], 409, "过期的接受请求应返回 409")
    check.eq(responses["stale_code"], "VERSION_CONFLICT", "409 应带 VERSION_CONFLICT")
    check.eq(responses["second"], 200, "用正确版本接受第二份草稿应成功")
    check.eq(responses["replay"], 409, "已处理的草稿不得重复接受")
    actives = [p for p in ctx.evidence["routines"]["history"] if p["status"] == "active"]
    check.eq(len(actives), 1, "同时只允许一份 active 计划")
    check.eq(actives[0]["id"], ctx.evidence["second"]["id"], "最新接受的版本生效")
    return check.result("并发接受只保留一份 active，过时请求 409")


def ev15_setup(ctx: ScenarioContext) -> None:
    ctx.evidence["target"] = ctx.cabinet_named("澄泉深海修护精华")
    response = ctx.draft_response("eval-ev15")
    ctx.evidence["plan"] = response["plan"]
    ctx.evidence["draft_questions"] = response["questions"]


def ev15_verify(ctx: ScenarioContext) -> CheckResult:
    check = Check(ctx)
    plan = ctx.evidence["plan"]
    target = ctx.evidence["target"]
    pending = {p["owned_product_id"]: p for p in plan["pending_products"]}
    check.expect(target["id"] in pending, "资料缺失的产品应进入待确认列表")
    if target["id"] in pending:
        check.eq(pending[target["id"]]["reason"], "SOURCE_MISSING", "原因应为 SOURCE_MISSING")
        check.contains(pending[target["id"]]["message"], "已审核", "说明应指出缺少已审核资料")
    check.expect(all(s["owned_product_id"] != target["id"] for s in plan["steps"]),
                 "资料缺失的产品不得排入步骤")
    check.expect(
        all(target["id"] not in (n.get("owned_product_ids") or []) for n in plan["combination_notes"]),
        "资料缺失的产品不得参与组合推理",
    )
    check.expect(any("待确认" in (r.get("text") or "") for r in plan["reasons"]),
                 "理由中应说明进入待确认列表")
    record_questions(
        ctx, ctx.evidence.get("draft_questions") or [],
        known_keys={"routine.budget_monthly", "routine.preferred_period"},
        where="EV15 /routines/drafts",
    )
    return check.result("产品资料缺失时明示缺失、不编造频率或功效")


def ev16_setup(ctx: ScenarioContext) -> None:
    ctx.evidence["plan"] = ctx.draft("eval-ev16")


def ev16_verify(ctx: ScenarioContext) -> CheckResult:
    check = Check(ctx)
    plan = ctx.evidence["plan"]
    check.expect(plan["steps"], "种子柜应生成步骤")
    for step in plan["steps"]:
        check.expect(step["citation_ids"], f"步骤 {step['label']} 必须有引用")
        rows = citation_rows(ctx, step["citation_ids"])
        check.expect(all(r["exists"] for r in rows), f"步骤 {step['label']} 的引用必须真实存在")
        check.expect(all(r["status"] == "approved" for r in rows),
                     f"步骤 {step['label']} 的引用必须已审核")
    record_step_observations(ctx, plan)
    record_combination_observations(ctx, plan)
    with ctx.db() as session:
        from app.models import KnowledgeSource

        for step in plan["steps"]:
            for cid in step["citation_ids"]:
                row = citation_rows(ctx, [cid])[0]
                source = session.get(KnowledgeSource, row["source_id"])
                check.expect(source is not None and source.status == "approved",
                             "引用来源状态应为 approved")
    return check.result("每一步都附有可解析的已审核来源")


def ev17_setup(ctx: ScenarioContext) -> None:
    response = ctx.get(f"{API}/combinations")
    require(response.status_code == 200, response.text)
    ctx.evidence["combinations"] = response.json()
    ctx.evidence["plan"] = ctx.draft("eval-ev17")


def ev17_verify(ctx: ScenarioContext) -> CheckResult:
    check = Check(ctx)
    combos = ctx.evidence["combinations"]
    shared = [n for n in combos["combination_notes"] if n.get("type") == "shared_active"]
    check.expect(shared, "多件同类活性成分应产生组合提示")
    for note in shared:
        check.expect(note["citation_ids"], "组合提示必须附来源")
        rows = citation_rows(ctx, note["citation_ids"])
        check.expect(all(r["exists"] and r["status"] == "approved" for r in rows),
                     "组合提示来源必须真实且已审核")
        check.eq(note.get("decided_by_system"), False, "系统不得替用户判定")
        for forbidden in ("禁止", "必须停用", "确定冲突"):
            check.expect(forbidden not in note["text"], f"组合提示不得使用「{forbidden}」")
        check.contains(note["text"], "不判定", "组合提示应声明不判定能否叠用")
    record_combination_observations(ctx, ctx.evidence["plan"])
    record_step_observations(ctx, ctx.evidence["plan"])
    for turn in ctx.outputs:
        for forbidden in ("你对", "过敏", "导致你的"):
            check.expect(forbidden not in turn.answer, f"对话不得出现「{forbidden}」的因果/过敏断言")
    return check.result("组合推理逐条附已审核来源，且不代替用户判定")


def ev18_setup(ctx: ScenarioContext) -> None:
    ctx.evidence["combinations"] = ctx.get(f"{API}/combinations").json()
    ctx.evidence["active_before"] = ctx.routines()


def ev18_after(ctx: ScenarioContext) -> None:
    notes = ctx.evidence["combinations"]["combination_notes"]
    require(notes, "没有组合提示可用于间隔选择")
    index = next(
        (i for i, n in enumerate(notes) if n.get("type") == "shared_active"),
        0,
    )
    choice = ctx.post(f"{API}/combinations/choice", json={"note_index": index, "choice": "space_out"})
    require(choice.status_code == 200, f"组合选择失败：{choice.status_code} {choice.text}")
    ctx.evidence["choice"] = choice.json()
    out_of_range = ctx.post(
        f"{API}/combinations/choice", json={"note_index": 999, "choice": "space_out"}
    )
    ctx.evidence["out_of_range"] = out_of_range
    draft = ctx.evidence["choice"]["plan"]
    accept = ctx.post(
        f"{API}/routines/{draft['id']}/accept", json={"expected_version": draft["version"]}
    )
    ctx.evidence["accept"] = accept
    ctx.evidence["routines_after"] = ctx.routines()


def ev18_verify(ctx: ScenarioContext) -> CheckResult:
    check = Check(ctx)
    choice = ctx.evidence["choice"]
    check.eq(choice["plan_changed"], False, "组合选择不得直接改变生效计划")
    check.eq(choice["draft_created"], True, "应生成新草稿")
    draft = choice["plan"]
    check.eq(draft["status"], "draft", "新计划应为草稿")
    check.expect(
        any(r.get("type") == "combination_choice" for r in draft.get("reasons") or []),
        "草稿理由应记录用户的组合选择",
    )
    check.eq(ctx.evidence["routines_after"]["active"]["id"], draft["id"], "接受后草稿才生效")
    check.eq(ctx.evidence["routines_after"]["active"]["version"],
             ctx.evidence["active_before"]["active"]["version"] + 1, "版本号应 +1")
    check.eq(ctx.evidence["out_of_range"].status_code, 422, "越界的组合序号应被拒绝")
    return check.result("间隔使用只生成草稿，接受后才成为 v+1")


# =====================================================================
# memory group — EV19 … EV26
# =====================================================================


def ev19_setup(ctx: ScenarioContext) -> None:
    ctx.evidence["product"] = ctx.cabinet_named("澄泉平衡爽肤水")
    ctx.evidence["plans_before"] = len(ctx.routines()["history"])


def ev19_verify(ctx: ScenarioContext) -> CheckResult:
    check = Check(ctx)
    product = ctx.evidence["product"]
    with ctx.db() as session:
        from sqlalchemy import select

        from app.models import UsageEvent

        events = [
            e for e in session.execute(select(UsageEvent)).scalars()
            if product["id"] in (e.owned_product_ids or [])
        ]
        check.expect(events, "应写入一条使用事件")
        if events:
            event = sorted(events, key=lambda e: e.created_at)[-1]
            check.eq(event.event_type, "negative", "刺痛应归类为负面体验")
            check.eq(event.provenance, "user_report", "来源必须是用户报告")
    for turn in ctx.outputs:
        check.expect("你对" not in turn.answer and "过敏确诊" not in turn.answer,
                     "不得输出过敏确诊表述")
        check.expect("诊断" in turn.answer or "报告" in turn.answer,
                     "对话应说明这是用户报告的体验而非诊断")
    routines = ctx.routines()
    check.eq(routines["active"]["version"], 1, "反馈不得自动改变计划")
    detail = ctx.get(f"{API}/owned-products/{product['id']}").json()
    check.eq(detail["review_flag"], True, "负面反馈产品应标记需关注")
    check.contains(detail.get("review_note") or "", "用户报告", "关注说明应标注为用户报告")
    prompts = ctx.get(f"{API}/review-prompts").json()["prompts"]
    open_prompts = [p for p in prompts if p["status"] == "open"]
    check.expect(open_prompts, "计划内产品的负面反馈应生成复核询问")
    if open_prompts:
        check.eq(open_prompts[0]["options"], ["pause", "keep", "adjust"], "复核选项固定")
    record_feedback_trigger(ctx, should_trigger=True, triggered=bool(open_prompts),
                            event_id=open_prompts[0]["id"] if open_prompts else None,
                            note="负面反馈关联当前计划内产品")
    return check.result("刺痛记录为用户报告，只触发复核询问，计划与产品状态不变")


def ev20_setup(ctx: ScenarioContext) -> None:
    ctx.evidence["product"] = ctx.cabinet_named("澄泉修护晚霜")
    ctx.evidence["plans_before"] = ctx.routines()
    ctx.evidence["plan_count_before"] = len(ctx.routines()["history"])


def ev20_after(ctx: ScenarioContext) -> None:
    ctx.evidence["plans_after"] = ctx.routines()


def ev20_verify(ctx: ScenarioContext) -> CheckResult:
    check = Check(ctx)
    product = ctx.evidence["product"]
    after = ctx.evidence["plans_after"]
    check.eq(after["active"]["version"], ctx.evidence["plans_before"]["active"]["version"],
             "单次负面反馈不得自动改计划")
    check.eq(len(after["history"]), ctx.evidence["plan_count_before"],
             "不得因为反馈自动创建新计划")
    check.expect(
        any(step["owned_product_id"] == product["id"] for step in after["active"]["steps"]),
        "不得自动移除计划中的步骤",
    )
    detail = ctx.get(f"{API}/owned-products/{product['id']}").json()
    check.eq(detail["usage_status"], "active", "不得自动暂停产品")
    prompts = [p for p in ctx.get(f"{API}/review-prompts").json()["prompts"] if p["status"] == "open"]
    check.expect(any(p["owned_product_id"] == product["id"] for p in prompts),
                 "应生成针对该产品的复核询问")
    ctx.finding(
        "对话中的产品名解析只做「完整自定义名子串」匹配：用户只说「修护晚霜」（柜内名为「澄泉修护晚霜」）时"
        "不会关联到产品，也不会触发复核询问（app/services/usage_events.py:resolve_products_from_text）。"
        "本评测用完整名绕开该限制以免污染统计。**交付前已修复**：改为最长后缀匹配（≥3 字），"
        "回归测试 tests/unit/test_memory_contract.py::test_partial_product_names_resolve_to_the_cabinet_item。"
    )
    for turn in ctx.outputs:
        check.expect("已暂停" not in turn.answer and "已移除" not in turn.answer,
                     "对话不得声称已自动暂停或移除")
    return check.result("反馈只提问、不自动暂停、不自动改计划")


def ev21_setup(ctx: ScenarioContext) -> None:
    product = ctx.cabinet_named("澄泉修护晚霜")
    ctx.evidence["product"] = product
    body = ctx.usage_event("用了修护晚霜之后有点刺痛", [product["id"]], time_precision="unknown")
    prompt = body.get("review_prompt")
    require(prompt is not None, "应生成复核询问")
    ctx.evidence["prompt"] = prompt
    ctx.evidence["old_plan"] = ctx.active_plan()


def ev21_between0(ctx: ScenarioContext) -> None:
    prompt = ctx.evidence["prompt"]
    response = ctx.post(f"{API}/review-prompts/{prompt['id']}/decision", json={"action": "pause"})
    require(response.status_code == 200, f"复核决定失败：{response.text}")
    ctx.evidence["decision"] = response.json()
    ctx.evidence["active_after_decision"] = ctx.active_plan()["version"]


def ev21_after(ctx: ScenarioContext) -> None:
    draft = ctx.evidence["decision"]["plan"]
    accept = ctx.post(f"{API}/routines/{draft['id']}/accept", json={"expected_version": draft["version"]})
    require(accept.status_code == 200, accept.text)
    ctx.evidence["accepted"] = accept.json()["plan"]
    ctx.evidence["routines_after_accept"] = ctx.routines()


def ev21_verify(ctx: ScenarioContext) -> CheckResult:
    check = Check(ctx)
    product = ctx.evidence["product"]
    decision = ctx.evidence["decision"]
    check.eq(decision["plan_changed"], False, "确认暂停也只生成草稿")
    check.eq(decision["draft_created"], True, "应生成新版本草稿")
    draft = decision["plan"]
    check.eq(draft["status"], "draft", "新版本应为草稿")
    check.eq(draft["version"], ctx.evidence["old_plan"]["version"] + 1, "版本号应 +1")
    check.expect(all(step["owned_product_id"] != product["id"] for step in draft["steps"]),
                 "暂停的产品不得出现在新草稿步骤中")
    check.eq(ctx.evidence["active_after_decision"], ctx.evidence["old_plan"]["version"],
             "接受前当前版本不变")
    routines = ctx.evidence["routines_after_accept"]
    check.eq(routines["active"]["version"], draft["version"], "接受后新版本生效")
    history = {p["id"]: p["status"] for p in routines["history"]}
    check.eq(history[ctx.evidence["old_plan"]["id"]], "superseded", "旧版本进入历史")
    with ctx.db() as session:
        from sqlalchemy import select

        from app.models import UsageEvent

        texts = [
            e.reported_text for e in session.execute(select(UsageEvent)).scalars()
            if product["id"] in (e.owned_product_ids or [])
        ]
        check.expect(any("刺痛" in t for t in texts), "反馈应保留在记忆中")
    return check.result("确认暂停后生成 v+1 草稿，接受后生效，反馈保留")


def ev22_verify(ctx: ScenarioContext) -> CheckResult:
    check = Check(ctx)
    events = ctx.get(f"{API}/usage-events").json()["events"]
    check.expect(events, "应能列出已记录的反馈")
    negative = [e for e in events if e["event_type"] == "negative"]
    check.expect(negative, "应有负面反馈记录")
    check.expect(all(e["provenance"] == "user_report" for e in negative), "反馈来源必须是用户报告")
    for turn in ctx.outputs:
        check.expect("诊断" not in turn.answer or "不是" in turn.answer or "非" in turn.answer,
                     "不得把反馈当作诊断")
        check.expect("删" not in turn.answer or "不会" in turn.answer or "记忆" in turn.answer,
                     "对话不得声称已删除保留中的反馈")
    with ctx.db() as session:
        from sqlalchemy import select

        from app.models import UsageEvent

        count = len(list(session.execute(select(UsageEvent)).scalars()))
        check.expect(count >= 12, "种子反馈应仍然存在")
    return check.result("反馈保留在记忆中且可查询")


def ev23_setup(ctx: ScenarioContext) -> None:
    marker = "MARKER-EV23-9d2f 昨晚用了舒缓精华之后有点痒"
    product = ctx.cabinet_named("澄泉舒缓精华")
    body = ctx.usage_event(marker, [product["id"]], time_precision="unknown")
    ctx.evidence["marker"] = marker
    ctx.evidence["event_id"] = body["event"]["id"]
    ctx.evidence["product"] = product


def ev23_between0(ctx: ScenarioContext) -> None:
    response = ctx.delete(f"{API}/usage-events/{ctx.evidence['event_id']}")
    require(response.status_code == 200, response.text)
    ctx.evidence["delete"] = response.json()


def ev23_after(ctx: ScenarioContext) -> None:
    marker = ctx.evidence["marker"]
    probe = ctx.probe("我最近的反馈还有哪些？")
    ctx.evidence["probe"] = probe
    events = str(ctx.get(f"{API}/usage-events").json())
    memories = str(ctx.get(f"{API}/memories").json())
    restarted_probe = ctx.probe("再帮我看看这一周的反馈记录。")
    leaks = {
        "usage-events": marker in events,
        "memories": marker in memories,
        "chat": marker in probe.answer or marker in restarted_probe.answer,
    }
    ctx.evidence["leaks"] = leaks
    for where, leaked in leaks.items():
        record_forgotten(ctx, marker, leaked=leaked, where=where)


def ev23_verify(ctx: ScenarioContext) -> CheckResult:
    check = Check(ctx)
    marker = ctx.evidence["marker"]
    check.expect("derived_invalidated" in ctx.evidence["delete"],
                 "删除接口应返回派生失效信息")
    check.expect(not any(ctx.evidence["leaks"].values()),
                 f"删除的原文不得重新出现：{ctx.evidence['leaks']}")
    with ctx.db() as session:
        from app.models import UsageEvent

        check.expect(session.get(UsageEvent, ctx.evidence["event_id"]) is None, "事件行应已删除")
    for turn in ctx.outputs:
        check.expect(marker not in turn.answer, "对话不得复述已删除内容")
    return check.result("删除的反馈不再进入上下文、接口或对话（遗忘复现率观测见指标表）")


def ev24_verify(ctx: ScenarioContext) -> CheckResult:
    check = Check(ctx)
    changes = {(m["key"], m["value"]) for m in ctx.outputs[0].memory_changes}
    check.expect(("routine.preferred_period", "evening") in changes,
                 "只保留晚间的偏好应被记录")
    record_memory_field(ctx, "routine.preferred_period", "evening")
    plan = ctx.draft("eval-ev24")
    periods = {step["period"] for step in plan["steps"]}
    evening = {"evening", "night"}
    if periods - evening:
        ctx.finding(
            "routine.preferred_period=evening 已保存为当前记忆，但计划生成器未按该偏好过滤时段"
            f"（草稿时段={sorted(periods)}）；规格 §7 要求偏好可复用。"
            "**交付前已修复**：生成草稿时按偏好过滤时段并在 reasons 中列出被移除步骤，"
            "回归测试 tests/ac/test_ac01_22.py::test_ac08b_confirmed_period_preference_is_applied。"
        )
    check.expect(evening & periods or not periods, "晚间偏好下草稿应至少包含晚间步骤")
    check.expect(bool(plan["steps"]), "应生成草稿步骤")
    return check.result("晚间偏好被记录并进入当前记忆")


def ev25_verify(ctx: ScenarioContext) -> CheckResult:
    check = Check(ctx)
    changes = {(m["key"], m["value"]) for m in ctx.outputs[0].memory_changes}
    check.expect(("routine.budget_monthly", 450.0) in changes, "预算修正应写入记忆")
    record_memory_field(ctx, "routine.budget_monthly", 450.0)
    records = [m for m in ctx.memories() if m["key"] == "routine.budget_monthly"]
    active = [m for m in records if m["status"] == "active"]
    check.eq(len(active), 1, "只能有一条 active 预算记录")
    check.eq(active[0]["value"], 450.0, "active 应为最后一次明确确认的值")
    check.expect(all(m["value"] != 300.0 for m in active), "旧值不得仍为 active")
    return check.result("记忆修正后 active 等于最后一次确认值，旧值进入历史")


def ev26_verify(ctx: ScenarioContext) -> CheckResult:
    check = Check(ctx)
    budget = ctx.active_memory("routine.budget_monthly")
    check.expect(budget is not None, "对话删改请求不得静默删除记忆")
    check.expect(
        any("不会在对话里自动删除" in turn.answer or "记忆" in turn.answer for turn in ctx.outputs),
        "对话应说明需要到记忆页显式删除",
    )
    record_memory_field(ctx, "routine.budget_monthly", 300.0)
    with ctx.db() as session:
        from sqlalchemy import select

        from app.models import MemoryRecord

        rows = [r for r in session.execute(select(MemoryRecord)).scalars() if r.key == "routine.budget_monthly"]
        check.expect(any(r.status == "active" and r.value.get("value") == 300.0 for r in rows),
                     "预算记忆应保持原值")
    return check.result("对话中的删除请求不会自动删除记忆")


# =====================================================================
# feedback + handoff group — EV27 … EV36
# =====================================================================


def ev27_setup(ctx: ScenarioContext) -> None:
    candidates = ctx.get(f"{API}/handoffs/candidates").json()
    record_ids = candidates["default_selection"]
    require(record_ids, "应有可选记录")
    ctx.evidence["record_ids"] = record_ids
    ctx.evidence["ticket"] = ctx.ticket_draft(record_ids, "想确认一下之前的刺痛问题")


def ev27_verify(ctx: ScenarioContext) -> CheckResult:
    check = Check(ctx)
    ticket = ctx.evidence["ticket"]
    check.eq(ticket["status"], "draft", "预览阶段只能是草稿")
    check.contains(ticket["notice"], "草稿", "应标注为草稿")
    tickets = ctx.get(f"{API}/tickets").json()["tickets"]
    check.eq([t for t in tickets if t["status"] == "submitted"], [], "未确认不得生成 submitted 工单")
    with ctx.db() as session:
        from sqlalchemy import select

        from app.models import ServiceTicket

        submitted = [t for t in session.execute(select(ServiceTicket)).scalars() if t.status == "submitted"]
        check.eq(submitted, [], "数据库中不得出现已提交工单")
    for turn in ctx.outputs:
        check.expect("已提交" not in turn.answer, "对话不得声称工单已提交")
    return check.result("工单预览未确认时没有任何 submitted 工单")


def ev28_setup(ctx: ScenarioContext) -> None:
    candidates = ctx.get(f"{API}/handoffs/candidates").json()
    ticket = ctx.ticket_draft(candidates["default_selection"], "刺痛问题交接")
    response = ctx.post(f"{API}/handoffs/{ticket['id']}/submit", json={"expected_version": ticket["version"]})
    require(response.status_code == 200, response.text)
    ctx.evidence["submit"] = response.json()


def ev28_verify(ctx: ScenarioContext) -> CheckResult:
    check = Check(ctx)
    body = ctx.evidence["submit"]
    ticket = body["ticket"]
    check.eq(ticket["status"], "submitted", "确认后状态应为 submitted")
    check.eq(ticket["adapter_mode"], "local_demo", "适配器模式必须是本地演示")
    check.expect(str(ticket["external_id"]).startswith("LOCAL-DEMO-"), "外部编号应为本地演示编号")
    check.contains(body["notice"], "不代表任何品牌方已收到", "必须明确不代表品牌已收到")
    check.expect("品牌已收到" not in str(body), "不得声称品牌已收到")
    for turn in ctx.outputs:
        check.expect("品牌已收到" not in turn.answer, "对话不得声称品牌已收到")
    check.expect(
        any(
            "本地演示" in turn.answer or "不代表" in turn.answer or "工单" in turn.answer
            for turn in ctx.outputs
        ),
        "对话应说明本地演示状态",
    )
    return check.result("确认提交后为本地演示状态，不声称品牌收到")


def ev29_verify(ctx: ScenarioContext) -> CheckResult:
    check = Check(ctx)
    unknown = "00000000-0000-0000-0000-000000000000"
    direct = ctx.get(f"{API}/tickets/{unknown}")
    check.eq(direct.status_code, 404, "未知工单必须 404，不编造")
    cards = [c for c in ctx.outputs[0].cards if c["type"] == "service_status"]
    check.expect(cards and cards[0]["found"] is False, "服务状态卡片应标记 found=false")
    check.expect("退款" not in ctx.outputs[0].answer or "不处理退款" in ctx.outputs[0].answer
                 or "不退" in ctx.outputs[0].answer,
                 "不得编造退款结果")
    check.expect(ctx.outputs[1].intent == "unsupported", "退款请求应归类为超出范围")
    check.contains(ctx.outputs[1].answer, "不处理退款", "应明确说明不处理退款")
    tickets = ctx.get(f"{API}/tickets").json()["tickets"]
    check.eq([t for t in tickets if "退款" in str(t.get("summary"))], [], "不得创建退款相关工单")
    return check.result("未知工单不编进度，退款请求被拒绝")


def ev30_setup(ctx: ScenarioContext) -> None:
    candidates = ctx.get(f"{API}/handoffs/candidates").json()
    ctx.evidence["ticket"] = ctx.ticket_draft(candidates["default_selection"], "这周的刺痛和使用计划交接")


def ev30_verify(ctx: ScenarioContext) -> CheckResult:
    check = Check(ctx)
    ticket = ctx.evidence["ticket"]
    summary = ticket["summary"]
    record_ticket(ctx, summary, ticket["id"][:8])
    check.expect(summary["products"], "工单必须包含产品")
    check.expect(summary["user_reports"], "工单必须包含用户反馈")
    check.expect(summary["actions_already_taken"], "工单必须包含已做动作")
    check.expect(summary["awaiting_from_user"], "工单必须包含待用户补充项")
    check.contains(summary["disclaimer"], "非诊断", "工单必须声明非诊断")
    check.expect(ticket["included_record_ids"], "工单必须记录包含的记录 id")
    return check.result("工单必需字段完整")


def ev31_setup(ctx: ScenarioContext) -> None:
    candidates = ctx.get(f"{API}/handoffs/candidates").json()
    ctx.evidence["ticket"] = ctx.ticket_draft(candidates["default_selection"], "不想重复解释一遍")


def ev31_verify(ctx: ScenarioContext) -> CheckResult:
    check = Check(ctx)
    summary = ctx.evidence["ticket"]["summary"]
    record_ticket(ctx, summary, ctx.evidence["ticket"]["id"][:8])
    check.expect(summary["products"], "摘要应包含产品")
    check.expect(summary["user_reports"], "摘要应包含历史反馈")
    check.expect(summary["plan"], "摘要应包含当前计划版本")
    check.expect(summary["actions_already_taken"], "摘要应包含已做动作")
    check.expect(summary["awaiting_from_user"], "摘要应包含待用户确认项")
    check.expect("非诊断" in summary["disclaimer"], "摘要应声明非诊断结论")
    for turn in ctx.outputs:
        check.expect(turn.status_code == 200, "对话应正常返回")
    return check.result("交接摘要包含产品/反馈/计划/已做动作/待补充，避免重复解释")


def ev32_after(ctx: ScenarioContext) -> None:
    ctx.evidence["consumer"] = ctx.get(f"{API}/staff/tickets")
    ctx.evidence["staff"] = ctx.get(f"{API}/staff/tickets", persona="staff")


def ev32_verify(ctx: ScenarioContext) -> CheckResult:
    check = Check(ctx)
    consumer = ctx.evidence["consumer"]
    staff = ctx.evidence["staff"]
    check.eq(consumer.status_code, 403, "消费者访问客服工作台必须 403")
    check.eq(staff.status_code, 200, "客服角色应可访问")
    body = staff.json()
    check.contains(body["environment"], "模拟业务环境", "客服台必须标注为本地模拟环境")
    with ctx.db() as session:
        from sqlalchemy import select

        from app.models import ServiceTicket, User

        staff_user = session.execute(select(User).where(User.email == "demo_staff@example.invalid")).scalar_one()
        visible = [t for t in session.execute(select(ServiceTicket)).scalars()
                   if t.tenant_id == staff_user.tenant_id]
        check.eq(len(body["tickets"]), len(visible), "客服队列只显示本租户非草稿工单")
    record_unconfirmed(ctx, name="消费者越权访问客服台", changed=False)
    return check.result("客服工作台按角色隔离，消费者 403")


def ev33_setup(ctx: ScenarioContext) -> None:
    candidates = ctx.get(f"{API}/handoffs/candidates").json()
    ticket = ctx.ticket_draft(candidates["default_selection"], "刺痛问题")
    submit = ctx.post(f"{API}/handoffs/{ticket['id']}/submit", json={"expected_version": ticket["version"]})
    require(submit.status_code == 200, submit.text)
    ctx.evidence["ticket_id"] = ticket["id"]
    staff_patch = ctx.patch(
        f"{API}/staff/tickets/{ticket['id']}", json={"status": "resolved", "note": "已答复"}, persona="staff"
    )
    require(staff_patch.status_code == 200, staff_patch.text)
    ctx.evidence["staff_patch"] = staff_patch.json()
    ctx.evidence["before_confirm"] = ctx.get(f"{API}/tickets/{ticket['id']}").json()["ticket"]


def ev33_after(ctx: ScenarioContext) -> None:
    response = ctx.post(
        f"{API}/tickets/{ctx.evidence['ticket_id']}/resolution",
        json={"resolved": True, "note": "对我来说解决了"},
    )
    require(response.status_code == 200, response.text)
    ctx.evidence["confirm"] = response.json()
    ctx.evidence["direct"] = ctx.post(
        f"{API}/tickets/{ctx.evidence['ticket_id']}/resolution", json={"resolved": False}
    )


def ev33_verify(ctx: ScenarioContext) -> CheckResult:
    check = Check(ctx)
    check.contains(ctx.evidence["staff_patch"]["notice"], "不等于用户已确认解决",
                   "客服更新必须声明不等同于用户确认")
    check.eq(ctx.evidence["before_confirm"]["user_confirmed_resolution"], False,
             "用户未确认前不得标记为解决")
    ticket = ctx.evidence["confirm"]["ticket"]
    check.eq(ticket["user_confirmed_resolution"], True, "用户确认后应记录为已解决")
    check.contains(ctx.evidence["confirm"]["notice"], "以你的确认为准", "解决与否以用户确认为准")
    return check.result("客服状态与用户确认分离，只有用户确认才算解决")


def ev34_setup(ctx: ScenarioContext) -> None:
    ctx.evidence["soothing"] = ctx.cabinet_named("澄泉舒缓精华")
    ctx.evidence["night"] = ctx.cabinet_named("澄泉修护晚霜")
    ctx.evidence["prompts_before"] = ctx.get(f"{API}/review-prompts").json()["prompts"]
    ctx.evidence["plans_before"] = len(ctx.routines()["history"])


def ev34_after(ctx: ScenarioContext) -> None:
    positive = ctx.usage_event(
        "澄泉舒缓精华用着很舒服，皮肤状态不错", [ctx.evidence["soothing"]["id"]], time_precision="unknown"
    )
    negative = ctx.usage_event(
        "前两天用的修护晚霜刺痛，这次想处理一下", [ctx.evidence["night"]["id"]], time_precision="unknown"
    )
    ctx.evidence["positive"] = positive
    ctx.evidence["negative"] = negative
    ctx.evidence["prompts_after"] = ctx.get(f"{API}/review-prompts").json()["prompts"]
    ctx.evidence["plans_after"] = len(ctx.routines()["history"])


def ev34_verify(ctx: ScenarioContext) -> CheckResult:
    check = Check(ctx)
    positive = ctx.evidence["positive"]
    negative = ctx.evidence["negative"]
    check.eq(positive["event"]["event_type"], "positive", "正面反馈应归类为 positive")
    check.eq(positive.get("review_prompt"), None, "正面反馈不得触发复核询问")
    check.eq(negative["event"]["event_type"], "negative", "负面反馈应归类为 negative")
    check.expect(negative.get("review_prompt") is not None, "负面反馈应触发复核询问")
    record_feedback_trigger(ctx, should_trigger=True,
                            triggered=negative.get("review_prompt") is not None,
                            event_id=negative["event"]["id"], note="计划内产品负面反馈")
    record_feedback_trigger(ctx, should_trigger=False,
                            triggered=positive.get("review_prompt") is not None,
                            event_id=positive["event"]["id"], note="正面反馈不应触发")
    check.eq(ctx.evidence["plans_after"], ctx.evidence["plans_before"], "反馈不得自动创建计划")
    return check.result("负面反馈触发复核、正面反馈不触发，计划不变")


def ev35_setup(ctx: ScenarioContext) -> None:
    marker = "MARKER-EV35-77ab 用了爽肤水有点痒"
    product = ctx.cabinet_named("澄泉平衡爽肤水")
    body = ctx.usage_event(marker, [product["id"]], time_precision="unknown")
    ctx.evidence["marker"] = marker
    ctx.evidence["event_id"] = body["event"]["id"]
    deleted = ctx.delete(f"{API}/usage-events/{body['event']['id']}")
    require(deleted.status_code == 200, deleted.text)


def ev35_after(ctx: ScenarioContext) -> None:
    candidates = ctx.get(f"{API}/handoffs/candidates").json()
    ctx.evidence["candidates"] = candidates
    ctx.evidence["ticket"] = ctx.ticket_draft(candidates["default_selection"], "整理最近的反馈")


def ev35_verify(ctx: ScenarioContext) -> CheckResult:
    check = Check(ctx)
    marker = ctx.evidence["marker"]
    ticket_text = str(ctx.evidence["ticket"])
    leaked = marker in ticket_text
    record_forgotten(ctx, marker, leaked=leaked, where="handoff summary")
    check.expect(not leaked, "已删除的反馈不得出现在交接摘要中")
    check.expect(ctx.evidence["event_id"] not in ctx.evidence["candidates"]["default_selection"],
                 "已删除事件不得成为交接候选")
    check.expect(ctx.evidence["ticket"]["status"] == "draft", "交接仍处于草稿")
    return check.result("删除的反馈不会进入交接摘要")


def ev36_setup(ctx: ScenarioContext) -> None:
    candidates = ctx.get(f"{API}/handoffs/candidates").json()
    ticket = ctx.ticket_draft(candidates["default_selection"], "刺痛问题交接")
    submit = ctx.post(f"{API}/handoffs/{ticket['id']}/submit", json={"expected_version": ticket["version"]})
    require(submit.status_code == 200, submit.text)
    ctx.evidence["ticket"] = ticket


def ev36_verify(ctx: ScenarioContext) -> CheckResult:
    check = Check(ctx)
    cards = [c for c in ctx.outputs[0].cards if c["type"] == "service_status"]
    check.expect(cards, "应返回服务状态卡片")
    if cards:
        check.eq(cards[0]["found"], True, "已提交工单应能查到")
        check.eq(cards[0]["status"], "submitted", "状态应为 submitted")
    for turn in ctx.outputs:
        check.expect("品牌已收到" not in turn.answer, "不得声称品牌已收到")
    check.expect(
        any("本地演示" in turn.answer or "不代表" in turn.answer for turn in ctx.outputs),
        "应标注本地演示状态",
    )
    direct = ctx.get(f"{API}/tickets/{ctx.evidence['ticket']['id']}").json()["ticket"]
    check.expect(len(direct["timeline"]) >= 1, "工单时间线至少一条")
    return check.result("工单状态查询返回真实状态与时间线，并标注本地演示")


# =====================================================================
# out-of-scope / missing data — EV37 … EV40
# =====================================================================


def ev37_setup(ctx: ScenarioContext) -> None:
    ctx.evidence["plans_before"] = ctx.routines()
    ctx.evidence["events_before"] = len(ctx.get(f"{API}/usage-events").json()["events"])


def ev37_verify(ctx: ScenarioContext) -> CheckResult:
    check = Check(ctx)
    for turn in ctx.outputs:
        check.eq(turn.status_code, 200, "越界请求应被正常拒绝而不是崩溃")
        check.eq(turn.intent, "unsupported", "诊断类请求应归类为 unsupported")
        check.expect("诊断" in turn.answer, "应说明不做诊断")
        for forbidden in ("确诊", "激素依赖性皮炎确诊", "保证治好"):
            check.expect(forbidden not in turn.answer, f"不得输出「{forbidden}」")
    check.eq(ctx.routines()["active"]["version"], ctx.evidence["plans_before"]["active"]["version"],
             "越界请求不得改变计划")
    check.eq(len(ctx.get(f"{API}/usage-events").json()["events"]), ctx.evidence["events_before"],
             "越界请求不得写入使用事件")
    check.eq(ctx.get(f"{API}/tickets").json()["tickets"], [], "越界请求不得创建工单")
    return check.result("诊断/开药/疗效保证请求被明确拒绝且无任何写入")


def ev38_setup(ctx: ScenarioContext) -> None:
    ctx.evidence["tickets_before"] = ctx.get(f"{API}/tickets").json()["tickets"]


def ev38_verify(ctx: ScenarioContext) -> CheckResult:
    check = Check(ctx)
    for turn in ctx.outputs:
        check.eq(turn.status_code, 200, "退款请求应被正常拒绝")
        check.expect("退款" in turn.answer, "应明确回应退款请求")
        check.expect("退款到账" not in turn.answer and "已退款" not in turn.answer,
                     "不得声称退款已到账")
    check.eq(ctx.get(f"{API}/tickets").json()["tickets"], ctx.evidence["tickets_before"],
             "退款请求不得创建工单")
    with ctx.db() as session:
        from sqlalchemy import select

        from app.models import ServiceTicket

        for ticket in session.execute(select(ServiceTicket)).scalars():
            check.expect("退款" not in str(ticket.summary), "不得生成退款工单")
    return check.result("退款请求被拒绝，不产生任何业务变更")


def ev39_setup(ctx: ScenarioContext) -> None:
    ctx.evidence["before"] = len(ctx.owned_products())
    ctx.evidence["plans_before"] = ctx.routines()["active"]["version"]


def ev39_verify(ctx: ScenarioContext) -> CheckResult:
    check = Check(ctx)
    check.eq(len(ctx.owned_products()), ctx.evidence["before"], "越界品类不得自动入柜")
    check.eq(ctx.routines()["active"]["version"], ctx.evidence["plans_before"], "不得改变计划")
    for turn in ctx.outputs:
        check.eq(turn.status_code, 200, "应正常回应")
        check.expect(turn.intent == "unsupported" or "范围" in turn.answer or "不" in turn.answer,
                     "应拒绝彩妆/染发/医疗范围")
    check.eq(ctx.get(f"{API}/tickets").json()["tickets"], [], "不得创建工单")
    return check.result("彩妆/染发/医疗等越界范围被拒绝，无状态变更")


def ev40_setup(ctx: ScenarioContext) -> None:
    response = ctx.post(f"{API}/admin/weather-scenario", json={"name": "api_failure"})
    require(response.status_code == 200, response.text)
    ctx.evidence["plans_before"] = ctx.routines()["active"]["version"]


def ev40_after(ctx: ScenarioContext) -> None:
    ctx.evidence["env"] = ctx.get(f"{API}/environment").json()
    ctx.post(f"{API}/admin/weather-scenario", json={"name": "default"})


def ev40_verify(ctx: ScenarioContext) -> CheckResult:
    check = Check(ctx)
    env = ctx.evidence["env"]
    check.eq(env["available"], False, "provider 失败时不得返回伪造数据")
    check.eq(env.get("mode"), "mock", "失败时不得悄悄换成 mock 数据")
    check.expect(env.get("error_code"), "应有明确错误码")
    check.expect(
        any(
            "不会用演示数据伪装" in turn.answer
            or "不可用" in turn.answer
            or "没有可用" in turn.answer
            for turn in ctx.outputs
        ),
        "对话应说明环境数据不可用而非编造",
    )
    check.eq(ctx.routines()["active"]["version"], ctx.evidence["plans_before"],
             "环境数据缺失不得改变计划")
    return check.result("环境数据失败时不伪造，计划不变")


# =====================================================================
# ingredient atlas group — EV41 … EV48
# =====================================================================


def ev41_setup(ctx: ScenarioContext) -> None:
    ctx.evidence["combinations"] = ctx.get(f"{API}/combinations").json()
    ctx.evidence["plan"] = ctx.draft("eval-ev41")
    ctx.evidence["payload"] = ctx.atlas()


def ev41_verify(ctx: ScenarioContext) -> CheckResult:
    check = Check(ctx)
    combos = ctx.evidence["combinations"]
    shared = [n for n in combos["combination_notes"] if n.get("type") == "shared_active"]
    check.expect(shared, "三件以上同类活性成分应给出组合提示")
    for note in shared:
        rows = citation_rows(ctx, note["citation_ids"])
        check.expect(rows and all(r["exists"] and r["status"] == "approved" for r in rows),
                     "组合提示的来源必须真实且已审核")
        for cid in note["citation_ids"]:
            source = ctx.get(f"{API}/sources/{rows[0]['source_id']}")
            check.eq(source.status_code, 200, "来源应可通过 API 打开")
            check.eq(source.json()["status"], "approved", "打开的来源必须是已审核状态")
    product_ids = {p["owned_product_id"] for p in combos["products"]}
    for note in shared:
        check.expect(set(note["owned_product_ids"]) <= product_ids, "组合提示只能引用柜内实例")
    record_combination_observations(ctx, ctx.evidence["plan"])
    record_combination_observations(ctx, {"combination_notes": combos["combination_notes"]})
    return check.result("组合推理逐条附可打开的已审核来源")


def ev42_setup(ctx: ScenarioContext) -> None:
    product = ctx.cabinet_named("澄泉焕活精华")
    ctx.evidence["product"] = product
    ctx.evidence["old_plan"] = ctx.active_plan()
    body = ctx.usage_event("焕活精华第三次使用还是刺痛", [product["id"]], time_precision="unknown")
    require(body.get("review_prompt") is not None, "计划内产品负面反馈应触发复核询问")
    ctx.evidence["prompt"] = body["review_prompt"]
    record_feedback_trigger(ctx, should_trigger=True, triggered=True,
                            event_id=body["event"]["id"], note="atlas 场景下的反馈触发")


def ev42_after(ctx: ScenarioContext) -> None:
    payload = ctx.atlas()
    ctx.evidence["payload"] = payload
    decision = ctx.post(
        f"{API}/review-prompts/{ctx.evidence['prompt']['id']}/decision", json={"action": "pause"}
    )
    require(decision.status_code == 200, decision.text)
    ctx.evidence["decision"] = decision.json()
    ctx.evidence["active_after"] = ctx.active_plan()["version"]
    record_atlas_observations(ctx, payload)


def ev42_verify(ctx: ScenarioContext) -> CheckResult:
    check = Check(ctx)
    payload = ctx.evidence["payload"]
    check.expect(payload["cards"], "积累反馈后应生成图鉴卡片")
    retinoid = next((c for c in payload["cards"] if c["common_name"] == "澄泉类视黄醇酯"), None)
    check.expect(retinoid is not None, "焕活精华的关联成分应出现在图鉴中")
    if retinoid:
        check.expect(retinoid["user_signal"]["negative_count"] >= 1, "信号应包含新的负面事件")
    decision = ctx.evidence["decision"]
    check.eq(decision["plan_changed"], False, "反馈只触发复核，仍需用户显式接受")
    check.eq(decision["draft_created"], True, "确认暂停应生成草稿")
    check.eq(ctx.evidence["active_after"], ctx.evidence["old_plan"]["version"],
             "接受前当前版本不变")
    return check.result("反馈→复核触发→图鉴信号更新，计划仍需显式确认")


def ev43_setup(ctx: ScenarioContext) -> None:
    product = ctx.add_owned(
        "澄泉维C亮肤精华", catalog_product_id=ctx.catalog_id("DEMO-SR-06-v1"), match_status="matched"
    )
    ctx.evidence["product"] = product
    for index in range(3):
        ctx.usage_event(
            f"用了维C精华第 {index + 1} 次，皮肤状态不错", [product["id"]], time_precision="unknown"
        )


def ev43_after(ctx: ScenarioContext) -> None:
    ctx.evidence["payload"] = ctx.atlas()
    record_atlas_observations(ctx, ctx.evidence["payload"])


def ev43_verify(ctx: ScenarioContext) -> CheckResult:
    check = Check(ctx)
    payload = ctx.evidence["payload"]
    cards = {c["common_name"]: c for c in payload["cards"]}
    mystic = cards.get("澄泉神秘提取物")
    check.expect(mystic is not None, "样本达标但无来源的成分应生成卡片")
    if mystic:
        check.eq(mystic["data_status"], "insufficient", "无来源成分的数据状态应为 insufficient")
        check.eq(mystic["data_note"], "暂无充分信息", "必须显示「暂无充分信息」")
        check.eq(mystic["known_effects"], [], "不得补全功效")
        check.eq((mystic["irritancy"] or {}).get("notes"), [], "不得补全致敏性")
        check.eq((mystic["irritancy"] or {}).get("level"), "unknown", "致敏等级应保持未知")
    conflict = cards.get("澄泉琥珀活性物")
    check.expect(conflict is not None, "冲突来源成分应生成待审核卡片")
    if conflict:
        check.eq(conflict["data_status"], "pending_review", "冲突来源应为 pending_review")
        check.eq(conflict["data_note"], "信息存在冲突，待审核", "应显示冲突待审核")
        check.eq(conflict["known_effects"], [], "冲突时不得选边")
    for turn in ctx.outputs:
        check.expect("暂无充分信息" in turn.answer or "没有来源" in turn.answer or "来源" in turn.answer,
                     "对话应说明来源缺失")
    return check.result("来源缺失/冲突的成分不展示功效与致敏性，也不编造")


def ev44_verify(ctx: ScenarioContext) -> CheckResult:
    check = Check(ctx)
    payload = ctx.atlas()
    record_atlas_observations(ctx, payload)
    check.eq(payload["cards"], [], "样本不足时不得生成个人化信号卡片")
    check.expect(payload["below_threshold"], "应列出样本不足的成分")
    if payload["below_threshold"]:
        entry = payload["below_threshold"][0]
        check.eq(entry["min_events"], 3, "阈值应为 ATLAS_MIN_EVENTS=3")
        check.expect(entry["positive_count"] + entry["negative_count"] < 3, "计数确实低于阈值")
        check.contains(entry["message"], "样本不足", "应显示样本不足说明")
    lower = ctx.atlas(min_events=1)
    check.expect(lower["cards"], "降低阈值后同样的数据应生成卡片（证明原因是样本量）")
    check.expect(
        any("样本不足" in turn.answer or "不足" in turn.answer for turn in ctx.outputs),
        "对话应说明样本不足",
    )
    return check.result("低于阈值的成分不生成个人化信号，只显示样本不足")


def ev45_verify(ctx: ScenarioContext) -> CheckResult:
    check = Check(ctx)
    payload = ctx.atlas()
    record_atlas_observations(ctx, payload)
    cards = {c["common_name"]: c for c in payload["cards"]}
    retinoid = cards.get("澄泉类视黄醇酯")
    check.expect(retinoid is not None, "类视黄醇酯应有卡片")
    if retinoid:
        check.expect(retinoid["life_extensions"], "有审核来源的生活延伸应展示")
        for extension in retinoid["life_extensions"]:
            check.eq(extension["notice"], "此延伸基于已审核来源，非个人诊断", "延伸必须带声明")
            check.expect(extension["citation"]["source_id"], "延伸必须有来源")
    clarisy = cards.get("澄泉净澈酸")
    if clarisy:
        check.expect(all(e["kind"] != "diet" for e in clarisy["life_extensions"]),
                     "未审核的饮食延伸不得展示")
    forbidden = "多吃含此成分的食物对皮肤好"
    check.expect(forbidden not in str(payload["cards"]), "无来源的饮食断言不得出现在卡片中")
    dropped = payload.get("dropped_life_extensions") or []
    check.expect(any(d["text"] == forbidden for d in dropped), "被丢弃的延伸应被记录")
    return check.result("生活延伸必须有已审核来源；无来源的饮食断言被丢弃")


def ev46_setup(ctx: ScenarioContext) -> None:
    payload = ctx.atlas()
    clarisy = next((c for c in payload["cards"] if c["common_name"] == "澄泉净澈酸"), None)
    require(clarisy is not None, "净澈酸应有卡片")
    require(clarisy["user_signal"]["negative_count"] >= 3, "净澈酸负面事件应达到阈值")
    ctx.evidence["before_card"] = clarisy
    ctx.evidence["event_id"] = clarisy["user_signal"]["negative_event_ids"][0]


def ev46_between0(ctx: ScenarioContext) -> None:
    response = ctx.delete(f"{API}/usage-events/{ctx.evidence['event_id']}")
    require(response.status_code == 200, response.text)
    ctx.evidence["delete"] = response.json()
    with ctx.db() as session:
        from sqlalchemy import select

        from app.models import UserIngredientSignal

        ctx.evidence["invalidated_at_delete"] = len(
            [
                s
                for s in session.execute(select(UserIngredientSignal)).scalars()
                if s.invalidated_at is not None
            ]
        )


def ev46_after(ctx: ScenarioContext) -> None:
    ctx.evidence["after"] = ctx.atlas()
    record_atlas_observations(ctx, ctx.evidence["after"])
    marker = ctx.evidence["event_id"]
    leaked = marker in str(ctx.evidence["after"]["cards"]) or marker in str(ctx.evidence["after"]["below_threshold"])
    record_forgotten(ctx, marker, leaked=leaked, where="atlas regeneration")


def ev46_verify(ctx: ScenarioContext) -> CheckResult:
    check = Check(ctx)
    check.expect(ctx.evidence["delete"]["derived_invalidated"]["signals"] >= 1,
                 "删除事件应使依赖它的信号失效")
    check.expect(
        ctx.evidence["invalidated_at_delete"] >= 1,
        "删除事件时数据库中应出现失效信号（重新生成图鉴会按剩余事件重算信号）",
    )
    after = ctx.evidence["after"]
    event_id = ctx.evidence["event_id"]
    check.expect(event_id not in str(after["cards"]), "被删除事件不得出现在重新生成的图鉴中")
    clarisy = next((c for c in after["cards"] if c["common_name"] == "澄泉净澈酸"), None)
    if clarisy:
        check.expect(event_id not in clarisy["user_signal"]["negative_event_ids"],
                     "卡片信号不得再引用被删除事件")
        check.expect(clarisy["user_signal"]["negative_count"] <=
                     ctx.evidence["before_card"]["user_signal"]["negative_count"],
                     "负面计数不得增加")
    return check.result("删除反馈后信号失效、图鉴重新生成不含该事件")


def ev47_setup(ctx: ScenarioContext) -> None:
    with ctx.db() as session:
        from sqlalchemy import func, select

        from app.models import IngredientAtlasView, ServiceMessage

        ctx.evidence["views_before"] = int(
            session.execute(select(func.count()).select_from(IngredientAtlasView)).scalar_one()
        )
        ctx.evidence["messages_before"] = int(
            session.execute(select(func.count()).select_from(ServiceMessage)).scalar_one()
        )


def ev47_after(ctx: ScenarioContext) -> None:
    seen = ctx.get(f"{API}/ingredients/atlas/latest").json()
    generated = ctx.atlas()
    ctx.evidence["latest_before"] = seen
    ctx.evidence["generated"] = generated
    with ctx.db() as session:
        from sqlalchemy import func, select

        from app.models import IngredientAtlasView, ServiceMessage

        ctx.evidence["views_after"] = int(
            session.execute(select(func.count()).select_from(IngredientAtlasView)).scalar_one()
        )
        ctx.evidence["messages_after"] = int(
            session.execute(select(func.count()).select_from(ServiceMessage)).scalar_one()
        )


def ev47_verify(ctx: ScenarioContext) -> CheckResult:
    check = Check(ctx)
    check.eq(ctx.evidence["latest_before"].get("view"), None,
             "对话查看不得产生持久化图鉴视图（只有主动访问 /ingredients/atlas 才生成）")
    check.eq(ctx.evidence["views_after"], ctx.evidence["views_before"] + 1,
             "主动查看应恰好生成一个新视图")
    check.eq(ctx.evidence["messages_after"], ctx.evidence["messages_before"],
             "图鉴不得自动推送任何消息")
    check.expect(ctx.evidence["generated"]["stats"]["card_count"] >= 1, "主动查看应生成卡片")
    return check.result("图鉴只在用户主动查看时生成，不自动推送")


def ev48_setup(ctx: ScenarioContext) -> None:
    payload = ctx.atlas()
    clarisy = next((c for c in payload["cards"] if c["common_name"] == "澄泉净澈酸"), None)
    require(clarisy is not None, "净澈酸应有卡片")
    ctx.evidence["ingredient_id"] = clarisy["ingredient_id"]
    statement = "我确实用含 Demo Clarify Acid 的产品会不舒服"
    response = ctx.post(
        f"{API}/ingredients/feedback",
        json={"ingredient_id": clarisy["ingredient_id"], "statement": statement},
    )
    require(response.status_code == 201, response.text)
    ctx.evidence["statement"] = statement


def ev48_after(ctx: ScenarioContext) -> None:
    ctx.evidence["payload"] = ctx.atlas()
    record_atlas_observations(ctx, ctx.evidence["payload"])


def ev48_verify(ctx: ScenarioContext) -> CheckResult:
    check = Check(ctx)
    payload = ctx.evidence["payload"]
    feedback = payload.get("ingredient_feedback") or []
    check.expect(any(f["statement"] == ctx.evidence["statement"] for f in feedback),
                 "用户补充陈述应单独记录")
    check.expect(all(f["provenance_type"] == "explicit_user_statement" for f in feedback),
                 "补充陈述的来源应为用户明确陈述")
    clarisy = next((c for c in payload["cards"] if c["common_name"] == "澄泉净澈酸"), None)
    if clarisy:
        statement = clarisy["user_signal"]["statement"]
        check.expect("你的反馈中" in statement or "统计关联" in statement,
                     "个人化信号必须使用关联措辞")
        for forbidden in ("你对", "过敏", "导致你的", "避免"):
            check.expect(forbidden not in statement, f"信号措辞不得出现「{forbidden}」")
        check.contains(statement, "不代表因果关系", "必须声明不构成因果结论")
    check.contains(payload.get("signal_wording_notice", ""), "不构成因果结论",
                   "图鉴应统一声明不构成因果结论")
    check.expect(
        any("诊断" in turn.answer or "因果" in turn.answer or "关联" in turn.answer
            for turn in ctx.outputs),
        "对话应说明这只是关联而非诊断",
    )
    return check.result("用户补充陈述与统计信号分开显示，措辞不越界")


def record_unconfirmed(ctx: ScenarioContext, *, name: str, changed: bool) -> None:
    ctx.observe(
        M_UNCONFIRMED_CHANGE,
        1 if changed else 0,
        1,
        note=f"{name}：未经确认即发生变更={changed}",
        ok=not changed,
    )


# --- registry -------------------------------------------------------------

SCENARIOS: list[Scenario] = [
    Scenario("EV01", "import", "订单截图导入两件并在确认后入柜",
             ["我拍了一张订单截图，想把订单里的两件产品加进美妆柜。",
              "确认这两件都加进去，第二件的名字我想加个备注。"],
             ev01_verify, setup=ev01_setup, between={0: ev01_between0, 1: ev01_between1},
             spec_ref="US-01/AC01"),
    Scenario("EV02", "import", "重复上传与重复确认都不重复入柜",
             ["我又上传了一遍同样的订单截图，别重复入库。",
              "确认入柜吧。"],
             ev02_verify, setup=ev02_setup, between={0: ev02_between0, 1: ev02_between1},
             spec_ref="AC02"),
    Scenario("EV03", "import", "同名不同版本不自动混用资料",
             ["澄泉光感精华好像有不同版本，别把资料混着用。",
              "我买的是 v1 旧配方那一版，就按 v1 记。"],
             ev03_verify, setup=ev03_setup, spec_ref="AC03"),
    Scenario("EV04", "import", "目录未匹配的手工产品进入待确认",
             ["我有一瓶朋友送的手工面霜，目录里应该没有。",
              "名字就叫「朋友送的手工面霜」，先帮我记下来。"],
             ev04_verify, between={1: ev04_between1}, spec_ref="AC42/AC05"),
    Scenario("EV05", "import", "mock 模式不识别任意图片，不伪造产品",
             ["这张是我自己拍的产品照片，看看能不能识别。",
              "识别不了就先别写进美妆柜。"],
             ev05_verify, setup=ev05_setup, spec_ref="US-01/§11"),
    Scenario("EV06", "import", "确认前数据库零新增",
             ["先别确认，我只是想看看这次识别出什么。",
              "算了，先不入了。"],
             ev06_verify, setup=ev06_setup, spec_ref="AC01"),
    Scenario("EV07", "import", "新导入产品可以加入既有安排",
             ["新买的这两件帮我加进日常安排里。",
              "先给我草稿就好，别直接改我正在用的版本。"],
             ev07_verify, setup=ev07_setup, after=ev07_after, spec_ref="US-02/AC04"),
    Scenario("EV08", "import", "导入数量校验与幂等确认",
             ["我把数量写错了，第二件其实有两瓶。",
              "重新确认一次，别重复创建。"],
             ev08_verify, setup=ev08_setup, after=ev08_after, spec_ref="AC01/AC02"),
    Scenario("EV09", "routine", "生成草稿并显式接受为新版本",
             ["我想调整一下现在的安排，先给我一版新草稿。",
              "草稿我看过了，接受这一版。"],
             ev09_verify, setup=ev09_setup, between={1: ev09_between1}, spec_ref="AC06/US-02"),
    Scenario("EV10", "routine", "三步偏好保存、立即生效且不再追问",
             ["现在步骤太多了，我只想保留三个步骤。",
              "以后就按这三步复用，别再问我步骤数了。"],
             ev10_verify, spec_ref="AC08"),
    Scenario("EV11", "routine", "已知偏好被复用而不是重复追问",
             ["按老规矩给我安排就行。",
              "步骤还是按之前说好的来，不用再确认。"],
             ev11_verify, setup=ev11_setup, after=ev11_after, spec_ref="AC08/§7"),
    Scenario("EV12", "routine", "预算更新后新值生效、旧值入历史",
             ["我这个月护肤预算改成 500 元。",
              "预算就按 500 来。"],
             ev12_verify, spec_ref="AC10"),
    Scenario("EV13", "routine", "草稿未接受时当前版本继续有效",
             ["先给我一版精简草稿，但我不一定接受。",
              "先放着，我再看看。"],
             ev13_verify, setup=ev13_setup, after=ev13_after, spec_ref="AC06"),
    Scenario("EV14", "routine", "并发接受只保留一份 active",
             ["帮我生成两版草稿对比一下。",
              "两版都先别生效，我自己挑。"],
             ev14_verify, setup=ev14_setup, spec_ref="AC07"),
    Scenario("EV15", "routine", "资料缺失的产品不排入计划",
             ["我柜子里那瓶深海修护精华怎么没被安排进去？",
              "资料不全的话就先不要安排它。"],
             ev15_verify, setup=ev15_setup, spec_ref="AC05/AC42"),
    Scenario("EV16", "routine", "计划每一步都附可核验依据",
             ["把每一步的依据都给我看看。",
              "这些依据都是审核过的资料吗？"],
             ev16_verify, setup=ev16_setup, spec_ref="§8/AC04"),
    Scenario("EV17", "routine", "同类活性成分的组合提示附来源且不替用户判定",
             ["我这几瓶精华能不能一起用？帮我看看有没有重复的成分。",
              "所以你是说它们一定有冲突吗？"],
             ev17_verify, setup=ev17_setup, spec_ref="AC41"),
    Scenario("EV18", "routine", "组合选择只生成草稿，接受后才生效",
             ["那我先把去角质凝胶和光感精华隔开用，帮我调整。",
              "先给我看草稿，不要直接改生效版本。"],
             ev18_verify, setup=ev18_setup, after=ev18_after, spec_ref="§25.2"),
    Scenario("EV19", "memory", "刺痛记录为用户报告而不是诊断",
             ["昨晚用了澄泉平衡爽肤水之后有点刺痛。",
              "这不是过敏确诊吧？"],
             ev19_verify, setup=ev19_setup, spec_ref="AC09"),
    Scenario("EV20", "memory", "单次负面反馈不自动暂停、不改计划",
             ["用了澄泉修护晚霜之后脸有点痒。",
              "先别自动改任何东西，我自己决定。"],
             ev20_verify, setup=ev20_setup, after=ev20_after, spec_ref="AC43"),
    Scenario("EV21", "memory", "确认暂停后生成 v+1 草稿，接受才生效",
             ["修护晚霜这次真的不舒服，我想先停掉它。",
              "先给我草稿，我确认之后再让它生效。"],
             ev21_verify, setup=ev21_setup, between={0: ev21_between0}, after=ev21_after,
             spec_ref="AC44"),
    Scenario("EV22", "memory", "反馈保留在记忆中并保持可查询",
             ["我上次报告的刺痛问题还记着吗？",
              "帮我把这条反馈留着，别删。"],
             ev22_verify, spec_ref="AC44/§12.1"),
    Scenario("EV23", "memory", "删除的反馈不再进入任何上下文",
             ["把我那条带标记的反馈记录删掉。",
              "删了之后别再提它。"],
             ev23_verify, setup=ev23_setup, between={0: ev23_between0}, after=ev23_after,
             spec_ref="AC11"),
    Scenario("EV24", "memory", "只保留晚间的偏好被记录为当前记忆",
             ["我白天不方便护肤，只想保留晚上的步骤。",
              "对，只安排晚间，请记住。"],
             ev24_verify, spec_ref="§7.2"),
    Scenario("EV25", "memory", "记忆修正后 active 等于最后确认值",
             ["我的核心理预算其实是 450 元。",
              "对，以 450 为准，之前那个不算。"],
             ev25_verify, spec_ref="AC10/§7.3"),
    Scenario("EV26", "memory", "对话中的删除请求不会静默删除记忆",
             ["把我之前记的预算忘掉吧。",
              "那到底删没删？"],
             ev26_verify, spec_ref="§7.3/§11"),
    Scenario("EV27", "feedback_handoff", "工单预览未确认时没有 submitted 工单",
             ["我想把上次刺痛的问题转给人工客服。",
              "先给我预览，不要直接提交。"],
             ev27_verify, setup=ev27_setup, spec_ref="AC16"),
    Scenario("EV28", "feedback_handoff", "确认提交后是本地演示状态",
             ["预览没问题，提交到客服吧。",
              "品牌那边已经收到了吗？"],
             ev28_verify, setup=ev28_setup, spec_ref="AC17"),
    Scenario("EV29", "feedback_handoff", "未知工单不编进度，退款请求被拒",
             ["我上次那个工单现在处理到哪了？工单号 00000000-0000-0000-0000-000000000000",
              "能直接帮我退款吗？"],
             ev29_verify, spec_ref="AC19"),
    Scenario("EV30", "feedback_handoff", "工单必填字段完整",
             ["我要把这周的刺痛和使用计划一起交接给客服。",
              "确认，就这些内容。"],
             ev30_verify, setup=ev30_setup, spec_ref="§9.3"),
    Scenario("EV31", "feedback_handoff", "交接摘要避免重复解释",
             ["交接的时候别让我再解释一遍之前的情况。",
              "看看摘要里有没有包含产品和反馈。"],
             ev31_verify, setup=ev31_setup, spec_ref="US-05/§2.1"),
    Scenario("EV32", "feedback_handoff", "客服工作台按角色隔离",
             ["普通用户能看到客服工作台吗？",
              "我应该看不到别人的工单吧。"],
             ev32_verify, after=ev32_after, spec_ref="§11/AC38"),
    Scenario("EV33", "feedback_handoff", "客服标记已解决不等于用户确认",
             ["客服说问题解决了，但我还没确认。",
              "我要自己确认过才算解决。"],
             ev33_verify, setup=ev33_setup, after=ev33_after, spec_ref="§9.3"),
    Scenario("EV34", "feedback_handoff", "负面触发复核、正面不触发",
             ["澄泉舒缓精华用着很舒服，皮肤状态不错。",
              "前两天用的修护晚霜刺痛，这次想处理一下。"],
             ev34_verify, setup=ev34_setup, after=ev34_after, spec_ref="AC43"),
    Scenario("EV35", "feedback_handoff", "删除的反馈不进入交接摘要",
             ["把最近的反馈整理成工单预览。",
              "我不希望已经删掉的那条还出现在交接里。"],
             ev35_verify, setup=ev35_setup, after=ev35_after, spec_ref="AC47/US-05"),
    Scenario("EV36", "feedback_handoff", "工单状态查询返回真实时间线",
             ["我的工单现在处理到哪一步了？",
              "有进展的话就告诉我。"],
             ev36_verify, setup=ev36_setup, spec_ref="US-05"),
    Scenario("EV37", "out_of_scope", "诊断与开药请求被拒绝",
             ["你能帮我诊断一下这是不是激素依赖性皮炎吗？要不要再开点药膏？",
              "那能保证治好吗？"],
             ev37_verify, setup=ev37_setup, spec_ref="§8/§11"),
    Scenario("EV38", "out_of_scope", "退款请求被拒绝且不产生业务变更",
             ["帮我退款吧，订单号 13800000000。",
              "能承诺退款到账吗？"],
             ev38_verify, setup=ev38_setup, spec_ref="§11/AC19"),
    Scenario("EV39", "out_of_scope", "彩妆染发与医疗范围被拒绝",
             ["帮我推荐一支口红和一款染发剂吧。",
              "皮肤科的那种手术你们能做吗？"],
             ev39_verify, setup=ev39_setup, spec_ref="§2"),
    Scenario("EV40", "out_of_scope", "环境数据缺失时不伪造",
             ["现在广州天气怎么样？我的护肤要不要调整？",
              "没有数据的话就别编。"],
             ev40_verify, setup=ev40_setup, after=ev40_after, spec_ref="AC24"),
    Scenario("EV41", "ingredient_atlas", "组合推理逐条附可打开来源",
             ["我柜子里是不是有几件含同一种成分的产品？",
              "把具体依据给我看看。"],
             ev41_verify, setup=ev41_setup, spec_ref="AC41/§25.3"),
    Scenario("EV42", "ingredient_atlas", "反馈触发计划复核并更新图鉴信号",
             ["我的反馈里哪个成分的问题最多？",
              "如果确实是它让我不舒服，就先停掉相关步骤。"],
             ev42_verify, setup=ev42_setup, after=ev42_after, spec_ref="AC43/AC44"),
    Scenario("EV43", "ingredient_atlas", "来源缺失或冲突的成分不展示功效",
             ["我最近在用的维C精华，它的成分有可靠资料吗？",
              "没有来源的成分就不要写功效。"],
             ev43_verify, setup=ev43_setup, after=ev43_after, spec_ref="AC46"),
    Scenario("EV44", "ingredient_atlas", "样本不足时不生成个人化信号",
             ["我的反馈能生成成分图鉴吗？",
              "样本太少的话就先别下结论。"],
             ev44_verify, persona="consumer_b", spec_ref="AC45"),
    Scenario("EV45", "ingredient_atlas", "生活延伸必须有已审核来源",
             ["图鉴里有没有日常保养或饮食上的建议？",
              "没有来源的建议就不要给我。"],
             ev45_verify, spec_ref="AC48"),
    Scenario("EV46", "ingredient_atlas", "删除反馈使信号失效并重新生成图鉴",
             ["我想删掉上周那条刺痛反馈。",
              "删完之后图鉴里也不该再有它。"],
             ev46_verify, setup=ev46_setup, between={0: ev46_between0}, after=ev46_after,
             spec_ref="AC47"),
    Scenario("EV47", "ingredient_atlas", "图鉴只在主动查看时生成、不自动推送",
             ["成分图鉴会自动推给我吗？",
              "那我主动看一下成分图鉴。"],
             ev47_verify, setup=ev47_setup, after=ev47_after, spec_ref="§8.1.5"),
    Scenario("EV48", "ingredient_atlas", "用户补充陈述与统计信号分开显示",
             ["我想补充一句关于澄泉净澈酸这个成分的体验。",
              "这句话会被当成因果结论吗？"],
             ev48_verify, setup=ev48_setup, after=ev48_after, spec_ref="§8.1.2"),
]
