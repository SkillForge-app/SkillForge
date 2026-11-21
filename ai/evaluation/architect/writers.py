"""AI-13 and AI-14 in the Architect evaluation: `run --set seed --writers`.

After each valid spec the reference writer (AI-13) and the trigger writer (AI-14) run. The
report gets their counts, the AI-13 verdict and a human spot-check list; the generated files go
to the run folder (references/<request>/<file>.md, descriptions.json), never into Git.

AI-13 verdict (done-when "no uncited claims in reference files"): all 10 seed specs valid, a
file for every reference, 0 uncited claims. The weakly-supported rate is reported with no gate
yet (one is set after the first live run). A fake run never counts.
"""

import json
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.agents import ArchitectResult
from core.agents.writers import Descriptions, ReferenceFile, describe, summarise, write_references
from core.agents.writers.support import SUPPORT_THRESHOLD
from evaluation.architect.data import SEED_SET_SIZE, ArchitectItem
from evaluation.common import Outcome

SPOT_CHECK_SIZE = 10
SPOT_CHECK_SEED = 20261119

Result = Outcome[ArchitectItem, ArchitectResult]


@dataclass(frozen=True)
class Written:
    files: list[ReferenceFile] = field(default_factory=list)
    descriptions: Descriptions | None = None


async def write_all(outcomes: Sequence[Result]) -> dict[str, Written]:
    """Both writers for every valid spec, one request at a time."""
    out = {}
    for o in outcomes:
        r = o.result
        if r is None or not r.ok or r.spec is None:
            continue
        files = await write_references(r.spec, r.passages, r.evidence)
        out[o.item.id] = Written(files, await describe(r.spec))
    return out


def writer_metrics(written: Mapping[str, Written]) -> dict[str, Any]:
    files = [f for w in written.values() for f in w.files]
    s = summarise(files)
    descriptions = [w.descriptions for w in written.values() if w.descriptions is not None]
    return {
        "specs_written": len(written),
        "reference_files": s.files,
        "reference_files_ok": s.files_ok,
        "claims": s.claims,
        "uncited_claims": s.uncited,
        "dropped_claims": sum(s.dropped.values()),
        "dropped_by_reason": s.dropped,
        "weakly_supported": s.weak,
        "weakly_supported_rate": s.weak_rate,
        "support_threshold": SUPPORT_THRESHOLD,
        "descriptions": sum(len(d.by_target) for d in descriptions),
        "description_fallbacks": sum(len(d.fallback) for d in descriptions),
    }


def references_verdict(metrics: dict[str, Any], *, live: bool) -> dict[str, Any]:
    """AI-13: all seed specs valid, every reference has a file, 0 uncited claims."""
    w = metrics["writers"]
    reasons = []
    if metrics["n"] != SEED_SET_SIZE or metrics["valid"] != metrics["n"]:
        reasons.append(f"{metrics['valid']} of {metrics['n']} seed specs are valid (need all 10)")
    if w["reference_files_ok"] != w["reference_files"]:
        missing = w["reference_files"] - w["reference_files_ok"]
        reasons.append(f"{missing} references have no file")
    if w["uncited_claims"]:
        reasons.append(f"{w['uncited_claims']} uncited claims (must be 0)")
    return {
        "passed": not reasons,
        "counts": live,
        "reasons": reasons,
        "weakly_supported_rate": w["weakly_supported_rate"],  # reported, not gated yet
    }


def spot_check(
    outcomes: Sequence[Result], written: Mapping[str, Written], *, n: int = SPOT_CHECK_SIZE
) -> list[dict[str, Any]]:
    """N random kept claims (fixed seed), each with the full text of the chunks it cites."""
    by_item = {o.item.id: o for o in outcomes}
    rows = []
    for item_id in sorted(written):
        r = by_item[item_id].result
        texts = {p.chunk_id: p.text for p in (r.passages if r else ())}
        for f in written[item_id].files:
            for c in f.claims:
                rows.append(
                    {
                        "request": item_id,
                        "file": f.path,
                        "claim": c.text,
                        "support": c.support,
                        "weak": c.weak,
                        "cited": [{"chunk_id": i, "text": texts.get(i, "")} for i in c.chunk_ids],
                    }
                )
    return random.Random(SPOT_CHECK_SEED).sample(rows, min(n, len(rows)))


def save_outputs(written: Mapping[str, Written], run_dir: Path) -> None:
    """Every reference file and the descriptions, for review by hand (the run folder only)."""
    descriptions: dict[str, Any] = {}
    for item_id, w in written.items():
        safe = item_id.replace(":", "_").replace("/", "_")
        for f in w.files:
            if f.markdown:
                path = run_dir / "references" / safe / Path(f.path).name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f.markdown, encoding="utf-8")
        if w.descriptions is not None:
            descriptions[item_id] = {
                "by_target": w.descriptions.by_target,
                "fallback": list(w.descriptions.fallback),
            }
    (run_dir / "descriptions.json").write_text(
        json.dumps(descriptions, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def render(
    references: dict[str, Any] | None, metrics: dict[str, Any], spot: Sequence[Any]
) -> list[str]:
    lines = []
    if references is not None:
        verdict = "PASSED" if references["passed"] else "FAILED"
        if not references["counts"]:
            verdict += " (fake mode: does NOT count for AI-13)"
        lines += [f"**AI-13 (no uncited claims in the seed reference files): {verdict}**"]
        lines += [f"- {r}" for r in references["reasons"]] + [""]
    w = metrics.get("writers")
    if w:
        rate = w["weakly_supported_rate"]
        lines += [
            "| reference files (ok) | claims | uncited | dropped | weakly supported | "
            "descriptions (fallbacks) |",
            "|---|---|---|---|---|---|",
            f"| {w['reference_files']} ({w['reference_files_ok']}) | {w['claims']} | "
            f"{w['uncited_claims']} | {w['dropped_claims']} {w['dropped_by_reason'] or ''} | "
            f"{w['weakly_supported']} ({'n/a' if rate is None else f'{rate:.0%}'}, below "
            f"{w['support_threshold']}) | {w['descriptions']} ({w['description_fallbacks']}) |",
            "",
        ]
    if spot:
        lines += [
            f"## Human spot-check: {len(spot)} random claims (seed {SPOT_CHECK_SEED})",
            "",
            "For each claim: does the cited text support it? Tick it, or note what is wrong.",
            "",
        ]
        for n, row in enumerate(spot, 1):
            weak = " **(weakly supported)**" if row["weak"] else ""
            lines += [
                f"{n}. `{row['request']}` {row['file']}, support {row['support']}{weak}",
                f"   - Claim: {row['claim']}",
            ]
            lines += [f"   - Cited `{c['chunk_id']}`: {c['text']}" for c in row["cited"]]
            lines += ["   - [ ] supported", ""]
    return lines


__all__ = [
    "Written",
    "references_verdict",
    "render",
    "save_outputs",
    "spot_check",
    "write_all",
    "writer_metrics",
]
