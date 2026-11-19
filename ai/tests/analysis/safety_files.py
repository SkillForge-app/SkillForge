"""Empty copies of redteam.yaml and safety-dev.yaml for tests: the real headers, no block
items, known versions. The real files fill up as people review; tests must not depend on that."""

import re
from pathlib import Path

import pytest

from evaluation.safety import data


def install_empty_copies(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    red = data.FILES["redteam"].read_text(encoding="utf-8").split("\nrequests:")[0]
    red = _set(red, "version", "0.0.1")
    red = _set(red, "status", "incomplete")
    red = _set(red, "source", "null") + "\nrequests: []\n"
    dev = data.FILES["dev"].read_text(encoding="utf-8").split("\n  - id: sd-11")[0] + "\n"
    dev = _set(dev, "version", "0.1.1")
    dev = _set(dev, "status", "incomplete")
    dev = _set(dev, "source", "allow half written by the AI team; block half to do")
    for split, text in (("redteam", red), ("dev", dev)):
        copy = tmp_path / data.FILES[split].name
        copy.write_text(text, encoding="utf-8")
        monkeypatch.setitem(data.FILES, split, copy)


def _set(text: str, key: str, value: str) -> str:
    return re.sub(rf"^{key}: .*$", f"{key}: {value}", text, count=1, flags=re.MULTILINE)
