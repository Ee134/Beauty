"""Report writer: docs/evaluation/report.md (Chinese) + report.json."""

from __future__ import annotations

import hashlib
import json
import platform
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

_EVAL_DIR = Path(__file__).resolve().parent
_ROOT = _EVAL_DIR.parents[1]
if str(_EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(_EVAL_DIR))

from harness import HARD_ZERO_METRICS, METRICS, CaseResult  # noqa: E402
from metrics import MetricAggregate  # noqa: E402


def backend_source_hash() -> str:
    """Commit-less content hash of backend/app source files."""
    root = _ROOT / "backend" / "app"
    digest = hashlib.sha256()
    if not root.exists():
        return "unavailable"
    for path in sorted(root.rglob("*.py")):
        digest.update(str(path.relative_to(root)).encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def environment_info(settings: Any, command: str, root: Path) -> dict[str, Any]:
    return {
        "command": command,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "model_mode": settings.model_mode,
        "model_provider": settings.model_provider,
        "weather_mode": settings.weather_mode,
        "vision_mode": settings.vision_mode,
        "notification_mode": settings.notification_mode,
        "auth_mode": settings.auth_mode,
        "atlas_min_events": settings.atlas_min_events,
        "citation_strict": settings.citation_strict,
        "scheduler_enabled": settings.scheduler_enabled,
        "backend_source_hash": backend_source_hash(),
        "scratch_root": str(root),
        "note": "所有数字均由本次真实运行产生；mock 模型模式，确定性 fixtures。",
    }


def _fmt_rate(value: float | None) -> str:
    return "N/A" if value is None else f"{value * 100:.2f}%"


def _verdict(agg: MetricAggregate) -> str:
    passed = agg.passed
    if passed is None:
        return "未测量"
    return "通过" if passed else "未通过"


def _metric_row(agg: MetricAggregate) -> str:
    meta = METRICS[agg.key]
    target = "0（硬零）" if meta.hard_zero else f"{meta.target * 100:.0f}%"
    return (
        f"| {meta.title_zh} | {agg.numerator:g} | {agg.denominator:g} | "
        f"{_fmt_rate(agg.rate)} | {target} | {_verdict(agg)} | {meta.spec_ref} |"
    )


def build_payload(
    *,
    command: str,
    env: dict[str, Any],
    scenario_results: list[CaseResult],
    security_results: list[CaseResult],
    aggregates: dict[str, MetricAggregate],
    latency: dict[str, Any],
    comparison: dict[str, Any],
    atlas_comparison: dict[str, Any],
    unverified: list[dict[str, str]],
    findings: list[str],
) -> dict[str, Any]:
    metric_table = [aggregates[key].as_dict() for key in METRICS if key in aggregates]
    hard_zero = {
        METRICS[key].title_zh: {
            "key": key,
            "value": aggregates[key].numerator if key in aggregates else None,
            "denominator": aggregates[key].denominator if key in aggregates else None,
            "passed": aggregates[key].passed if key in aggregates else None,
        }
        for key in HARD_ZERO_METRICS
    }
    failing_scenarios = [r for r in scenario_results if not r.passed]
    failing_security = [r for r in security_results if not r.passed]
    return {
        "environment": env,
        "command": command,
        "scenario_count": len(scenario_results),
        "scenario_ids": [r.id for r in scenario_results],
        "security_count": len(security_results),
        "hard_zero": hard_zero,
        "metrics": metric_table,
        "latency": latency,
        "failures": {
            "scenarios": [r.as_dict(include_raw=True) for r in failing_scenarios],
            "security": [r.as_dict(include_raw=True) for r in failing_security],
            "errored": [
                r.as_dict(include_raw=True)
                for r in scenario_results + security_results
                if r.error
            ],
        },
        "all_scenarios": [r.as_dict() for r in scenario_results],
        "all_security": [r.as_dict() for r in security_results],
        "comparison_abc": comparison,
        "comparison_atlas_abc": atlas_comparison,
        "unverified": unverified,
        "findings": findings,
    }


def write_markdown(payload: dict[str, Any], path: Path) -> None:
    env = payload["environment"]
    lines: list[str] = []
    lines.append("# BeautyCare 评估报告")
    lines.append("")
    lines.append(
        "本报告由 `tests/eval/run_eval.py` 在真实进程内运行 FastAPI TestClient 生成；"
        "所有数字都是本次运行的实测值，未测量项在文末「未验证 / 无法测量」中列出。"
    )
    lines.append("")
    lines.append("## 1. 运行命令与环境")
    lines.append("")
    lines.append("| 项目 | 值 |")
    lines.append("|---|---|")
    lines.append(f"| 运行命令 | `{payload['command']}` |")
    lines.append(f"| 生成时间 (UTC) | {env['generated_at']} |")
    lines.append(f"| Python | {env['python']} |")
    lines.append(f"| 平台 | {env['platform']} |")
    lines.append(f"| MODEL_MODE | {env['model_mode']}（provider={env['model_provider']}） |")
    lines.append(f"| WEATHER_MODE | {env['weather_mode']} |")
    lines.append(f"| VISION_MODE | {env['vision_mode']} |")
    lines.append(f"| NOTIFICATION_MODE | {env['notification_mode']} |")
    lines.append(f"| AUTH_MODE | {env['auth_mode']} |")
    lines.append(f"| ATLAS_MIN_EVENTS | {env['atlas_min_events']} |")
    lines.append(f"| 后端源码内容哈希 | `{env['backend_source_hash']}`（backend/app/**/*.py，非 git commit） |")
    lines.append(f"| 临时数据目录 | `{env['scratch_root']}` |")
    lines.append("")
    lines.append("## 2. 结果摘要")
    lines.append("")
    lines.append(f"- 多轮场景：{payload['scenario_count']} 个，全部执行（ID：{payload['scenario_ids'][0]}…{payload['scenario_ids'][-1]}）")
    lines.append(f"- 安全对抗用例：{payload['security_count']} 个，全部执行")
    lines.append(f"- 会话轮次延迟：P50 = {payload['latency']['p50_ms']} ms，P95 = {payload['latency']['p95_ms']} ms（共 {payload['latency']['turns']} 轮）")
    lines.append("")
    lines.append("### 2.1 硬零指标（工程发布门槛）")
    lines.append("")
    lines.append("| 指标 | 违规数 | 机会数 | 是否通过 |")
    lines.append("|---|---|---|---|")
    for title, data in payload["hard_zero"].items():
        verdict = "通过" if data["passed"] is True else ("未通过" if data["passed"] is False else "未测量")
        lines.append(f"| {title} | {data['value']} | {data['denominator']} | {verdict} |")
    lines.append("")
    lines.append("## 3. 指标表（分子 / 分母 / 比率 / 目标）")
    lines.append("")
    lines.append("| 指标 | 分子 | 分母 | 比率 | 目标 | 结果 | 规格 |")
    lines.append("|---|---|---|---|---|---|---|")
    for metric in payload["metrics"]:
        target = "0（硬零）" if metric["hard_zero"] else f"{metric['target'] * 100:.0f}%"
        if metric["passed"] is None:
            verdict = "未测量"
        else:
            verdict = "通过" if metric["passed"] else "未通过"
        lines.append(
            f"| {metric['title_zh']} | {metric['numerator']:g} | {metric['denominator']:g} | "
            f"{_fmt_rate(metric['rate'])} | {target} | {verdict} | {metric['spec_ref']} |"
        )
    lines.append("")
    lines.append("### 3.1 指标定义")
    lines.append("")
    for metric in payload["metrics"]:
        lines.append(f"- **{metric['title_zh']}**（`{metric['key']}`）：{metric['definition_zh']}")
    lines.append("")
    lines.append("## 4. 失败用例（原文输出）")
    lines.append("")
    failures = payload["failures"]
    if not failures["scenarios"] and not failures["security"]:
        lines.append("本次运行没有失败用例。")
    else:
        for result in failures["scenarios"] + failures["security"]:
            lines.append(f"### {result['id']} — {result['title']}")
            lines.append("")
            lines.append("```text")
            lines.append(result.get("raw_output", result["detail"]))
            lines.append("```")
            lines.append("")
    if failures["errored"]:
        lines.append("### 4.1 抛出异常的用例（不得静默跳过）")
        lines.append("")
        for result in failures["errored"]:
            lines.append(f"#### {result['id']} — {result['title']}")
            lines.append("")
            lines.append("```text")
            lines.append(result.get("error") or "")
            lines.append("```")
            lines.append("")
    lines.append("## 5. 安全对抗用例结果")
    lines.append("")
    lines.append("| 用例 | 类别 | 说明 | 结果 |")
    lines.append("|---|---|---|---|")
    for result in payload["all_security"]:
        lines.append(
            f"| {result['id']} | {result['group']} | {result['title']} | "
            f"{'通过' if result['passed'] else '未通过'} |"
        )
    lines.append("")
    lines.append("## 6. §14 三设置对比（A / B / C）")
    lines.append("")
    cc = payload["comparison_abc"]
    lines.append(cc["fidelity_note"])
    lines.append("")
    for spec in cc["settings"]:
        lines.append(f"### {spec['label']}")
        lines.append("")
        lines.append(spec["description"])
        lines.append("")
        lines.append("| 指标 | 分子 | 分母 | 比率 | 结果 |")
        lines.append("|---|---|---|---|---|")
        for metric in spec["metrics"]:
            lines.append(
                f"| {metric['title_zh']} | {metric['numerator']:g} | {metric['denominator']:g} | "
                f"{_fmt_rate(metric['rate'])} | "
                f"{'未测量' if metric['passed'] is None else ('通过' if metric['passed'] else '未通过')} |"
            )
        lines.append("")
    failing = cc.get("failing_by_setting") or {}
    if failing:
        lines.append("#### 各设置失败场景（对话驱动差异）")
        lines.append("")
        lines.append("| 设置 | 失败场景数 | 失败场景 ID |")
        lines.append("|---|---|---|")
        for key, ids in failing.items():
            lines.append(f"| {key} | {len(ids)} | {'、'.join(ids) if ids else '无'} |")
        lines.append("")
    lines.append("#### 三设置差异结论")
    lines.append("")
    for note in cc["conclusions"]:
        lines.append(f"- {note}")
    lines.append("")
    lines.append("## 7. §25.3 图鉴三设置对比")
    lines.append("")
    ac = payload["comparison_atlas_abc"]
    lines.append(ac["fidelity_note"])
    lines.append("")
    for spec in ac["settings"]:
        lines.append(f"### {spec['label']}")
        lines.append("")
        lines.append(f"构造方式：`{spec['configure']}`")
        lines.append("")
        lines.append("| 指标 | 分子 | 分母 | 比率 | 结果 |")
        lines.append("|---|---|---|---|---|")
        for metric in spec["metrics"]:
            lines.append(
                f"| {metric['title_zh']} | {metric['numerator']:g} | {metric['denominator']:g} | "
                f"{_fmt_rate(metric['rate'])} | "
                f"{'未测量' if metric['passed'] is None else ('通过' if metric['passed'] else '未通过')} |"
            )
        lines.append("")
        for detail in spec.get("probe_details", []):
            lines.append(f"- {detail}")
        lines.append("")
    lines.append("#### 图鉴三设置差异结论")
    lines.append("")
    for note in ac["conclusions"]:
        lines.append(f"- {note}")
    lines.append("")
    lines.append("## 8. 未验证 / 无法测量")
    lines.append("")
    if not payload["unverified"]:
        lines.append("无。")
    else:
        lines.append("| 项目 | 原因 | 影响 |")
        lines.append("|---|---|---|")
        for item in payload["unverified"]:
            lines.append(f"| {item['item']} | {item['reason']} | {item['impact']} |")
    lines.append("")
    lines.append("## 9. 评测期间发现的问题（含修复状态）")
    lines.append("")
    lines.append(
        "harness 只做测量，不修改后端。以下是评测中由用例发现的真实产品缺陷；"
        "括号内标注它们在本次交付前是否已修复，以及对应的回归测试。"
        "「已修复」表示修复后的代码重新跑过本 harness，指标已反映修复结果。"
    )
    lines.append("")
    if not payload["findings"]:
        lines.append("无。")
    else:
        for finding in payload["findings"]:
            lines.append(f"- {finding}")
    lines.append("")
    lines.append("## 10. 延迟明细")
    lines.append("")
    lines.append(
        f"P50 = {payload['latency']['p50_ms']} ms，P95 = {payload['latency']['p95_ms']} ms，"
        f"均值 = {payload['latency']['mean_ms']} ms，最大 = {payload['latency']['max_ms']} ms，"
        f"轮次数 = {payload['latency']['turns']}。"
    )
    lines.append("")
    lines.append(
        "> 说明：模型为确定性 mock，延迟只反映本机编排与 SQLite 开销，不代表真实模型或线上性能。"
    )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_reports(docs_dir: Path, payload: dict[str, Any]) -> tuple[Path, Path]:
    docs_dir.mkdir(parents=True, exist_ok=True)
    json_path = docs_dir / "report.json"
    md_path = docs_dir / "report.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    write_markdown(payload, md_path)
    return md_path, json_path
