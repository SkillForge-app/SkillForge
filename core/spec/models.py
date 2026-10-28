
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
    )


class ProjectSpec(StrictModel):
    name: str = Field(min_length=1)
    description: str | None = None


class ToolSpec(StrictModel):
    name: str = Field(min_length=1)
    description: str | None = None
    enabled: bool = True


class ConstraintsSpec(StrictModel):
    rules: list[str] = Field(default_factory=list)


class WorkflowSpec(StrictModel):
    steps: list[str] = Field(default_factory=list)


class QualitySpec(StrictModel):
    criteria: list[str] = Field(default_factory=list)


class AutonomySpec(StrictModel):
    level: Literal["low", "medium", "high"] = "medium"


class AgentSpec(StrictModel):
    name: str = Field(min_length=1)
    description: str | None = None
    runtime: Literal["python", "node", "container"]
    entrypoint: str = Field(min_length=1)
    tools: list[str] = Field(default_factory=list)
    environment: dict[str, str] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)

    constraints: ConstraintsSpec = Field(
        default_factory=ConstraintsSpec
    )
    workflow: WorkflowSpec = Field(
        default_factory=WorkflowSpec
    )
    quality: QualitySpec = Field(
        default_factory=QualitySpec
    )
    autonomy: AutonomySpec = Field(
        default_factory=AutonomySpec
    )


class AgentDefinition(StrictModel):
    agent: AgentSpec
    project: ProjectSpec
    tools: list[ToolSpec] = Field(default_factory=list)
