"""Request Analyzer (AI-05): free-text skill request -> AnalyzedRequest (contract A3).

    analyzed = await analyze_request("I need a recruiter skill", selected_targets=["claude"])
    if analyzed.needs_clarification:
        ...show analyzed.questions, collect answers...
        analyzed = await answer_questions(analyzed, answers)

The LLM classifies and extracts; a few rules are then applied in code so they never depend
on the model (see `_finish`).
"""

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from pydantic import Field, model_validator

from core.analysis.types import (
    MAX_QUESTIONS,
    MIN_QUESTIONS,
    AnalyzedRequest,
    AnalyzerInfo,
    Answer,
    ClarifyingQuestion,
    Classification,
)
from core.llm import complete, load_prompt
from core.spec import DOMAIN_AREAS, HIGH_RISK_AREAS, KINDS, TARGETS, RiskLevel, Target
from core.spec.models import TargetList

PROMPT_ID = "analysis/request"


class RequestAnalysis(Classification):
    """What the LLM returns. AnalyzedRequest adds the request, targets, answers and metadata."""

    mentioned_targets: TargetList = Field(
        default_factory=list, description="Only platforms the request itself names."
    )

    @model_validator(mode="after")
    def _question_rule(self) -> "RequestAnalysis":
        self._check_question_ids()
        count = len(self.questions)
        if self.needs_clarification and not MIN_QUESTIONS <= count <= MAX_QUESTIONS:
            raise ValueError(f"a vague request needs {MIN_QUESTIONS} to {MAX_QUESTIONS} questions")
        if not self.needs_clarification and count:
            raise ValueError("write questions only when needs_clarification is true")
        return self


async def analyze_request(text: str, *, selected_targets: Iterable[Target] = ()) -> AnalyzedRequest:
    """First pass: classify the request and, if it is vague, ask 3 to 5 questions."""
    analysis = await complete(PROMPT_ID, _inputs(text, ()), RequestAnalysis)
    return _finish(text, analysis, selected_targets)


async def answer_questions(analyzed: AnalyzedRequest, answers: Sequence[Answer]) -> AnalyzedRequest:
    """Second pass, after the user answered (or skipped) the questions. Never asks again."""
    by_id = {q.id: q for q in analyzed.questions}
    unknown = sorted({a.question_id for a in answers} - set(by_id))
    if unknown:  # checked before paying for an LLM call
        raise ValueError(f"answers to questions that were not asked: {unknown}")
    pairs = [{"question": by_id[a.question_id].text, "answer": a.text} for a in answers]
    analysis = await complete(PROMPT_ID, _inputs(analyzed.request, pairs), RequestAnalysis)
    return _finish(
        analyzed.request,
        analysis,
        analyzed.targets,
        questions=analyzed.questions,
        answers=answers,
    )


def _inputs(text: str, answers: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "request_text": text,
        "answers": list(answers),
        "kinds": list(KINDS),
        "domain_areas": list(DOMAIN_AREAS),
        "high_risk_areas": sorted(HIGH_RISK_AREAS),
    }


def _finish(
    text: str,
    analysis: RequestAnalysis,
    selected_targets: Iterable[Target],
    *,
    questions: Sequence[ClarifyingQuestion] | None = None,
    answers: Sequence[Answer] = (),
) -> AnalyzedRequest:
    """Apply the rules that must not depend on the model.

    - risk: high exactly for HIGH_RISK_AREAS; a "high" anywhere else becomes "medium".
    - targets: platforms picked in the UI plus platforms named in the text, in TARGETS order.
    - after answers: keep the original questions, store the answers, never ask again.
    """
    area = analysis.domain.split("/", 1)[0]
    risk: RiskLevel
    if area in HIGH_RISK_AREAS:
        risk = "high"
    elif analysis.risk == "high":
        risk = "medium"
    else:
        risk = analysis.risk
    wanted = set(selected_targets) | set(analysis.mentioned_targets)
    prompt = load_prompt(PROMPT_ID)
    return AnalyzedRequest(
        request=text,
        kind=analysis.kind,
        domain=analysis.domain,
        risk=risk,
        audience=analysis.audience,
        expected_outputs=list(analysis.expected_outputs),
        skill_name=analysis.skill_name,
        summary=analysis.summary,
        needs_clarification=analysis.needs_clarification if questions is None else False,
        questions=list(analysis.questions if questions is None else questions),
        answers=list(answers),
        targets=[t for t in TARGETS if t in wanted],
        analyzer=AnalyzerInfo(prompt_id=PROMPT_ID, prompt_version=prompt.version),
    )
