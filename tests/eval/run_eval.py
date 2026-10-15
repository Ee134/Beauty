"""Evaluation runner.

Run from the workspace root:

    .venv/bin/python -m tests.eval.run_eval
    .venv/bin/python tests/eval/run_eval.py

It builds a fresh seeded SQLite database per case (temp dir), authenticates the
demo personas and executes every scenario and security case against the real
FastAPI app in-process (TestClient) in mock model mode.  It then writes
``docs/evaluation/report.md`` (Chinese) and ``docs/evaluation/report.json``.

Exit codes:
    0  harness completed and every measured hard-zero metric is 0
    1  harness completed but a hard-zero metric was violated
    2  the harness itself could not run (setup error)
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

_EVAL_DIR = Path(__file__).resolve().parent
_ROOT = _EVAL_DIR.parents[1]
for _p in (str(_EVAL_DIR), str(_ROOT), str(_ROOT / "backend")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from comparison import (  # noqa: E402
    ATLAS_SETTINGS,
    SETTINGS,
    atlas_probe_scenario,
    provider_for,
)
from harness import (  # noqa: E402
    HARD_ZERO_METRICS,
    M_CROSS_USER_LEAK,
    M_FABRICATED_CITATION,
    METRICS,
    CaseResult,
    EvalHarness,
    EvalSession,
    run_case,
)
from metrics import aggregate, latency_stats  # noqa: E402
from report import build_payload, environment_info, write_reports  # noqa: E402
from scenarios import SCENARIOS  # noqa: E402
from security_scenarios import SECURITY_CASES  # noqa: E402

ATLAS_METRIC_KEYS = [
    "combination_advice_source_support",
    "feedback_plan_iteration_trigger",
    "atlas_card_required_fields",
    "atlas_unsourced_assertion",
    "user_signal_false_positive",
    "life_extension_source_support",
]


@dataclass
class HarnessRun:
    payload: dict[str, Any]
    scenario_results: list[CaseResult]
    security_results: list[CaseResult]
    aggregates: dict[str, Any]
    md_path: Path
    json_path: Path
    elapsed_s: float

    @property
    def hard_zero_failures(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for key in HARD_ZERO_METRICS:
            agg = self.aggregates.get(key)
            if agg is not None and agg.passed is False:
                out[key] = agg.as_dict()
        return out

    @property
    def errored(self) -> list[CaseResult]:
        return [r for r in self.scenario_results + self.security_results if r.error]


def _run_scenarios(
    harness: EvalHarness,
    cases: Iterable[Any],
    *,
    kind: str,
    lenient: bool = False,
    provider: Callable[[Any], Any] | None = None,
    setting: str = "C",
    progress: Callable[[str], None] | None = None,
    configure_factory: Callable[[Any], Callable[[Any, Any], None] | None] | None = None,
) -> list[CaseResult]:
    results: list[CaseResult] = []
    for case in cases:
        configure = configure_factory(case) if configure_factory else None
        with harness.app(f"{kind}-{case.id}", configure=configure) as session:
            result = run_case(case, session, kind=kind, lenient=lenient, provider=provider, setting=setting)
        results.append(result)
        if progress is not None:
            progress(
                f"  [{kind}] {case.id} {'PASS' if result.passed else 'FAIL'} "
                f"({result.duration_ms:.0f} ms)"
                + ("" if provider is None and setting == "C" else f" setting={setting}")
            )
    return results


def _comparison_payload(
    *,
    spec_settings: list[Any],
    results_by_setting: dict[str, list[CaseResult]],
    main_aggregates: dict[str, Any],
) -> dict[str, Any]:
    settings_payload: list[dict[str, Any]] = []
    for spec in spec_settings:
        if spec.key not in results_by_setting:
            continue
        results = results_by_setting[spec.key]
        aggs = aggregate(results, METRICS)
        settings_payload.append(
            {
                "key": spec.key,
                "label": spec.label_zh,
                "description": spec.description_zh,
                "allowed_tools": sorted(spec.allowed_tools),
                "cases": len(results),
                "passed": sum(1 for r in results if r.passed),
                "metrics": [aggs[key].as_dict() for key in METRICS if key in aggs],
            }
        )

    # honest, data-driven conclusions
    per_metric: dict[str, dict[str, tuple[float, float]]] = {}
    for spec in spec_settings:
        if spec.key not in results_by_setting:
            continue
        aggs = aggregate(results_by_setting[spec.key], METRICS)
        for key in METRICS:
            per_metric.setdefault(key, {})[spec.key] = (aggs[key].numerator, aggs[key].denominator)

    labels = "/".join(spec.key for spec in spec_settings if spec.key in results_by_setting)
    reference = "C" if "C" in results_by_setting else labels.split("/")[0]
    invariant: list[str] = []
    not_producible: list[str] = []
    differs: list[str] = []
    for key, values in per_metric.items():
        title = METRICS[key].title_zh
        pairs = {tuple(v) for v in values.values()}
        has_zero = any(den == 0 for _, den in values.values())
        if len(pairs) == 1 and not has_zero:
            invariant.append(
                f"{title}：{labels} 完全相同（{values[reference][0]:g}/{values[reference][1]:g}），"
                "由服务层与校验层保证，与模型输入设置无关。"
            )
        elif has_zero:
            zero_keys = [k for k, (_, den) in values.items() if den == 0]
            if key in {M_CROSS_USER_LEAK, M_FABRICATED_CITATION}:
                reason = (
                    "该指标由安全对抗用例测量，而本节对比按规格只复用同一组 48 个多轮场景，"
                    "因此三设置的分母都是 0；交付设置 C 的实测数值见第 3 节与第 5 节。"
                )
            else:
                reason = (
                    "在关闭结构化状态与服务工具后，该行为在编排中无法产生，属未测量而不是通过。"
                )
            not_producible.append(f"{title}：设置 {'/'.join(sorted(zero_keys))} 的分母为 0 —— {reason}")
        else:
            differs.append(f"{title}：{labels} 数值不同 {values}。")

    # conversation-driven difference: which scenarios pass only in C
    failing_by_setting: dict[str, list[str]] = {}
    for spec in spec_settings:
        results = results_by_setting.get(spec.key) or []
        failing_by_setting[spec.key] = [r.id for r in results if not r.passed]
    conversation_only: list[str] = []
    reference_failures = set(failing_by_setting.get(reference, []))
    for spec in spec_settings:
        if spec.key == reference or spec.key not in results_by_setting:
            continue
        extra = sorted(set(failing_by_setting[spec.key]) - reference_failures)
        if extra:
            conversation_only.append(
                f"设置 {spec.key} 相比 {reference} 多失败的对话驱动场景（{len(extra)} 个）："
                + "、".join(extra)
                + "。这些场景依赖计划草稿/工单/记忆写入或状态工具，而该设置在配置中关闭了它们。"
            )
        elif spec.key in results_by_setting:
            conversation_only.append(
                f"设置 {spec.key} 与 {reference} 的场景通过集合相同（未观测到对话驱动差异）。"
            )
    if not conversation_only:
        conversation_only.append("未执行多设置场景对比。")
    service_layer_note = (
        "注：上表中多数指标在 A/B/C 上完全相同，是因为它们在场景中通过服务层 API"
        "（/routines/drafts、/ingredients/atlas、/usage-events 等，不经过模型）测得，"
        "而这些不变量本来就由服务层与校验层保证。三设置真正的差异体现在下面「对话驱动场景」的通过集合上。"
    )
    conclusions = conversation_only + [service_layer_note] + invariant + not_producible + differs
    if not conclusions:
        conclusions.append("三设置在本次运行中没有可比较的差异。")
    fidelity_note = (
        "**实现保真度声明**：项目只交付一套编排（orchestrator + mock_brain）。本节 A/B/C 不是三套产品，"
        "而是**同一编排的三种可切换配置**，切换点在文档化的模型提供者工厂 "
        "`app.agent.orchestrator.get_model_provider`：A 只允许知识检索工具且不提供结构化状态/服务工具；"
        "B 在 A 之上把最近对话拼入检索 query；C 是交付配置（不做任何变换）。"
        "mock 大脑本身不消费对话历史，因此 B 的“聊天历史”是以检索输入近似实现的，指标差异不代表"
        "真实模型在有历史时的上限。固定条件：同一确定性 mock、同一目录、同一 48 个场景、同一轮次预算。"
    )
    return {
        "fidelity_note": fidelity_note,
        "settings": settings_payload,
        "failing_by_setting": failing_by_setting,
        "conversation_driven": conversation_only,
        "conclusions": conclusions,
    }


def _atlas_comparison_payload(
    *,
    probes: dict[str, CaseResult],
) -> dict[str, Any]:
    settings_payload: list[dict[str, Any]] = []
    per_metric: dict[str, dict[str, tuple[float, float]]] = {}
    for setting in ATLAS_SETTINGS:
        result = probes[setting.key]
        aggs = aggregate([result], ATLAS_METRIC_KEYS)
        settings_payload.append(
            {
                "key": setting.key,
                "label": setting.label_zh,
                "configure": setting.configure.__name__ if setting.configure else "无（交付种子数据）",
                "probe_details": [result.detail],
                "metrics": [aggs[key].as_dict() for key in ATLAS_METRIC_KEYS],
            }
        )
        for key in ATLAS_METRIC_KEYS:
            per_metric.setdefault(key, {})[setting.key] = (aggs[key].numerator, aggs[key].denominator)

    def _fmt(pair: tuple[float, float]) -> str:
        return "N/A" if pair[1] == 0 else f"{pair[0]:g}/{pair[1]:g}"

    conclusions: list[str] = []
    for key in ATLAS_METRIC_KEYS:
        title = METRICS[key].title_zh
        values = per_metric[key]
        a, b, c = values["A"], values["B"], values["C"]
        line = (
            f"{title}：A（无反馈积累）={_fmt(a)}，B（无成分来源）={_fmt(b)}，"
            f"C（交付配置）={_fmt(c)}。"
        )
        if a[1] == 0:
            line += " 设置 A 没有个人化信号，该项无法测量。"
        if b != c:
            line += " 缺少已审核成分来源（B）会直接改变该指标。"
        conclusions.append(line)
    fidelity_note = (
        "**构造声明**：三个图鉴设置不是模拟数据，而是由同一份真实种子数据派生的三种数据库配置："
        "A 删除全部 UsageEvent/信号/复核问题（仅保留产品资料）；B 保留反馈但把 IngredientProfile 引用的"
        "成分来源置为 revoked；C 不做任何改动。三者运行同一探针（同一用户、同一柜内产品、同一份成分资料"
        "与同一轮次预算）。"
    )
    return {"fidelity_note": fidelity_note, "settings": settings_payload, "conclusions": conclusions}


def run_harness(
    *,
    root: Path | str | None = None,
    docs_dir: Path | str | None = None,
    command: str = ".venv/bin/python -m tests.eval.run_eval",
    run_comparison: bool = True,
    scenario_ids: list[str] | None = None,
    security_ids: list[str] | None = None,
    progress: Callable[[str], None] | None = None,
    write: bool = True,
) -> HarnessRun:
    started = time.perf_counter()
    scratch_root = Path(root) if root else Path(tempfile.mkdtemp(prefix="beautycare-eval-"))
    scratch_root.mkdir(parents=True, exist_ok=True)
    harness = EvalHarness(scratch_root)
    docs = Path(docs_dir) if docs_dir else _ROOT / "docs" / "evaluation"

    def log(message: str) -> None:
        if progress is not None:
            progress(message)

    scenarios = [s for s in SCENARIOS if not scenario_ids or s.id in scenario_ids]
    security = [c for c in SECURITY_CASES if not security_ids or c.id in security_ids]

    log(f"临时数据目录：{scratch_root}")
    log(f"多轮场景：{len(scenarios)} 个；安全用例：{len(security)} 个")

    settings_holder: dict[str, Any] = {}

    scenario_results: list[CaseResult] = []
    for scenario in scenarios:
        with harness.app(f"scenario-{scenario.id}") as session:
            settings_holder["settings"] = session.settings
            result = run_case(scenario, session, kind="scenario")
        scenario_results.append(result)
        log(f"  [scenario] {scenario.id} {'PASS' if result.passed else 'FAIL'} ({result.duration_ms:.0f} ms)")

    security_results: list[CaseResult] = []
    for case in security:
        with harness.app(f"security-{case.id}") as session:
            settings_holder["settings"] = session.settings
            result = run_case(case, session, kind="security")
        security_results.append(result)
        log(f"  [security] {case.id} {'PASS' if result.passed else 'FAIL'} ({result.duration_ms:.0f} ms)")

    if "settings" not in settings_holder:
        raise RuntimeError("没有执行任何用例，无法取得设置")
    settings = settings_holder["settings"]

    all_results = scenario_results + security_results
    aggregates = aggregate(all_results, METRICS)
    latency = latency_stats(scenario_results + security_results)

    results_by_setting: dict[str, list[CaseResult]] = {"C": list(scenario_results)}
    if run_comparison:
        log("§14 三设置对比：A / B …")
        for spec in SETTINGS:
            if spec.key == "C":
                continue
            log(f"  设置 {spec.key}：{spec.label_zh}")
            results_by_setting[spec.key] = _run_scenarios(
                harness,
                scenarios,
                kind="scenario",
                lenient=True,
                provider=provider_for(spec),
                setting=spec.key,
                progress=log,
            )

    comparison = _comparison_payload(
        spec_settings=list(SETTINGS),
        results_by_setting=results_by_setting,
        main_aggregates=aggregates,
    )

    atlas_probes: dict[str, CaseResult] = {}
    if run_comparison:
        log("§25.3 图鉴三设置对比：A / B / C …")
        for setting in ATLAS_SETTINGS:
            probe = atlas_probe_scenario(setting)
            with harness.app(f"atlas-{setting.key}", configure=setting.configure) as session:
                result = run_case(probe, session, kind="atlas_abc", setting=setting.key)
            atlas_probes[setting.key] = result
            log(f"  [atlas] {setting.key} {'PASS' if result.passed else 'FAIL'} ({result.duration_ms:.0f} ms)")
        atlas_comparison = _atlas_comparison_payload(probes=atlas_probes)
    else:
        atlas_comparison = {
            "fidelity_note": "本次运行使用 --skip-comparison，未执行 §25.3 对比。",
            "settings": [],
            "conclusions": ["未执行对比运行。"],
        }

    unverified = _unverified_items(aggregates, comparison, atlas_comparison, run_comparison)
    findings = _collect_findings(all_results, atlas_probes, atlas_comparison)

    env = environment_info(settings, command, scratch_root)
    payload = build_payload(
        command=command,
        env=env,
        scenario_results=scenario_results,
        security_results=security_results,
        aggregates=aggregates,
        latency=latency,
        comparison=comparison,
        atlas_comparison=atlas_comparison,
        unverified=unverified,
        findings=findings,
    )

    md_path = docs / "report.md"
    json_path = docs / "report.json"
    if write:
        md_path, json_path = write_reports(docs, payload)

    elapsed = time.perf_counter() - started
    return HarnessRun(
        payload=payload,
        scenario_results=scenario_results,
        security_results=security_results,
        aggregates=aggregates,
        md_path=md_path,
        json_path=json_path,
        elapsed_s=elapsed,
    )


def _unverified_items(
    aggregates: dict[str, Any],
    comparison: dict[str, Any],
    atlas_comparison: dict[str, Any],
    run_comparison: bool,
) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    unmeasured = [
        METRICS[key].title_zh
        for key, agg in aggregates.items()
        if agg.denominator == 0
    ]
    if unmeasured:
        items.append(
            {
                "item": "本次运行分母为 0 的指标：" + "、".join(sorted(unmeasured)),
                "reason": "该场景集合没有产生可计数的机会（例如没有卡片或没有应触发的反馈）。",
                "impact": "指标显示为 N/A，未被当作通过。",
            }
        )
    items.append(
        {
            "item": "真实模型（MODEL_MODE=live）下的表现",
            "reason": "本环境没有模型凭据，规格要求未配置密钥时明示不可用；harness 固定使用确定性 mock。",
            "impact": "所有指标只代表 mock 编排，不能外推到真实模型质量。",
        }
    )
    items.append(
        {
            "item": "用户信号误报率的人工评估部分",
            "reason": "规格 §14 定义该指标含人工评估；harness 只能机器判定「关联事件数 < ATLAS_MIN_EVENTS 却出现在信号中」。",
            "impact": "报告的是可机器验证的子集，人工标注部分未做。",
        }
    )
    items.append(
        {
            "item": "任务解决率、相关性人工评分、通知采纳率/关闭率",
            "reason": "这些指标需要真实用户或人工评分，超出本 harness 的可观测范围。",
            "impact": "未测量，报告不作任何声明。",
        }
    )
    items.append(
        {
            "item": "Web Push 真实送达/已读、Playwright 端到端 UI 流程",
            "reason": "没有推送凭据与浏览器环境；tests/e2e 的 Playwright 流程属于既有 E2E 套件，不在本 harness 内。",
            "impact": "仅验证编排契约与 API 层，不声明真实送达。",
        }
    )
    if not run_comparison:
        items.append(
            {
                "item": "§14 与 §25.3 的 A/B/C 对比",
                "reason": "本次以 --skip-comparison 运行。",
                "impact": "仅报告交付设置 C 的指标。",
            }
        )
    else:
        items.append(
            {
                "item": "A/B 设置下明细能力（计划草稿、工单、记忆写入）",
                "reason": "这两套配置按定义关闭了结构化状态与服务工具，因此相关指标分母为 0。",
                "impact": "A/B 的这些指标为 N/A；这是配置事实，不是实现缺陷。",
            }
        )
        items.append(
            {
                "item": "设置 B 的“聊天历史”对真实模型的增益",
                "reason": "mock 大脑不消费对话历史，B 只能用检索 query 近似历史影响。",
                "impact": "B 与 A 的差异被低估，不能作为真实模型的上限。",
            }
        )
    atlas_text = " ".join(atlas_comparison.get("conclusions", []))
    if "个人化信号" in atlas_text and "无法测量" in atlas_text:
        items.append(
            {
                "item": "§25.3 设置 A 的图鉴卡片类指标",
                "reason": "删除积累反馈后没有个人化信号，图鉴不生成卡片。",
                "impact": "设置 A 的卡片完整率/无来源断言率/误报率分母为 0，显示为 N/A。",
            }
        )
    return items


def _collect_findings(
    results: list[CaseResult],
    atlas_probes: dict[str, CaseResult],
    atlas_comparison: dict[str, Any],
) -> list[str]:
    findings: list[str] = []
    for result in results + list(atlas_probes.values()):
        for finding in result.findings:
            if finding not in findings:
                findings.append(finding)
    # measured, reproducible observations about the shipped code, taken from the
    # §25.3 setting B (feedback present, ingredient sources revoked)
    b_settings = [s for s in atlas_comparison.get("settings", []) if s["key"] == "B"]
    if b_settings:
        b_metrics = {m["key"]: m for m in b_settings[0]["metrics"]}
        unsourced = b_metrics.get("atlas_unsourced_assertion", {})
        completeness = b_metrics.get("atlas_card_required_fields", {})
        if unsourced.get("numerator", 0) > 0:
            findings.append(
                "图鉴在缺少可解析的已审核成分来源时，卡片仍标记 data_status=approved，并保留非 unknown 的"
                f"致敏等级（无引用）：实测无来源断言 {unsourced['numerator']:g}/{unsourced['denominator']:g}。"
                "这是 app/services/atlas.py 的行为（**交付前已修复**：无可解析引用时降级为 insufficient，" \
                "回归测试 tests/unit/test_atlas_and_expiry.py::"
                "test_approved_ingredient_without_resolvable_sources_degrades_to_insufficient）；" \
                "本 harness 仍只通过 DB 配置（把 IngredientProfile "
                "引用的来源置为 revoked）测得。"
            )
        if completeness.get("denominator", 0) and completeness.get("passed") is False:
            findings.append(
                "同一配置下图鉴卡片必填项完整率为 "
                f"{completeness['numerator']:g}/{completeness['denominator']:g}：来源不可解析时应降级为 "
                "insufficient 并显示「暂无充分信息」，而不是返回 approved 但内容为空的卡片。"
            )
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="BeautyCare evaluation harness")
    parser.add_argument("--root", default=None, help="临时数据目录（默认自动创建）")
    parser.add_argument("--docs", default=None, help="报告输出目录（默认 docs/evaluation）")
    parser.add_argument("--skip-comparison", action="store_true", help="跳过 §14/§25.3 对比")
    parser.add_argument("--quiet", action="store_true", help="只输出最终摘要")
    parser.add_argument(
        "--keep",
        action="store_true",
        help="保留临时数据库（默认保留，便于复现失败用例）",
    )
    args = parser.parse_args(argv)

    command = ".venv/bin/python -m tests.eval.run_eval" + (
        " " + " ".join(argv or []) if argv else ""
    )

    def progress(message: str) -> None:
        if not args.quiet:
            print(message, flush=True)

    try:
        run = run_harness(
            root=args.root,
            docs_dir=args.docs,
            command=command,
            run_comparison=not args.skip_comparison,
            progress=progress,
        )
    except Exception:  # noqa: BLE001
        print("评测 harness 运行失败：", file=sys.stderr)
        traceback.print_exc()
        return 2

    payload = run.payload
    print("")
    print("=" * 78)
    print(f"用例：场景 {len(run.scenario_results)} 个，安全 {len(run.security_results)} 个")
    print(
        f"延迟：P50 {payload['latency']['p50_ms']} ms / P95 {payload['latency']['p95_ms']} ms"
        f"（{payload['latency']['turns']} 轮）"
    )
    print("-" * 78)
    print(f"{'指标':<32}{'分子':>8}{'分母':>8}{'比率':>10}  目标/结果")
    for metric in payload["metrics"]:
        rate = "N/A" if metric["rate"] is None else f"{metric['rate'] * 100:.2f}%"
        target = "0(硬零)" if metric["hard_zero"] else f"{metric['target'] * 100:.0f}%"
        verdict = "未测量" if metric["passed"] is None else ("通过" if metric["passed"] else "未通过")
        print(
            f"{metric['title_zh']:<32}{metric['numerator']:>8g}{metric['denominator']:>8g}"
            f"{rate:>10}  {target} {verdict}"
        )
    print("-" * 78)
    failing = [r for r in run.scenario_results + run.security_results if not r.passed]
    print(f"失败用例：{len(failing)}")
    for result in failing:
        print(f"  - {result.id} {result.title}: {result.detail[:160]}")
    print(f"报告：{run.md_path}")
    print(f"      {run.json_path}")
    print(f"耗时：{run.elapsed_s:.1f} s")
    print("=" * 78)

    if run.hard_zero_failures:
        print("硬零指标未通过：", ", ".join(run.hard_zero_failures))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
