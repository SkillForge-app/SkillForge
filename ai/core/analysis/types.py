"""AnalyzedRequest (contract A3): what the Request Analyzer (AI-05) hands to the Skill Architect.

It is also what the backend stores for a skill request and what the frontend's clarify step
(FE-08) shows. The closed vocabularies (Kind, DomainArea, RiskLevel, Target) come from core.spec,
so labels, analyzer and SkillSpec always agree. Draft 6 Nov 2026, frozen 13 Nov 2026.
"""

import json
from pathlib import Path
from typing import Annotated, Any, Literal, get_args

from pydantic import Field, StringConstraints, model_validator

from core.spec import Kind, RiskLevel
from core.spec.models import Domain, Line, SkillName, SpecModel, TargetList, Text

QuestionTopic = Literal[
    "audience", "outputs", "platforms", "scope", "tone", "constraints", "domain"
]
QUESTION_TOPICS: tuple[QuestionTopic, ...] = get_args(QuestionTopic)
MIN_QUESTIONS = 3
MAX_QUESTIONS = 5

QuestionId = Annotated[str, StringConstraints(pattern=r"^q[1-5]$")]
RequestText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)
]
# Safety screening (AI-06). Reasons a request is blocked, and conditions attached to an allowed
# request that the Skill Architect must turn into `must` guardrails. See docs/ai/refusal-policy.md.
HarmCategory = Literal[
    "cyber_attack",
    "fraud_scams",
    "weapons",
    "violence_harassment",
    "self_harm",
    "child_safety",
    "hate_extremism",
    "privacy_surveillance",
    "illegal_drugs",
    "disinformation",
    "other",
]
HARM_CATEGORIES: tuple[HarmCategory, ...] = get_args(HarmCategory)
SafetyCondition = Literal[
    "authorized_use_only",
    "no_operational_harm",
    "professional_disclaimer",
    "crisis_resources",
    "privacy_protection",
    "age_appropriate",
]
SAFETY_CONDITIONS: tuple[SafetyCondition, ...] = get_args(SafetyCondition)

SCHEMA_PATH = Path(__file__).with_name("analyzed_request.schema.json")
SCHEMA_ID = "urn:skillforge:analyzed-request:0.1"


class ClarifyingQuestion(SpecModel):
    id: QuestionId = Field(description="q1 to q5.")
    text: Line = Field(description="Short question, in the language of the request.")
    about: QuestionTopic = Field(description="Which part of the analysis the answer fills in.")


class Answer(SpecModel):
    question_id: QuestionId
    text: Text | None = Field(default=None, description="null when the user skipped it.")


class AnalyzerInfo(SpecModel):
    prompt_id: str
    prompt_version: int = Field(ge=1)


class SafetyClearance(SpecModel):
    """Proof that the request passed safety screening, and the guardrails it requires."""

    conditions: list[SafetyCondition] = Field(
        default_factory=list,
        json_schema_extra={"uniqueItems": True},
        description="Each one must become a `must` guardrail in the SkillSpec.",
    )
    prompt_version: int = Field(ge=1, description="Version of the analysis/safety prompt.")

    @model_validator(mode="after")
    def _unique(self) -> "SafetyClearance":
        if len(set(self.conditions)) != len(self.conditions):
            raise ValueError("conditions must be unique")
        return self


class Classification(SpecModel):
    """The fields the analyzer decides. Shared by the LLM output and AnalyzedRequest."""

    kind: Kind = Field(description="role, task or workflow.")
    domain: Domain = Field(description="<area>/<sub-area>, area from the closed list.")
    risk: RiskLevel = Field(description="high only for legal, medical and finance areas.")
    audience: Line | None = Field(default=None, description="Who the skill's work is for.")
    expected_outputs: list[Line] = Field(
        default_factory=list, max_length=10, description="Artefacts the skill should produce."
    )
    skill_name: SkillName | None = Field(default=None, description="Suggested kebab-case name.")
    summary: Line = Field(description="One-sentence restatement of the request, in English.")
    needs_clarification: bool = Field(
        description="True when the request is too vague to design a skill from."
    )
    questions: list[ClarifyingQuestion] = Field(default_factory=list, max_length=MAX_QUESTIONS)

    @property
    def domain_area(self) -> str:
        return self.domain.split("/", 1)[0]

    def _check_question_ids(self) -> None:
        ids = [q.id for q in self.questions]
        if len(set(ids)) != len(ids):
            raise ValueError("question ids must be unique")


class AnalyzedRequest(Classification):
    """Contract A3. Produced by analyze_request(); updated by answer_questions()."""

    request: RequestText = Field(description="The user's request, as typed.")
    targets: TargetList = Field(
        default_factory=list,
        description="Platforms picked in the UI plus platforms named in the request. Empty: "
        "not chosen yet.",
    )
    answers: list[Answer] = Field(default_factory=list, max_length=MAX_QUESTIONS)
    analyzer: AnalyzerInfo
    safety: SafetyClearance | None = Field(
        default=None,
        description="Set by screen_and_analyze (AI-06). null: not screened, so it must not be "
        "used to generate a skill.",
    )

    @model_validator(mode="after")
    def _questions_and_answers(self) -> "AnalyzedRequest":
        self._check_question_ids()
        if self.questions and not MIN_QUESTIONS <= len(self.questions) <= MAX_QUESTIONS:
            raise ValueError(f"ask {MIN_QUESTIONS} to {MAX_QUESTIONS} questions, or none")
        if self.needs_clarification and (not self.questions or self.answers):
            raise ValueError("needs_clarification means open questions and no answers yet")
        if not self.needs_clarification and self.questions and not self.answers:
            raise ValueError("questions without answers mean needs_clarification must be true")
        asked = {q.id for q in self.questions}
        answered = [a.question_id for a in self.answers]
        if len(set(answered)) != len(answered):
            raise ValueError("at most one answer per question")
        unknown = sorted(set(answered) - asked)
        if unknown:
            raise ValueError(f"answers to questions that were not asked: {unknown}")
        return self


def json_schema() -> dict[str, Any]:
    schema = AnalyzedRequest.model_json_schema(mode="validation")
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": SCHEMA_ID,
        **schema,
        "description": (
            "AnalyzedRequest (contract A3, draft). Per-field rules only; the question/answer "
            "rules are enforced by core.analysis.AnalyzedRequest. Only requests that passed "
            "safety screening (safety is not null) may be used to generate a skill."
        ),
    }


def render_schema() -> str:
    return json.dumps(json_schema(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
