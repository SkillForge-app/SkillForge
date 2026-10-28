
from pydantic import BaseModel, Field


class ProjectSpec(BaseModel):
    name: str = Field(min_length=1)
    description: str | None = None


class AgentSpec(BaseModel):
    name: str = Field(min_length=1)
    description: str | None = None
    version: str = "0.1.0"
    
class ToolSpec(BaseModel):
    name: str = Field(min_length=1)
    description: str | None = None
    enabled: bool = True


from typing import Literal


class ConstraintsSpec(BaseModel):
    rules: list[str] = Field(default_factory=list)


class WorkflowSpec(BaseModel):
    steps: list[str] = Field(default_factory=list)


class QualitySpec(BaseModel):
    criteria: list[str] = Field(default_factory=list)


class AutonomySpec(BaseModel):
    level: Literal["low", "medium", "high"] = "medium"


class AgentDefinition(BaseModel):
    agent: AgentSpec
    project: ProjectSpec
    tools: list[ToolSpec] = Field(default_factory=list)
    constraints: ConstraintsSpec = Field(default_factory=ConstraintsSpec)
    workflow: WorkflowSpec = Field(default_factory=WorkflowSpec)
    quality: QualitySpec = Field(default_factory=QualitySpec)
    autonomy: AutonomySpec = Field(default_factory=AutonomySpec)
