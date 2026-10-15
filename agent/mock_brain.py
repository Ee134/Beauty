"""Deterministic mock brain.

This is the `mock` model implementation. It is intentionally rule based so the
whole orchestration (tools -> validation -> draft writes -> narration) can be
tested without keys and without pretending to be a real model.

It never invents facts: everything it says comes from the tool results handed to
it by the orchestrator.
"""

from __future__ import annotations

import re
from typing import Any

CN_NUMBERS = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}

INTENT_PATTERNS: list[tuple[str, list[str]]] = [
    ("unsupported", [r"诊断", r"开药", r"处方", r"激素药膏", r"医美手术", r"确诊", r"吃什么药", r"保证治好", r"退款到账", r"帮我退款"]),
    ("ingredient_atlas", [r"成分图鉴", r"图鉴", r"哪些成分", r"什么成分", r"成分", r"让我不适", r"适合我", r"致敏", r"叠加", r"叠用", r"能不能一起用", r"组合"]),
    ("import", [r"截图", r"上传", r"导入", r"订单", r"照片", r"图片", r"拍了一单"]),
    ("travel", [r"行程", r"出差", r"旅行", r"去北京", r"去上海", r"出行", r"飞", r"目的地"]),
    ("environment", [r"天气", r"湿度", r"紫外线", r"环境", r"城市", r"下雨", r"温度"]),
    ("notification", [r"通知", r"提醒", r"免打扰", r"推送", r"稍后", r"关闭此类", r"订阅"]),
    ("brand_feedback", [r"反馈给品牌", r"告诉品牌", r"品牌方", r"建议品牌", r"缺货", r"希望增加", r"功能建议"]),
    ("service", [r"工单", r"客服", r"人工", r"上次那个问题", r"进度", r"交接", r"怎么样了", r"处理到哪"]),
    ("memory", [r"预算", r"记住", r"不要保存", r"忘掉", r"忘记", r"删除.*(反馈|记录|偏好)", r"修改.*偏好", r"我不想再保存"]),
    ("routine", [r"计划", r"流程", r"步骤", r"安排", r"顺序", r"早晚", r"接受", r"复用", r"精简", r"太多", r"三个", r"3 步", r"3步", r"换一套"]),
    ("feedback", [r"刺痛", r"不舒服", r"发红", r"泛红", r"痒", r"脱皮", r"爆痘", r"闷痘", r"灼热", r"过敏", r"刺激", r"用了.*(之后|后)", r"用完", r"反馈", r"很舒服", r"挺好", r"不错", r"改善了"]),
]


def classify_intent(message: str) -> str:
    text = message or ""
    for intent, patterns in INTENT_PATTERNS:
        for pattern in patterns:
            if re.search(pattern, text):
                return intent
    return "general"


def _parse_number(text: str, pattern: str) -> int | None:
    match = re.search(pattern, text)
    if not match:
        return None
    token = match.group(1)
    if token.isdigit():
        return int(token)
    return CN_NUMBERS.get(token)


def plan(payload: dict[str, Any]) -> dict[str, Any]:
    message = payload.get("message", "")
    intent = classify_intent(message)
    tools: list[dict[str, Any]] = []
    questions: list[dict[str, Any]] = []
    writes: list[dict[str, Any]] = []

    if intent == "routine":
        tools = [
            {"name": "get_user_context", "args": {}},
            {"name": "list_owned_products", "args": {}},
            {"name": "get_active_routine", "args": {}},
        ]
        writes = [{"tool": "draft_routine", "args": {"trigger": "chat_request"}}]
    elif intent == "feedback":
        tools = [
            {"name": "get_user_context", "args": {}},
            {"name": "list_owned_products", "args": {}},
            {"name": "get_active_routine", "args": {}},
        ]
        writes = [{"tool": "record_usage_event", "args": {"reported_text": message}}]
    elif intent == "import":
        tools = [{"name": "get_user_context", "args": {}}]
    elif intent == "service":
        ticket_ref = _ticket_reference(message)
        tools = [
            {"name": "get_user_context", "args": {}},
            {"name": "get_service_status", "args": {"ticket_id": ticket_ref} if ticket_ref else {}},
        ]
    elif intent == "environment":
        tools = [
            {"name": "get_environment", "args": {}},
            {"name": "get_user_activities", "args": {}},
        ]
    elif intent == "travel":
        tools = [
            {"name": "get_user_activities", "args": {}},
            {"name": "list_owned_products", "args": {}},
            {"name": "get_environment", "args": {}},
        ]
    elif intent == "notification":
        tools = [{"name": "get_notification_status", "args": {}}]
    elif intent == "memory":
        tools = [{"name": "get_user_context", "args": {}}]
    elif intent == "ingredient_atlas":
        tools = [
            {"name": "get_user_context", "args": {}},
            {"name": "build_ingredient_atlas", "args": {}},
        ]
    else:
        tools = [{"name": "get_user_context", "args": {}}]

    return {
        "intent": intent,
        "tool_requests": tools[:4],
        "write_requests": writes,
        "questions": questions,
        "reasoning_summary": f"mock 规则分类：{intent}",
    }


TICKET_PATTERNS = (
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
    r"LOCAL-DEMO-[0-9A-Fa-f]{8}",
)


def _ticket_reference(message: str) -> str | None:
    for pattern in TICKET_PATTERNS:
        match = re.search(pattern, message or "")
        if match:
            return match.group(0)
    return None


def _citation_ids(results: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for key in ("citations", "ingredient_citation_ids"):
        for citation in results.get(key, []) or []:
            cid = citation.get("citation_id") if isinstance(citation, dict) else citation
            if cid:
                ids.append(cid)
    for product in (results.get("active_plan") or {}).get("steps", []) or []:
        ids.extend([c for c in product.get("citation_ids", []) if c])
    return sorted(set(ids))


def compose(payload: dict[str, Any]) -> dict[str, Any]:
    message: str = payload.get("message", "")
    intent: str = payload.get("intent") or classify_intent(message)
    tools: dict[str, Any] = payload.get("tool_results") or {}
    writes: dict[str, Any] = payload.get("write_results") or {}
    source_message_id = payload.get("source_message_id")
    answers: list[str] = []
    questions: list[dict[str, Any]] = []
    proposals: list[dict[str, Any]] = []
    uncertainties: list[str] = []
    citation_ids: list[str] = []
    write_requests: list[dict[str, Any]] = []

    context = tools.get("get_user_context") or {}
    cabinet = context.get("cabinet") or []
    active = (tools.get("get_active_routine") or {}).get("active_plan")

    if intent == "routine":
        draft = writes.get("routine_draft") or {}
        if draft.get("error"):
            answers.append(
                f"我没有生成计划草稿：{draft.get('error')}。你可以先在美妆柜补充产品资料，或继续手动安排。"
            )
        elif draft.get("plan_id"):
            pending = draft.get("pending_count", 0)
            steps = draft.get("step_count", 0)
            answers.append(
                f"已为你生成计划草稿（v{draft.get('version')}，共 {steps} 个步骤），"
                "草稿在你确认前不会生效。"
            )
            if draft.get("diff_summary"):
                answers.append(f"相对当前版本的差异：{draft['diff_summary']}")
            if draft.get("combination_notes"):
                answers.append(
                    "组合提示（每条都有已审核来源，系统不替你判定能否叠用）："
                    + "；".join(n.get("text", "") for n in draft["combination_notes"][:3])
                )
                for note in draft["combination_notes"]:
                    citation_ids.extend(note.get("citation_ids") or [])
            if pending:
                answers.append(
                    f"另有 {pending} 件产品资料不足或有冲突，已进入待确认列表，本版本没有为它们安排步骤。"
                )
            for question in draft.get("questions") or []:
                questions.append(question)
            current_max_steps = _preference_value(context, "routine.max_steps")
            if current_max_steps is None:
                wanted = _parse_number(message, r"([0-9一两二三四五六七八九十]+)\s*(?:个)?\s*步")
                if wanted:
                    proposals.append(
                        {
                            "kind": "explicit_preference",
                            "key": "routine.max_steps",
                            "value": wanted,
                            "provenance_type": "explicit_user_statement",
                            "source_message_id": source_message_id,
                            "requires_confirmation": False,
                        }
                    )
            answers.append("请查看草稿卡片中的步骤与依据，确认后再接受。")
        else:
            answers.append("我暂时无法生成计划草稿，请稍后重试或手动安排。")
    elif intent == "feedback":
        event = writes.get("usage_event") or {}
        if event.get("error"):
            answers.append(f"这条反馈我还没能记录：{event['error']}")
        else:
            answers.append(
                "已把这条记录为「你报告的体验」，不是诊断结论。（事件 ID："
                f"{str(event.get('event_id'))[:8]}…）"
            )
            if event.get("event_type") == "negative":
                answers.append(
                    "我没有建议你继续使用来验证；如果情况严重或持续，请使用工单入口联系人工或寻求专业帮助。"
                )
            if event.get("review_prompt"):
                answers.append(f"复核询问：{event['review_prompt']['question']}")
            if event.get("questions"):
                questions.extend(event["questions"])
            answers.append("这条反馈已加入记忆，后续生成计划时会作为已知反馈纳入。")
    elif intent == "import":
        answers.append(
            "请在「美妆柜 → 导入」上传截图或照片。识别结果会先给你确认，确认之前不会写入美妆柜。"
        )
        if (payload.get("settings_mode") or "mock") == "mock":
            answers.append("当前是 mock 模式：只有内置演示截图样本能被识别，其他图片需要手动添加。")
    elif intent == "service":
        status = tools.get("get_service_status") or {}
        tickets = status.get("tickets")
        if tickets is not None:
            if tickets:
                answers.append("你当前有 " f"{len(tickets)} 张工单，最近一张状态：{tickets[0]['status']}。")
                answers.append("状态来自本地演示工作台，不代表品牌方已收到。")
            else:
                answers.append("我没有查到你的工单记录。如需新建，请先预览交接摘要再确认提交。")
        elif status.get("found") is False:
            answers.append("没有找到这张工单，我不会推测它的进度，也不会承诺处理结果。")
        elif status.get("found"):
            timeline = status.get("timeline") or []
            answers.append(
                f"工单 {str(status['ticket_id'])[:8]}… 当前状态：{status['status']}，"
                f"已记录 {len(timeline)} 条处理记录。"
                f"下一步：{status.get('next_action') or '等待处理'}。"
            )
            if timeline:
                answers.append(
                    "最近的处理记录：" + "；".join(item["action"] for item in timeline[-3:])
                )
            answers.append("状态来自本地演示工作台，不代表品牌方已收到；解决与否以你的确认为准。")
    elif intent == "environment":
        env = tools.get("get_environment") or {}
        if not env.get("available"):
            answers.append("当前没有可用的环境数据（可能未设置城市或数据不可用），我不会用演示数据伪装成实时数据。")
        else:
            current = env.get("current") or {}
            metrics = current.get("metrics") or {}
            answers.append(
                f"{env.get('city_name')} 当前 {metrics.get('temperature_c', '未知')}°C、"
                f"相对湿度 {metrics.get('relative_humidity', '未知')}%、紫外线指数 {metrics.get('uv_index', '未知')}"
                f"（数据模式：{env.get('mode')}，时效：{current.get('freshness')}）。"
            )
            if env.get("missing_fields"):
                answers.append("缺失字段：" + "、".join(env["missing_fields"]) + "（未知不会被填成 0）。")
            answers.append("天气变化本身不能证明肤况变化，所以不会据此给出确定的产品结论。")
    elif intent == "travel":
        activities = (tools.get("get_user_activities") or {}).get("activities") or []
        trips = [a for a in activities if a["activity_type"] == "trip" and a["status"] == "planned"]
        if not trips:
            answers.append("你还没有确认过的行程。添加行程后，我会在出发前基于目的地预报生成出行清单。")
        else:
            trip = trips[0]
            answers.append(
                f"已找到你确认的行程「{trip['title']}」（目的地 {trip.get('destination_city_name') or '未指定'}）。"
                "出行清单与计划调整会先给草稿；预报未覆盖的日期显示未知，不伪造天气。"
            )
        answers.append("产品携带建议不等于两件产品可以互换。")
    elif intent == "notification":
        status = tools.get("get_notification_status") or {}
        preference = status.get("preferences") or {}
        channels = status.get("channels") or {}
        answers.append(
            "当前通知设置：服务类型 "
            + ("、".join(preference.get("service_types") or []) or "（未授权任何服务）")
            + f"；渠道 {'、'.join(preference.get('channels') or []) or '（无）'}；"
            f"每天最多 {preference.get('daily_cap')} 条；免打扰 {preference.get('quiet_hours_start')}–{preference.get('quiet_hours_end')}。"
        )
        answers.append(
            "Web Push：" + str((channels.get("web_push") or {}).get("notice"))
            + " 原生 App 推送为 P1，本 MVP 未交付原生客户端。"
        )
    elif intent == "memory":
        preferences = context.get("preferences") or []
        if preferences:
            answers.append(
                "当前生效的记忆："
                + "；".join(f"{p.get('label') or p['key']} = {p.get('value')}" for p in preferences[:5])
            )
        else:
            answers.append("目前没有保存下来的偏好或事实。")
        wanted = _parse_number(message, r"([0-9一两二三四五六七八九十]+)\s*(?:个)?\s*步")
        if wanted:
            proposals.append(
                {
                    "kind": "explicit_preference",
                    "key": "routine.max_steps",
                    "value": wanted,
                    "provenance_type": "explicit_user_statement",
                    "source_message_id": source_message_id,
                    "requires_confirmation": False,
                }
            )
        budget = re.search(r"预算[^\d]{0,6}(\d+)", message)
        if budget:
            proposals.append(
                {
                    "kind": "explicit_preference",
                    "key": "routine.budget_monthly",
                    "value": float(budget.group(1)),
                    "provenance_type": "explicit_user_statement",
                    "source_message_id": source_message_id,
                    "requires_confirmation": False,
                }
            )
        if re.search(r"忘掉|忘记|不要保存|不再保存|删除", message):
            answers.append(
                "如果要删除记录，请到「记忆」页选择具体条目确认删除；我不会在对话里自动删除。"
                "删除后相关原文与派生内容都会失效，重启后仍然保持。"
            )
    elif intent == "ingredient_atlas":
        atlas = tools.get("build_ingredient_atlas") or {}
        cards = atlas.get("cards") or []
        below = atlas.get("below_threshold") or []
        answers.append(
            f"已按你自己的反馈生成成分图鉴草稿：{len(cards)} 张卡片，"
            f"{len(below)} 个成分样本不足。每条功效与致敏性都来自已审核来源；"
            "没有来源的成分显示“暂无充分信息”。"
        )
        if below:
            answers.append(
                "样本不足的成分："
                + "、".join(f"{b['common_name']}（{b['positive_count'] + b['negative_count']}/{b['min_events']}）" for b in below[:5])
            )
        answers.append(
            "反馈与成分只是统计关联，不代表因果关系；图鉴不会自动推送，需要你主动查看。"
        )
        for card in cards:
            for effect in card.get("known_effects", []):
                citation_ids.append((effect.get("citation") or {}).get("citation_id"))
            for note in (card.get("irritancy") or {}).get("notes", []):
                citation_ids.append((note.get("citation") or {}).get("citation_id"))
            for extension in card.get("life_extensions", []):
                citation_ids.append((extension.get("citation") or {}).get("citation_id"))
        intent_out = "ingredient_atlas"
    elif intent == "brand_feedback":
        answers.append(
            "我可以把你的需求整理成内部草稿（资料缺口 / 服务缺口 / 显式产品需求 / 功能建议），"
            "但不会自动外发；真实分享需要你单独同意分享范围，并由品牌运营审核。"
        )
        write_requests.append({"tool": "draft_brand_feedback", "args": {"category": "explicit_product_request", "text": message}})
    elif intent == "unsupported":
        answers.append(
            "这超出了 BeautyCare 的服务范围：我不做诊断、不开药、不承诺治疗效果，也不处理退款。"
            "我可以帮你记录使用体验、暂停相关步骤，并生成本地演示工单转人工。"
        )
    else:
        if cabinet:
            answers.append(
                f"你的美妆柜里有 {len(cabinet)} 件产品"
                + (f"，当前计划 v{active['version']} 生效中。" if active else "，目前还没有生效中的计划。")
            )
        else:
            answers.append("你的美妆柜还是空的。可以先手动添加产品，或上传订单截图导入。")
        answers.append("你可以问：怎么安排这些产品、某件产品用了不舒服、成分图鉴、客服进度、天气与出行提醒。")

    # memory proposals must carry the real source message
    already = set(payload.get("applied_preference_keys") or [])
    proposals = [
        p for p in proposals if p.get("source_message_id") and p.get("key") not in already
    ]

    return {
        "answer": "\n".join(answers),
        "questions": questions[:2],
        "citation_ids": sorted({c for c in citation_ids if c}),
        "memory_proposals": proposals,
        "write_requests": write_requests,
        "uncertainties": uncertainties,
    }


def _preference_value(context: dict[str, Any], key: str) -> Any:
    for pref in context.get("preferences") or []:
        if pref.get("key") == key:
            return pref.get("value")
    return None


def extract_import(payload: dict[str, Any]) -> dict[str, Any]:
    """Mock vision never pretends to read an arbitrary image."""
    return {
        "candidates": [],
        "raw_text": None,
        "notes": (
            "mock 模式不识别任意图片：只有内置演示截图样本可以被识别，"
            "其它图片请使用手动添加。"
        ),
    }
