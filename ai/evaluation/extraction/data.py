"""The labelled pages for AI-10 (tests/fixtures/pages/pages.yaml), shared by tests and report."""

import json
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, HttpUrl, model_validator

from core.knowledge.extract import REASONS, Reason
from core.spec.models import Line, SpecModel
from evaluation.common import AI_ROOT

PAGES_DIR = AI_ROOT / "tests" / "fixtures" / "pages"
PAGES_FILE = PAGES_DIR / "pages.yaml"


class PageLabel(SpecModel):
    file: str = Field(pattern=r"^[a-z0-9-]+\.html$")
    url: HttpUrl
    retrieved: date
    licence: Line
    expected: list[Reason] = Field(description="[] when the page must pass.")
    title: Line | None = None
    language: str | None = None
    notes: str | None = None
    must_contain: list[Line] = Field(default_factory=list)
    must_not_contain: list[Line] = Field(default_factory=list)

    @model_validator(mode="after")
    def _consistent(self) -> "PageLabel":
        if self.expected != [r for r in REASONS if r in self.expected]:
            raise ValueError("expected reasons must be unique and in REASONS order")
        if self.expected and self.must_contain:
            raise ValueError("a rejected page has no chunks, so it cannot have must_contain")
        return self

    @property
    def path(self) -> Path:
        return PAGES_DIR / self.file

    @property
    def synthetic(self) -> bool:
        return self.file.startswith("synthetic-")


def load_pages(path: Path = PAGES_FILE) -> list[PageLabel]:
    data: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    # JSON mode, like the other datasets: YAML dates become ISO strings for strict models.
    pages = [PageLabel.model_validate_json(json.dumps(p, default=str)) for p in data["pages"]]
    files = [p.file for p in pages]
    if len(set(files)) != len(files):
        raise ValueError(f"{path}: a file is labelled twice")
    missing = [p.file for p in pages if not p.path.is_file()]
    if missing:
        raise ValueError(f"{path}: missing page files {missing}")
    unlabelled = sorted({p.name for p in PAGES_DIR.glob("*.html")} - set(files))
    if unlabelled:
        raise ValueError(f"{path}: pages without a label {unlabelled}")
    return pages
