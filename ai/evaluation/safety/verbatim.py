"""child_safety items (AI-06): SimpleSafetyTests rows used verbatim, stored by reference only.

    python -m evaluation.safety verbatim --live

Nobody writes or rewords these. From SimpleSafetyTests' "Child Abuse" rows (CC BY 2.0, the local
download under _data/safety-datasets), it keeps only the rows where the requester intends harm,
not help-seeking victims: the independent classifier (Llama Guard 4, as in `precheck`) must say
`unsafe`, which it doesn't for someone asking for help. In row-id order, the first ones fill
the open child_safety slots (r-31 .. r-36, then sd-16) as `origin: dataset-verbatim` items with
`dataset` and `dataset_ref` and no text; the text is read from the download at evaluation time.

Never prints or logs any row's text: only ids, verdicts and counts. The verdicts go to
runs/child-safety-selection.jsonl (ignored by Git), without text.
"""

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.llm import BudgetExceeded, LLMError, skill_run
from evaluation.safety.data import (
    SAFETY_DIR,
    VERBATIM,
    VERBATIM_CATEGORY,
    VERBATIM_DATASET,
    datasets_dir,
    load_file,
)
from evaluation.safety.generate import answering_models
from evaluation.safety.precheck import GUARD_PROMPT, TextGateway, parse_reply
from evaluation.safety.review import append_item
from evaluation.safety.seeds import load_seeds
from evaluation.safety.slots import Slot, plan_slots

SELECTION_PATH = SAFETY_DIR / "runs" / "child-safety-selection.jsonl"
BUDGET_USD = 0.05


@dataclass
class VerbatimRun:
    rows: int = 0  # child-abuse rows considered
    unsafe: int = 0
    safe: int = 0
    skipped: list[str] = field(default_factory=list)  # ids only
    filled: list[tuple[str, str]] = field(default_factory=list)  # (slot id, dataset_ref)
    classifier: str | None = None
    cost_usd: float = 0.0


def open_verbatim_slots() -> list[Slot]:
    slots = [s for split in ("redteam", "dev") for s in plan_slots(split) if s.verbatim]
    filled = {r.id for split in ("redteam", "dev") for r in load_file(split).requests}
    return [s for s in slots if s.id not in filled]


def used_refs() -> set[str]:
    return {
        str(r.dataset_ref)
        for split in ("redteam", "dev")
        for r in load_file(split).requests
        if r.origin == VERBATIM
    }


async def fill_verbatim(
    gateway: TextGateway,
    *,
    folder: Path | None = None,
    selection_path: Path = SELECTION_PATH,
    budget_usd: float = BUDGET_USD,
) -> VerbatimRun:
    folder = folder or datasets_dir()
    rows = sorted(
        (s for s in load_seeds(folder) if s.dataset == VERBATIM_DATASET),
        key=lambda s: s.ref,
    )
    rows = [s for s in rows if s.category == VERBATIM_CATEGORY]
    if not rows:
        raise FileNotFoundError(
            f"no {VERBATIM_DATASET} child-abuse rows under {folder / VERBATIM_DATASET}: "
            "download the dataset first (LABELLING.md)"
        )
    run = VerbatimRun(rows=len(rows))
    slots = open_verbatim_slots()
    taken = used_refs()
    verdicts: list[dict[str, Any]] = []
    with skill_run("child-safety-verbatim", budget_usd=budget_usd) as budget:
        for row in rows:
            if not slots:
                break
            if row.ref in taken:
                continue
            try:
                with answering_models() as models:
                    reply = await gateway.complete_text(GUARD_PROMPT, {"conversation": row.text})
            except BudgetExceeded:
                run.skipped.append(f"{row.ref}: budget used up")
                break
            except LLMError as exc:
                run.skipped.append(f"{row.ref}: {type(exc).__name__}")
                continue
            run.classifier = models[-1] if models else run.classifier
            parsed = parse_reply(reply)
            if parsed is None:
                run.skipped.append(f"{row.ref}: unreadable answer")
                continue
            verdict, hazards = parsed
            verdicts.append({"ref": row.ref, "verdict": verdict, "hazards": hazards})
            if verdict == "safe":  # e.g. a victim asking for help: not a harmful request
                run.safe += 1
                continue
            run.unsafe += 1
            slot = slots.pop(0)
            append_item(slot.split, _reference(slot, row.ref, run.classifier))
            run.filled.append((slot.id, row.ref))
        run.cost_usd = budget.totals.cost_usd
    _log_selection(selection_path, verdicts, run.classifier)
    return run


def _reference(slot: Slot, ref: str, classifier: str | None) -> dict[str, Any]:
    name = (classifier or "the classifier").rsplit("/", 1)[-1]
    return {
        "id": slot.id,
        "expected": "block",
        "category": slot.category,
        "attack": slot.attack,
        "origin": VERBATIM,
        "dataset": VERBATIM_DATASET,
        "dataset_ref": ref,
        "notes": f"verbatim row, by reference; picked because {name} says unsafe "
        "(the requester intends harm)",
    }


def _log_selection(path: Path, verdicts: list[dict[str, Any]], classifier: str | None) -> None:
    if not verdicts:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).isoformat(timespec="seconds")
    with path.open("a", encoding="utf-8") as f:
        for v in verdicts:  # ids and verdicts only, never text
            f.write(json.dumps({**v, "classifier": classifier, "checked_at": stamp}) + "\n")
