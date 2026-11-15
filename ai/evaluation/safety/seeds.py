"""Seeds for adapted items (AI-06): rows from the vetted red-team datasets, one per adapted slot.

    python -m evaluation.safety seeds --datasets C:/AgentForge-worktrees/_data/safety-datasets

Reads DIR/<dataset>/ (csv, jsonl, jsonl.gz) as described in generator/datasets.yaml, maps each
row's category to ours, and writes runs/redteam-seeds.jsonl (ignored by Git): the raw dataset
text never goes into the repository, only our reworded item and the row reference.
"""

import contextlib
import csv
import gzip
import json
import random
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

from evaluation.safety.data import ARABIC, DATASET_LICENCES, SAFETY_DIR
from evaluation.safety.slots import Slot

DATASETS_PATH = SAFETY_DIR / "generator" / "datasets.yaml"
SEEDS_PATH = SAFETY_DIR / "runs" / "redteam-seeds.jsonl"
RANDOM_SEED = 6  # AI-06: a fixed pick, so the same downloads give the same seeds


@dataclass(frozen=True)
class Seed:
    dataset: str
    ref: str
    licence: str
    category: str  # ours, from HARM_CATEGORIES
    text: str
    arabic: bool
    slot: str | None = None  # the slot it was picked for


def load_seeds(datasets_dir: Path, config_path: Path = DATASETS_PATH) -> list[Seed]:
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))["datasets"]
    seeds = []
    for name, spec in config.items():
        folder = datasets_dir / name
        if not folder.is_dir():
            continue
        for path in sorted(folder.rglob("*")):
            for line, row in _rows(path):
                seed = _seed(name, spec, row, f"{path.name}:{line}")
                if seed is not None:
                    seeds.append(seed)
    return seeds


def select_seeds(slots: list[Slot], seeds: list[Seed], *, seed: int = RANDOM_SEED) -> list[Seed]:
    """One unused seed per adapted slot, in its category; Arabic rows for `arabic` slots when
    there are any. A slot with no seed in its category is left out (reported by the caller)."""
    rng = random.Random(seed)
    used: set[tuple[str, str]] = set()
    picked = []
    for slot in slots:
        if slot.origin != "adapted":
            continue
        pool = [s for s in seeds if s.category == slot.category and (s.dataset, s.ref) not in used]
        if slot.attack == "arabic" and any(s.arabic for s in pool):
            pool = [s for s in pool if s.arabic]
        if pool:
            choice = rng.choice(pool)
            used.add((choice.dataset, choice.ref))
            picked.append(Seed(**{**asdict(choice), "slot": slot.id}))
    return picked


def write_seeds(seeds: list[Seed], path: Path = SEEDS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = (json.dumps(asdict(s), ensure_ascii=False) for s in seeds)
    path.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")


def read_seeds(path: Path = SEEDS_PATH) -> dict[str, Seed]:
    """The picked seeds by slot id (empty when `seeds` has not been run)."""
    if not path.exists():
        return {}
    seeds = [Seed(**json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines()]
    return {s.slot: s for s in seeds if s.slot}


def _rows(path: Path) -> Iterator[tuple[int, dict[str, Any]]]:
    name = path.name.lower()
    if name.endswith(".csv"):
        with path.open(encoding="utf-8", newline="") as f:
            yield from enumerate(csv.DictReader(f), start=2)  # line 1 is the header
    elif name.endswith((".jsonl", ".jsonl.gz")):
        opener = gzip.open if name.endswith(".gz") else open
        with opener(path, "rt", encoding="utf-8") as f:
            content = f.read()
        if content.lstrip().startswith("["):  # one JSON array (hh-rlhf's red_team_attempts)
            yield from enumerate(json.loads(content), start=1)
            return
        for line, text in enumerate(content.splitlines(), start=1):
            if text.strip():
                yield line, json.loads(text)


def _field(row: dict[str, Any], names: list[str]) -> Any:
    return next((row[n] for n in names if row.get(n) not in (None, "")), None)


def _seed(name: str, spec: dict[str, Any], row: dict[str, Any], where: str) -> Seed | None:
    if any(str(row.get(column)) != value for column, value in spec.get("where", {}).items()):
        return None
    text = _field(row, spec["text"])
    labels = _field(row, spec["category"])
    if not isinstance(text, str) or not text.strip() or labels is None:
        return None
    if isinstance(labels, str) and labels.startswith("["):  # a list stored as text
        with contextlib.suppress(ValueError):
            labels = json.loads(labels.replace("'", '"'))
    categories = [spec["categories"].get(str(label)) for label in _as_list(labels)]
    category = next((c for c in categories if c), None)
    if category is None:
        return None
    ref = _field(row, spec["id"]) if spec["id"] else None
    language = str(_field(row, spec.get("language", [])) or "")
    arabic = bool(ARABIC.search(text)) or language.lower() in ("arabic", "ar", "arb")
    return Seed(name, str(ref or where), DATASET_LICENCES[name], category, text.strip(), arabic)


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else [value]
