import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from core.spec import Issue, validate_spec

AI_ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = AI_ROOT / "examples" / "skillspec"
FIXTURES = Path(__file__).parent / "fixtures"
EXAMPLE_NAMES = sorted(p.stem for p in EXAMPLES.glob("*.yaml"))

Spec = dict[str, Any]


def load_yaml(path: Path) -> Spec:
    data: Spec = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data


def example(name: str = "ai-engineer") -> Spec:
    """A fresh copy of an example spec, safe to modify."""
    return copy.deepcopy(load_yaml(EXAMPLES / f"{name}.yaml"))


def changed(change: Callable[[Spec], object], name: str = "ai-engineer") -> Spec:
    data = example(name)
    change(data)
    return data


def as_json(data: Spec) -> Any:
    """What the API would receive: plain JSON types (YAML dates become strings)."""
    return json.loads(json.dumps(data, default=str))


def codes(data: Spec) -> list[tuple[str, str]]:
    """(path, code) of every issue, in the validator's order."""
    return [(i.path, i.code) for i in validate_spec(data).issues]


def only_issue(data: Spec) -> Issue:
    [issue] = validate_spec(data).issues
    return issue
