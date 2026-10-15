"""Metric aggregation for the evaluation harness.

Every metric is reported as an explicit numerator/denominator pair produced by
real observations from the harness.  Nothing is estimated or inferred from the
model's own opinion.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

_EVAL_DIR = Path(__file__).resolve().parent
if str(_EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(_EVAL_DIR))

from harness import METRICS, CaseResult, Observation, percentile  # noqa: E402


@dataclass
class MetricAggregate:
    key: str
    numerator: float = 0.0
    denominator: float = 0.0
    failing: list[dict[str, Any]] = field(default_factory=list)

    @property
    def rate(self) -> float | None:
        if not self.denominator:
            return None
        return self.numerator / self.denominator

    @property
    def meta(self):
        return METRICS[self.key]

    @property
    def measured(self) -> bool:
        return self.denominator > 0

    @property
    def passed(self) -> bool | None:
        if not self.measured:
            return None
        rate = float(self.rate)
        meta = self.meta
        if meta.hard_zero:
            return self.numerator == 0
        return rate >= meta.target

    def as_dict(self) -> dict[str, Any]:
        meta = self.meta
        rate = self.rate
        return {
            "key": self.key,
            "title_zh": meta.title_zh,
            "definition_zh": meta.definition_zh,
            "spec_ref": meta.spec_ref,
            "numerator": self.numerator,
            "denominator": self.denominator,
            "rate": rate,
            "rate_pct": None if rate is None else round(rate * 100, 2),
            "target": meta.target,
            "higher_is_better": meta.higher_is_better,
            "hard_zero": meta.hard_zero,
            "measured": self.measured,
            "passed": self.passed,
            "failing_count": len(self.failing),
            "failing": self.failing,
        }


def aggregate(
    results: Iterable[CaseResult],
    metrics: Iterable[str] | None = None,
) -> dict[str, MetricAggregate]:
    wanted = set(metrics) if metrics else set(METRICS)
    aggregates: dict[str, MetricAggregate] = {key: MetricAggregate(key) for key in wanted}
    for result in results:
        for obs in result.observations:
            if obs.metric not in aggregates:
                continue
            agg = aggregates[obs.metric]
            agg.numerator += obs.numerator
            agg.denominator += obs.denominator
            if obs.ok is False:
                agg.failing.append(
                    {
                        "case_id": obs.case_id or result.id,
                        "case_title": result.title,
                        "numerator": obs.numerator,
                        "denominator": obs.denominator,
                        "note": obs.note,
                    }
                )
    return aggregates


def latency_stats(results: Iterable[CaseResult]) -> dict[str, Any]:
    values: list[float] = []
    per_case: list[dict[str, Any]] = []
    for result in results:
        for turn in result.outputs:
            values.append(turn.latency_ms)
            per_case.append(
                {
                    "case_id": result.id,
                    "turn": turn.index,
                    "latency_ms": round(turn.latency_ms, 3),
                    "status_code": turn.status_code,
                }
            )
    return {
        "turns": len(values),
        "p50_ms": None if not values else round(float(percentile(values, 0.50)), 3),
        "p95_ms": None if not values else round(float(percentile(values, 0.95)), 3),
        "mean_ms": None if not values else round(sum(values) / len(values), 3),
        "max_ms": None if not values else round(max(values), 3),
        "min_ms": None if not values else round(min(values), 3),
        "per_turn": per_case,
    }


def observation_dump(observations: Iterable[Observation]) -> list[dict[str, Any]]:
    return [o.as_dict() for o in observations]
