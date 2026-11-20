from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    Field,
    StringConstraints,
    field_validator,
)

from backend.app.spec.models import Target

# The same limits as the AI package's AnalyzedRequest, so a request that passes here is not
# rejected one step later.
RequestText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)
]
QuestionId = Annotated[str, StringConstraints(pattern=r"^q[1-5]$")]
AnswerText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


def _unique_in_order(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


class DesignRunCreate(BaseModel):
    project_id: UUID
    request: RequestText
    targets: Annotated[list[Target], AfterValidator(_unique_in_order)] = Field(
        default_factory=lambda: ["claude"],
        min_length=1,
        max_length=4,
        description="Platforms the skill is for.",
    )


class AnswerIn(BaseModel):
    question_id: QuestionId
    text: AnswerText | None = Field(default=None, description="null skips the question.")


class DesignRunAnswers(BaseModel):
    answers: list[AnswerIn] = Field(max_length=5)

    @field_validator("answers")
    @classmethod
    def one_answer_per_question(cls, answers: list[AnswerIn]) -> list[AnswerIn]:
        ids = [item.question_id for item in answers]
        if len(ids) != len(set(ids)):
            raise ValueError("send at most one answer per question")
        return answers


class DesignRunResponse(BaseModel):
    id: UUID
    project_id: UUID
    status: str
    step: str | None
    questions: list[dict[str, Any]]
    progress: list[dict[str, Any]]
    user_message: str | None
    error_code: str | None
    issues: list[dict[str, Any]]
    usage: dict[str, Any]
    spec_version_id: UUID | None
    version_number: int | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
