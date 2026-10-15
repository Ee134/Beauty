"""Deterministic extraction of explicit first-person preferences.

This runs before draft writes so a statement like “只想三步” is already in effect
when the plan draft is generated. It is the same source used by the mock brain,
so mock and live modes share the contract. Casual or vague statements are not
extracted here; they stay as proposals requiring confirmation.
"""

from __future__ import annotations

import re
from typing import Any

CN_DIGITS = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
DIGIT_TO_CN = {v: k for k, v in CN_DIGITS.items()}
CN_NUMERALS = {1: ["一", "1"], 2: ["二", "两", "2"], 3: ["三", "3"], 4: ["四", "4"]}


def numeral_forms(value: int) -> list[str]:
    forms = {str(value)}
    forms.update(CN_NUMERALS.get(value, []))
    for cn, number in CN_DIGITS.items():
        if number == value:
            forms.add(cn)
    return sorted(forms)


def _to_int(token: str) -> int | None:
    if token.isdigit():
        return int(token)
    return CN_DIGITS.get(token)


def extract_proposals(message: str) -> list[dict[str, Any]]:
    text = message or ""
    proposals: list[dict[str, Any]] = []

    steps = re.search(
        r"(?:只|只要|只需要|想要|保留|留|精简到|精简成|变成|改成|限制在)?\s*"
        r"([0-9一两二三四五六七八九十]+)\s*个?\s*步",
        text,
    )
    if steps:
        value = _to_int(steps.group(1))
        if value and 1 <= value <= 10:
            proposals.append(
                {
                    "kind": "explicit_preference",
                    "key": "routine.max_steps",
                    "value": value,
                    "provenance_type": "explicit_user_statement",
                    "requires_confirmation": False,
                }
            )

    # A bare money amount is not a budget statement: "帮我退款 1380 元" must not
    # become a recurring spending preference.
    budget = re.search(r"预算[^\d]{0,8}(\d+(?:\.\d+)?)", text)
    if budget is None and re.search(r"(每个月|每月|一个月|控制在|花费|开销|月度)", text):
        budget = re.search(r"(\d+(?:\.\d+)?)\s*(?:元|块)(?:以内|左右|的预算)?", text)
    if budget:
        proposals.append(
            {
                "kind": "explicit_preference",
                "key": "routine.budget_monthly",
                "value": float(budget.group(1)),
                "provenance_type": "explicit_user_statement",
                "requires_confirmation": False,
            }
        )

    if re.search(r"(只|仅).{0,4}(晚上|晚间|夜里)", text):
        proposals.append(
            {
                "kind": "explicit_preference",
                "key": "routine.preferred_period",
                "value": "evening",
                "provenance_type": "explicit_user_statement",
                "requires_confirmation": False,
            }
        )
    elif re.search(r"(只|仅).{0,4}(早上|晨间|白天)", text):
        proposals.append(
            {
                "kind": "explicit_preference",
                "key": "routine.preferred_period",
                "value": "morning",
                "provenance_type": "explicit_user_statement",
                "requires_confirmation": False,
            }
        )

    avoid = re.search(r"(?:不要|别|避免|不想).{0,4}(?:含|用|使用)\s*([A-Za-z0-9\u4e00-\u9fff\- ]{2,30}?)(?:的|成分|产品)", text)
    if avoid and re.search(r"(我的反馈|我不|我确定|我不想|请记住|帮我记住)", text):
        proposals.append(
            {
                "kind": "explicit_preference",
                "key": "routine.avoid_ingredients",
                "value": [avoid.group(1).strip()],
                "provenance_type": "explicit_user_statement",
                "requires_confirmation": True,
            }
        )

    if re.search(r"(步骤太多|太复杂|想简单|精简)", text):
        proposals.append(
            {
                "kind": "explicit_preference",
                "key": "routine.prefer_simple",
                "value": True,
                "provenance_type": "explicit_user_statement",
                "requires_confirmation": False,
            }
        )
    return proposals


def supported_number_in_text(text: str, value: int) -> bool:
    """True when the message actually contains the number (digit or Chinese form)."""
    return any(form in (text or "") for form in numeral_forms(value))
