"""Reference aggregator: the metrics of ops/metrics.yaml, computed from a JSON-lines log (AI-21).

    python -m core.ops.metrics run.jsonl      # counters, and count / p50 / p95 per histogram

OPS-10's collector does this in production; this module applies exactly the same rules, so
DevOps can check the mapping and tests can check that a simulated incident crosses an alert's
threshold. It reads metadata only.
"""

import argparse
import json
import sys
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict

METRICS_PATH = Path(__file__).resolve().parents[2] / "ops" / "metrics.yaml"
Labels = tuple[tuple[str, str], ...]


class MetricSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    type: Literal["counter", "histogram"]
    help: str
    logger: str
    record: str
    where: dict[str, Any] = {}
    value: str | None = None
    labels: dict[str, str] = {}
    explode: str | None = None
    empty_as: str | None = None
    buckets: list[float] = []


class MetricsFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: int
    metrics: list[MetricSpec]


@cache
def load_metrics(path: Path = METRICS_PATH) -> MetricsFile:
    return MetricsFile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


@dataclass
class Metrics:
    counters: dict[str, dict[Labels, float]] = field(default_factory=lambda: defaultdict(dict))
    histograms: dict[str, dict[Labels, list[float]]] = field(
        default_factory=lambda: defaultdict(dict)
    )

    def total(self, name: str, **match: str) -> float:
        """Sum of a counter over the series whose labels include `match`."""
        return sum(
            value
            for labels, value in self.counters.get(name, {}).items()
            if all(dict(labels).get(k) == v for k, v in match.items())
        )

    def values(self, name: str, **match: str) -> list[float]:
        return [
            v
            for labels, values in self.histograms.get(name, {}).items()
            if all(dict(labels).get(k) == str(val) for k, val in match.items())
            for v in values
        ]


def aggregate(lines: Iterable[Mapping[str, Any]], spec: MetricsFile | None = None) -> Metrics:
    spec = spec or load_metrics()
    out = Metrics()
    for line in lines:
        record = line.get("record")
        if not isinstance(record, Mapping):
            continue
        for metric in spec.metrics:
            if line.get("logger") != metric.logger or not _matches(record, metric.where):
                continue
            if metric.value is not None and record.get(metric.value) is None:
                continue
            value = 1.0 if metric.value is None else float(record[metric.value])
            for labels in _label_sets(record, metric):
                if metric.type == "counter":
                    series = out.counters[metric.name]
                    series[labels] = series.get(labels, 0.0) + value
                else:
                    out.histograms[metric.name].setdefault(labels, []).append(value)
    return out


def _matches(record: Mapping[str, Any], where: Mapping[str, Any]) -> bool:
    return all(record.get(k) == v for k, v in where.items())


def _label_sets(record: Mapping[str, Any], metric: MetricSpec) -> list[Labels]:
    def label(name: str, source: str) -> tuple[str, str]:
        value = record.get(source)
        return name, "" if value is None else str(value)

    base = [label(n, s) for n, s in metric.labels.items() if s != metric.explode]
    if metric.explode is None:
        return [tuple(sorted(base))]
    items = list(record.get(metric.explode) or []) or [metric.empty_as or ""]
    exploded = next(n for n, s in metric.labels.items() if s == metric.explode)
    return [tuple(sorted([*base, (exploded, str(item))])) for item in items]


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    lines = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if raw.startswith("{"):
            try:
                lines.append(json.loads(raw))
            except json.JSONDecodeError:
                continue
    return lines


def quantile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return float("nan")
    index = min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))
    return ordered[index]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m core.ops.metrics")
    parser.add_argument("log", type=Path, help="a JSON-lines log from core/ops/logs.py")
    args = parser.parse_args(argv)
    metrics = aggregate(read_jsonl(args.log))
    for name, series in sorted(metrics.counters.items()):
        for labels, value in sorted(series.items()):
            print(f"{name}{{{_fmt(labels)}}} {value:g}")
    for name, observed in sorted(metrics.histograms.items()):
        for labels, values in sorted(observed.items()):
            print(
                f"{name}{{{_fmt(labels)}}} count={len(values)} "
                f"p50={quantile(values, 0.5):g} p95={quantile(values, 0.95):g}"
            )
    return 0


def _fmt(labels: Labels) -> str:
    return ",".join(f'{k}="{v}"' for k, v in labels)


if __name__ == "__main__":
    sys.exit(main())
