"""The AI-19 injected test set (evaluation/injection/injections.yaml): models, loading, checks."""

import datetime as dt
import json
from collections import Counter
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field, HttpUrl, model_validator

from core.spec.models import SpecModel
from evaluation.common import AI_ROOT
from evaluation.extraction.data import PAGES_DIR, PageLabel, load_pages

DATA_DIR = AI_ROOT / "evaluation" / "injection"
DATA_FILE = DATA_DIR / "injections.yaml"

HIDDEN = (
    "display_none", "aria_hidden", "font_zero", "tiny_font", "white_text", "offscreen",
    "opacity", "style_class", "sr_only", "comment", "alt_text", "title_attr", "tag_chars",
)  # fmt: skip
VISIBLE_GATED = (
    "paragraph", "list_item", "in_paragraph", "link_text", "blockquote", "table_cell",
    "heading", "role_marker", "delimiter", "exfil_image", "secret_request", "zero_width",
    "vocative",
)  # fmt: skip
REPORTED = ("paraphrased", "other_language")
Technique = Literal[
    "display_none", "aria_hidden", "font_zero", "tiny_font", "white_text", "offscreen",
    "opacity", "style_class", "sr_only", "comment", "alt_text", "title_attr", "tag_chars",
    "paragraph", "list_item", "in_paragraph", "link_text", "blockquote", "table_cell",
    "heading", "role_marker", "delimiter", "exfil_image", "secret_request", "zero_width",
    "vocative", "paraphrased", "other_language",
]  # fmt: skip
Placement = Literal[
    "paragraph", "list_item", "in_paragraph", "link", "blockquote", "table_cell", "heading",
    "in_table_cell",
]  # fmt: skip
MIN_TEST_PER_GATED = 2  # the test split needs at least this many items per gated technique
Split = Literal["dev", "test"]


class Injection(SpecModel):
    id: str = Field(pattern=r"^[dt]-[hvpl]\d{2}$")
    was: str | None = Field(default=None, pattern=r"^t-[hvpl]\d{2}$", description="Old test id.")
    split: Split
    technique: Technique
    placement: Placement | None = Field(default=None, description="Visible insertions only.")
    language: str = "en"
    page: str
    anchor: int = Field(ge=1, description="Insert after the Nth matching content paragraph.")
    marker: str = Field(pattern=r"^[a-z]+-\d{2}$")
    url: HttpUrl | None = None
    payload: str = Field(min_length=10)

    @property
    def hidden(self) -> bool:
        return self.technique in HIDDEN

    @property
    def gated(self) -> bool:
        return self.technique not in REPORTED

    @property
    def layer(self) -> Literal["extraction", "rules"]:
        return "extraction" if self.hidden else "rules"

    @model_validator(mode="after")
    def _placement(self) -> "Injection":
        if self.hidden != (self.placement is None):
            raise ValueError(f"{self.id}: hidden techniques have no placement, others need one")
        if self.marker.lower() not in self.payload.lower():
            raise ValueError(f"{self.id}: the payload does not contain its marker")
        return self


class Control(SpecModel):
    id: str = Field(pattern=r"^[dt]-c\d{2}$")
    was: str | None = Field(default=None, pattern=r"^t-c\d{2}$", description="Old test id.")
    split: Split
    placement: Placement
    page: str
    anchor: int = Field(ge=1)
    text: str = Field(min_length=10)


class Review(SpecModel):
    status: Literal["draft", "reviewed"]
    reviewer: str | None = None
    date: dt.date | None = None


class InjectionSet(SpecModel):
    version: str
    review: Review
    pages: list[str]
    injections: list[Injection]
    controls: list[Control]

    def labels(self) -> dict[str, PageLabel]:
        by_file = {label.file: label for label in load_pages()}
        return {page: by_file[page] for page in self.pages}

    def split(self, split: Split | None) -> "InjectionSet":
        if split is None:
            return self
        return self.model_copy(
            update={
                "injections": [i for i in self.injections if i.split == split],
                "controls": [c for c in self.controls if c.split == split],
            }
        )


def load_set(path: Path = DATA_FILE) -> InjectionSet:
    data: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    # JSON mode, like the other datasets: YAML dates become ISO strings for strict models.
    return InjectionSet.model_validate_json(json.dumps(data, default=str))


def check_data(data: InjectionSet) -> list[str]:
    """Problems that make the set unusable; [] when it is fine."""
    problems = []
    real = {label.file for label in load_pages() if not label.synthetic and not label.expected}
    if sorted(set(data.pages)) != sorted(real):
        problems.append(f"pages must be the {len(real)} real AI-10 pages that pass")
    ids = [i.id for i in data.injections] + [c.id for c in data.controls]
    if len(set(ids)) != len(ids):
        problems.append("an id is used twice")
    markers = [i.marker for i in data.injections]
    if len(set(markers)) != len(markers):
        problems.append("a marker is used twice")
    items: list[Injection | Control] = [*data.injections, *data.controls]
    for item in items:
        if item.page not in data.pages:
            problems.append(f"{item.id}: page {item.page} is not in pages")
        if not item.id.startswith(item.split[0]):
            problems.append(f"{item.id}: the id prefix does not match split {item.split}")
    for injection in data.injections:
        others = [i.payload.lower() for i in data.injections if i.id != injection.id]
        if any(injection.marker in other for other in others):
            problems.append(f"{injection.id}: marker {injection.marker} appears in another payload")
    for control in data.controls:
        if any(i.marker in control.text.lower() for i in data.injections):
            problems.append(f"{control.id}: a control contains a marker")
    for split in ("dev", "test"):
        part = data.split(split)
        missing = set(HIDDEN + VISIBLE_GATED + REPORTED) - {i.technique for i in part.injections}
        if missing:
            problems.append(f"{split}: no injection for {sorted(missing)}")
        if split == "test":
            counts: Counter[str] = Counter(i.technique for i in part.injections)
            few = sorted(t for t in HIDDEN + VISIBLE_GATED if counts[t] < MIN_TEST_PER_GATED)
            if few:
                problems.append(f"test: fewer than {MIN_TEST_PER_GATED} items for {few}")
        if not part.controls:
            problems.append(f"{split}: no controls")
    if not all((PAGES_DIR / page).is_file() for page in data.pages):
        problems.append("a page file is missing")
    return problems
