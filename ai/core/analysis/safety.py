"""Safety screening (AI-06): refuse harmful skill requests before any skill is generated.

    analyzed = await screen_and_analyze(text, selected_targets=["claude"])   # may raise
    ...
    analyzed = await answer_questions_safely(analyzed, answers)             # screens again

Order: the screen (prompt analysis/safety) and the analysis (analysis/request) run at the same
time, as two independent LLM calls. The analysis is only released when the screen says
"allow". This keeps latency at about one call, keeps the screen independent of the analyzer
(a jailbreak would have to beat two prompts), and fails closed:
- screen says block, or a model refuses  -> RequestBlocked (no skill, no job; BE-14)
- the screen itself fails               -> SafetyUnavailable (try again later)
Policy: docs/ai/refusal-policy.md.
"""

import asyncio
import json
import logging
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Literal

from pydantic import Field, model_validator

from core.analysis.request import analyze_request, answer_questions
from core.analysis.types import (
    HARM_CATEGORIES,
    SAFETY_CONDITIONS,
    AnalyzedRequest,
    Answer,
    HarmCategory,
    SafetyClearance,
    SafetyCondition,
)
from core.llm import BudgetExceeded, LLMError, LLMRefused, complete, load_prompt
from core.spec import HIGH_RISK_AREAS, Target
from core.spec.models import Line, SpecModel

PROMPT_ID = "analysis/safety"
logger = logging.getLogger("skillforge.safety")

# One source for the policy wording used by the prompt, the docs and the tests.
CATEGORY_DESCRIPTIONS: dict[HarmCategory, str] = {
    "cyber_attack": "attacking computer systems the user does not own or is not allowed to "
    "test: malicious software, break-ins, stealing credentials, evading security tools",
    "fraud_scams": "deceiving people for gain: phishing, impersonation, fake reviews or "
    "documents, identity theft, laundering money",
    "weapons": "making or acquiring weapons that can cause mass harm, explosives, or illegal "
    "or untraceable firearms",
    "violence_harassment": "threatening, stalking, exposing or harassing specific people",
    "self_harm": "encouraging or enabling suicide, self-injury or disordered eating",
    "child_safety": "any sexualisation of minors or help to groom them",
    "hate_extremism": "dehumanising people for who they are, or recruiting for violent extremism",
    "privacy_surveillance": "secretly tracking or monitoring people, or profiling people from "
    "collected personal data without consent",
    "illegal_drugs": "making or trafficking illegal drugs",
    "disinformation": "deceiving the public at scale: fake grassroots campaigns, election "
    "manipulation, coordinated false information",
    "other": "any other request whose main purpose is serious harm",
}
CONDITION_DESCRIPTIONS: dict[SafetyCondition, str] = {
    "authorized_use_only": "security work only on systems the user owns or is allowed to test",
    "no_operational_harm": "explain threats so people can defend against them; never give "
    "working attack tools, recipes or step-by-step harm",
    "professional_disclaimer": "say it is not professional advice and recommend a qualified "
    "professional",
    "crisis_resources": "point to crisis help when distress or self-harm comes up",
    "privacy_protection": "work only with consent and the minimum personal data; nothing covert",
    "age_appropriate": "keep content suitable for children",
}

_REFUSAL = (
    "We can't create this skill. {reason} If you think this is a mistake, please rephrase "
    "what the skill should help with, or contact support."
)
REFUSAL_REASONS: dict[HarmCategory, str] = {
    "cyber_attack": "It would help attack computer systems. We can help with defending "
    "systems, security learning and testing systems you are allowed to test.",
    "fraud_scams": "It would help deceive or defraud people. We can help with spotting and "
    "preventing fraud.",
    "weapons": "It would help make or obtain dangerous weapons.",
    "violence_harassment": "It would help threaten, track or harass people.",
    "self_harm": "It could put someone's life or health at risk. If you are struggling, "
    "please reach out to a local crisis line or someone you trust.",
    "child_safety": "It would put children at risk.",
    "hate_extremism": "It would promote hatred or violent extremism.",
    "privacy_surveillance": "It would track or profile people without their consent. We can "
    "help with privacy protection and consent-based tools.",
    "illegal_drugs": "It would help make or sell illegal drugs. We can help with health and "
    "harm-reduction information.",
    "disinformation": "It would help mislead the public at scale.",
    "other": "It goes against our policy on harmful skills.",
}


class SafetyDecision(SpecModel):
    """What the screen decides. `rationale` is for the audit trail, never shown to users."""

    verdict: Literal["allow", "block"]
    category: HarmCategory | None = None
    conditions: list[SafetyCondition] = Field(default_factory=list)
    rationale: Line

    @model_validator(mode="after")
    def _consistent(self) -> "SafetyDecision":
        if self.verdict == "block" and (self.category is None or self.conditions):
            raise ValueError("a block needs a category and no conditions")
        if self.verdict == "allow" and self.category is not None:
            raise ValueError("an allowed request has no harm category")
        if len(set(self.conditions)) != len(self.conditions):
            raise ValueError("conditions must be unique")
        return self


def refusal_message(category: HarmCategory) -> str:
    return _REFUSAL.format(reason=REFUSAL_REASONS[category])


class RequestBlocked(Exception):
    """The request breaks the refusal policy. Show `user_message`; start no job (BE-14)."""

    def __init__(self, decision: SafetyDecision) -> None:
        assert decision.category is not None
        self.decision = decision
        self.category: HarmCategory = decision.category
        self.user_message = refusal_message(decision.category)
        super().__init__(f"request blocked: {decision.category}")


class SafetyUnavailable(Exception):
    """The screen could not run. Nothing may be generated; ask the user to try again."""


async def screen_request(text: str, answers: Sequence[Mapping[str, Any]] = ()) -> SafetyDecision:
    """Screen one request (and any answers to clarifying questions). Fails closed."""
    inputs = {
        "request_text": text,
        "answers": list(answers),
        "categories": [
            {"name": n, "description": CATEGORY_DESCRIPTIONS[n]} for n in HARM_CATEGORIES
        ],
        "conditions": [
            {"name": n, "description": CONDITION_DESCRIPTIONS[n]} for n in SAFETY_CONDITIONS
        ],
    }
    try:
        decision = await complete(PROMPT_ID, inputs, SafetyDecision)
    except LLMRefused:
        decision = _model_refused("the screening model refused to assess this request")
    except BudgetExceeded:
        raise  # out of budget is not an outage: retrying later would not help
    except LLMError as exc:
        raise SafetyUnavailable(f"safety screening failed: {type(exc).__name__}") from exc
    _log(decision)
    return decision


async def screen_and_analyze(
    text: str, *, selected_targets: Iterable[Target] = ()
) -> AnalyzedRequest:
    """Screen and analyze at the same time; release the analysis only if the screen allows."""
    screen, analysis = await asyncio.gather(
        screen_request(text),
        analyze_request(text, selected_targets=selected_targets),
        return_exceptions=True,
    )
    return _release(screen, analysis)


async def answer_questions_safely(
    analyzed: AnalyzedRequest, answers: Sequence[Answer]
) -> AnalyzedRequest:
    """Second pass: screen the request together with the answers, and re-analyze."""
    by_id = {q.id: q for q in analyzed.questions}
    unknown = sorted({a.question_id for a in answers} - set(by_id))
    if unknown:
        raise ValueError(f"answers to questions that were not asked: {unknown}")
    pairs = [{"question": by_id[a.question_id].text, "answer": a.text} for a in answers]
    screen, analysis = await asyncio.gather(
        screen_request(analyzed.request, pairs),
        answer_questions(analyzed, answers),
        return_exceptions=True,
    )
    return _release(screen, analysis)


def _release(
    screen: SafetyDecision | BaseException, analysis: AnalyzedRequest | BaseException
) -> AnalyzedRequest:
    for outcome in (screen, analysis):
        if isinstance(outcome, BudgetExceeded):
            raise outcome
    if isinstance(screen, SafetyUnavailable):
        raise screen
    if isinstance(screen, BaseException):
        raise SafetyUnavailable(f"safety screening failed: {type(screen).__name__}") from screen
    if screen.verdict == "block":
        raise RequestBlocked(screen)
    if isinstance(analysis, LLMRefused):  # the analyzer's model refused: treat as harmful
        decision = _model_refused("the analysis model refused this request")
        _log(decision)
        raise RequestBlocked(decision)
    if isinstance(analysis, BaseException):
        raise analysis
    conditions = list(screen.conditions)
    if analysis.domain_area in HIGH_RISK_AREAS and "professional_disclaimer" not in conditions:
        conditions.append("professional_disclaimer")
    clearance = SafetyClearance(
        conditions=conditions, prompt_version=load_prompt(PROMPT_ID).version
    )
    released = analysis.model_copy(update={"safety": clearance})
    return AnalyzedRequest.model_validate_json(released.model_dump_json())


def _model_refused(rationale: str) -> SafetyDecision:
    return SafetyDecision(verdict="block", category="other", rationale=rationale)


def _log(decision: SafetyDecision) -> None:
    """Metadata only: never the request, the answers or the rationale."""
    record = {
        "verdict": decision.verdict,
        "category": decision.category,
        "conditions": list(decision.conditions),
        "prompt_id": PROMPT_ID,
        "prompt_version": load_prompt(PROMPT_ID).version,
    }
    level = logging.WARNING if decision.verdict == "block" else logging.INFO
    logger.log(level, json.dumps(record), extra={"safety_decision": record})
