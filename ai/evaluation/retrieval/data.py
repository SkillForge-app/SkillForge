"""AI-11 evaluation data: the test questions and the embedding-model candidates."""

import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, model_validator

from core.knowledge.retrieval import check_domain
from core.llm.config import LocalModel, ModelConfig, ModelRole
from core.spec.models import Line, SpecModel
from evaluation.common import AI_ROOT
from evaluation.extraction.data import PageLabel, load_pages

HERE = AI_ROOT / "evaluation" / "retrieval"
QUESTIONS_FILE = HERE / "questions.yaml"
CANDIDATES_FILE = HERE / "candidates.yaml"


class Question(SpecModel):
    id: str = Field(pattern=r"^q\d{2,3}$")
    question: Line
    domain: str
    page: str  # a labelled page file in tests/fixtures/pages
    evidence: Line  # copied exactly from that page's extracted text


class QuestionSet(SpecModel):
    version: str
    pages: dict[str, str]  # page file -> the domain it is indexed under
    questions: list[Question]

    @model_validator(mode="after")
    def _consistent(self) -> "QuestionSet":
        for domain in [*self.pages.values(), *(q.domain for q in self.questions)]:
            check_domain(domain)
        ids = [q.id for q in self.questions]
        if len(set(ids)) != len(ids):
            raise ValueError("question ids must be unique")
        unknown = sorted({q.page for q in self.questions} - set(self.pages))
        if unknown:
            raise ValueError(f"questions about pages with no domain: {unknown}")
        return self


class Candidate(SpecModel):
    model: str
    dimensions: int
    max_tokens: int
    licence: str
    query_prefix: str
    local: LocalModel

    def role(self) -> ModelRole:
        return ModelRole(
            model=self.model,
            dimensions=self.dimensions,
            local=self.local,
            query_prefix=self.query_prefix,
            num_retries=0,
        )

    def model_config_for(self) -> ModelConfig:
        """A config whose `embedding` role is this candidate (for a LiteLLMGateway)."""
        return ModelConfig(roles={"embedding": self.role()})


def _yaml(path: Path) -> Any:
    # JSON mode for strict models, like the other datasets.
    return json.loads(json.dumps(yaml.safe_load(path.read_text(encoding="utf-8")), default=str))


def load_questions(path: Path = QUESTIONS_FILE) -> QuestionSet:
    question_set = QuestionSet.model_validate_json(json.dumps(_yaml(path)))
    labelled = {label.file: label for label in load_pages()}
    for file in question_set.pages:
        if file not in labelled or labelled[file].expected:
            raise ValueError(f"{file} is not a labelled page that passes extraction")
    return question_set


def load_candidates(path: Path = CANDIDATES_FILE) -> dict[str, Candidate]:
    data = _yaml(path)
    return {
        name: Candidate.model_validate_json(json.dumps(c)) for name, c in data["candidates"].items()
    }


def indexed_pages(question_set: QuestionSet, *, real_only: bool = False) -> list[PageLabel]:
    """The labelled pages the questions are asked over (`real_only`: no synthetic pages)."""
    return [
        label
        for label in load_pages()
        if label.file in question_set.pages and not (real_only and label.synthetic)
    ]
