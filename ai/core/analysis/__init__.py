"""Request Analyzer (AI-05) and its output, AnalyzedRequest (contract A3).

    from core.analysis import screen_and_analyze, answer_questions_safely, AnalyzedRequest
    from core.analysis import check_gap        # Gap Checker (AI-08): does the skill exist?

See docs/ai/request-analyzer.md and docs/ai/gap-checker.md.
"""

from core.analysis.gap_checker import (
    FixtureSkillIndex,
    GapCheck,
    GapMatch,
    GapSettings,
    IndexInfo,
    SkillCard,
    SkillIndex,
    Verdict,
    check_gap,
    load_settings,
    request_text,
    skill_text,
)
from core.analysis.request import PROMPT_ID, RequestAnalysis, analyze_request, answer_questions
from core.analysis.safety import (
    RequestBlocked,
    SafetyDecision,
    SafetyUnavailable,
    answer_questions_safely,
    refusal_message,
    screen_and_analyze,
    screen_request,
)
from core.analysis.types import (
    HARM_CATEGORIES,
    MAX_QUESTIONS,
    MIN_QUESTIONS,
    QUESTION_TOPICS,
    SAFETY_CONDITIONS,
    SCHEMA_PATH,
    AnalyzedRequest,
    AnalyzerInfo,
    Answer,
    ClarifyingQuestion,
    HarmCategory,
    QuestionTopic,
    SafetyClearance,
    SafetyCondition,
    json_schema,
    render_schema,
)

__all__ = [
    "FixtureSkillIndex",
    "GapCheck",
    "GapMatch",
    "GapSettings",
    "IndexInfo",
    "SkillCard",
    "SkillIndex",
    "Verdict",
    "check_gap",
    "load_settings",
    "request_text",
    "skill_text",
    "HARM_CATEGORIES",
    "SAFETY_CONDITIONS",
    "HarmCategory",
    "RequestBlocked",
    "SafetyClearance",
    "SafetyCondition",
    "SafetyDecision",
    "SafetyUnavailable",
    "answer_questions_safely",
    "refusal_message",
    "screen_and_analyze",
    "screen_request",
    "MAX_QUESTIONS",
    "MIN_QUESTIONS",
    "PROMPT_ID",
    "QUESTION_TOPICS",
    "SCHEMA_PATH",
    "AnalyzedRequest",
    "AnalyzerInfo",
    "Answer",
    "ClarifyingQuestion",
    "QuestionTopic",
    "RequestAnalysis",
    "analyze_request",
    "answer_questions",
    "json_schema",
    "render_schema",
]
