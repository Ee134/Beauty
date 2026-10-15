"""Programmatic run of the evaluation harness as a pytest test.

Marked ``slow``.  It fails loudly when a scenario raises instead of being
verified, and it blocks the five hard-zero metrics:

* 图鉴无来源断言率 (atlas unsourced assertion rate)
* 应忘记内容重新出现率 (forgotten content reappearance rate)
* 跨用户泄漏 (cross-user leakage)
* 虚构引用被接受 (fabricated citation acceptance)
* 未经确认的业务变更 (unconfirmed business change)

It also asserts that every scenario and every security case actually executed.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_EVAL_DIR = Path(__file__).resolve().parent
_ROOT = _EVAL_DIR.parents[1]
for _p in (str(_EVAL_DIR), str(_ROOT), str(_ROOT / "backend")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from harness import HARD_ZERO_METRICS, METRICS  # noqa: E402
from run_eval import run_harness  # noqa: E402
from scenarios import SCENARIOS  # noqa: E402
from security_scenarios import SECURITY_CASES  # noqa: E402

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def harness_run(tmp_path_factory):
    root = tmp_path_factory.mktemp("eval-harness")
    return run_harness(
        root=root,
        docs_dir=root / "docs",
        command=".venv/bin/python -m pytest tests/eval -q (tests/eval/test_eval_harness.py)",
        run_comparison=True,
        write=True,
    )


def test_every_scenario_executed_without_skip(harness_run):
    expected = [scenario.id for scenario in SCENARIOS]
    assert len(expected) == 48, "规格要求恰好 48 个多轮场景"
    got = [result.id for result in harness_run.scenario_results]
    assert got == expected, f"场景执行不完整：缺少 {set(expected) - set(got)}，多余 {set(got) - set(expected)}"
    for result in harness_run.scenario_results:
        assert result.passed, f"{result.id} 未通过：{result.detail}\n{result.raw_dump()}"
    # every scenario must have executed exactly as many turns as declared
    for result, scenario in zip(harness_run.scenario_results, SCENARIOS):
        assert len(result.outputs) == len(scenario.turns), (
            f"{result.id} 轮次数量不一致：声明 {len(scenario.turns)}，执行 {len(result.outputs)}"
        )
        assert result.detail, f"{result.id} 缺少校验说明"


def test_every_security_case_executed_without_skip(harness_run):
    expected = [case.id for case in SECURITY_CASES]
    assert len(expected) >= 20, "规格要求至少 20 个安全用例"
    got = [result.id for result in harness_run.security_results]
    assert got == expected, f"安全用例执行不完整：缺少 {set(expected) - set(got)}"
    for result in harness_run.security_results:
        assert result.passed, f"{result.id} 未通过：{result.detail}\n{result.raw_dump()}"


def test_no_case_raised_instead_of_being_verified(harness_run):
    errored = harness_run.errored
    assert not errored, "有用例抛出异常而非给出校验结果：\n" + "\n".join(
        f"{r.id}: {r.error}" for r in errored
    )


def test_hard_zero_metrics_are_zero(harness_run):
    for key in HARD_ZERO_METRICS:
        aggregate = harness_run.aggregates[key]
        assert aggregate.denominator > 0, (
            f"{METRICS[key].title_zh} 没有可计数的机会（分母 0）：硬零指标会变成空洞的通过"
        )
        assert aggregate.numerator == 0, (
            f"{METRICS[key].title_zh} 必须为 0，实测 {aggregate.numerator:g}/"
            f"{aggregate.denominator:g}；失败用例：{aggregate.failing}"
        )
        assert aggregate.passed is True


def test_all_metrics_have_explicit_numerator_and_denominator(harness_run):
    for metric in harness_run.payload["metrics"]:
        assert "numerator" in metric and "denominator" in metric
        assert metric["denominator"] >= metric["numerator"] >= 0
        if metric["denominator"] > 0:
            assert metric["passed"], f"{metric['title_zh']} 未达标：{metric}"


def test_latency_recorded_for_every_turn(harness_run):
    latency = harness_run.payload["latency"]
    assert latency["turns"] >= 48, "至少每个场景记录一轮延迟"
    assert latency["p50_ms"] is not None and latency["p95_ms"] is not None
    assert latency["p95_ms"] >= latency["p50_ms"]


def test_reports_contain_no_unverified_claims(harness_run):
    payload = harness_run.payload
    assert payload["unverified"], "必须显式列出未验证 / 无法测量的项目"
    assert payload["environment"]["model_mode"] == "mock"
    assert payload["command"]
    assert payload["comparison_abc"]["settings"], "必须包含 §14 三设置对比"
    assert payload["comparison_atlas_abc"]["settings"], "必须包含 §25.3 图鉴三设置对比"
    assert harness_run.md_path.exists() and harness_run.json_path.exists()


def test_report_writer_renders_failing_cases_verbatim(tmp_path):
    """The failure path of the report writer is exercised, not just the happy path."""
    from harness import CaseResult
    from report import build_payload, write_reports

    fake = CaseResult(
        kind="scenario",
        id="EV99",
        group="self_test",
        title="模拟失败用例",
        persona="consumer_a",
        turns=["这是一条用于验证失败渲染的输入"],
        passed=False,
        detail="断言失败：示例",
        observations=[],
        outputs=[],
        error="RuntimeError: boom\n<traceback>",
        duration_ms=1.0,
    )
    payload = build_payload(
        command="pytest self-test",
        env={
            "generated_at": "1970-01-01T00:00:00+00:00",
            "python": "3",
            "platform": "test",
            "model_mode": "mock",
            "model_provider": "mock",
            "weather_mode": "mock",
            "vision_mode": "mock",
            "notification_mode": "in_app",
            "auth_mode": "demo",
            "atlas_min_events": 3,
            "citation_strict": True,
            "scheduler_enabled": False,
            "backend_source_hash": "test",
            "scratch_root": str(tmp_path),
        },
        scenario_results=[fake],
        security_results=[],
        aggregates={},
        latency={"p50_ms": 1.0, "p95_ms": 2.0, "mean_ms": 1.5, "max_ms": 2.0, "min_ms": 1.0, "turns": 1},
        comparison={"fidelity_note": "n", "settings": [], "conclusions": []},
        atlas_comparison={"fidelity_note": "n", "settings": [], "conclusions": []},
        unverified=[{"item": "i", "reason": "r", "impact": "x"}],
        findings=["示例发现"],
    )
    md_path, json_path = write_reports(tmp_path, payload)
    text = md_path.read_text(encoding="utf-8")
    assert "EV99" in text and "模拟失败用例" in text
    assert "断言失败：示例" in text
    assert "RuntimeError: boom" in text
    assert "示例发现" in text
    assert "未验证 / 无法测量" in text
    assert json_path.exists()
