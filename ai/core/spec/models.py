"""SkillSpec v0.2: the platform-neutral description of a skill (AI-01, contract B1).

The Skill Architect fills a SkillSpec, never final Markdown; compilers turn it into packages.
These models hold the per-field rules: unknown fields are rejected, vocabularies are closed,
ids are stable kebab-case. They are exported to `schema.json` for the backend and frontend.
Rules that compare fields (ids that must exist, high-risk guardrails, ...) live in validator.py.
"""

import json
from datetime import date
from pathlib import Path
from typing import Annotated, Any, Literal, TypeVar, get_args

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    StringConstraints,
)
from pydantic_core import PydanticCustomError

SPEC_VERSION = "0.2"
SCHEMA_PATH = Path(__file__).with_name("schema.json")
SCHEMA_ID = f"urn:skillforge:skillspec:{SPEC_VERSION}"

# ------------------------------------------------------------------ closed vocabularies
# Public and part of contract B1: other modules (e.g. Track A's AnalyzedRequest, AI-05) import
# these instead of copying them. Use the Literal types as Pydantic field types, and the tuples
# (derived from them, so there is one source of truth) for prompts and runtime checks.

Kind = Literal["role", "task", "workflow"]
DomainArea = Literal[
    "technology",
    "data",
    "design",
    "product",
    "marketing",
    "sales",
    "customer-support",
    "operations",
    "hr",
    "education",
    "writing",
    "research",
    "finance",
    "legal",
    "medical",
    "general",
]
HIGH_RISK_AREAS: frozenset[DomainArea] = frozenset({"legal", "medical", "finance"})
# Risk of a skill request (Request Analyzer, AI-05) and of a benchmark skill (AI-04).
# "high" is reserved for HIGH_RISK_AREAS; "medium" for e.g. personal data or bias concerns.
RiskLevel = Literal["low", "medium", "high"]
Severity = Literal["must", "should"]
GuardrailCategory = Literal[
    "general", "accuracy", "safety", "privacy", "scope", "disclaimer", "human_review"
]
Capability = Literal[
    "filesystem_read",
    "filesystem_write",
    "terminal",
    "code_execution",
    "web_search",
    "web_fetch",
    "browser",
]
Target = Literal["claude", "codex", "chatgpt", "generic"]

KINDS: tuple[Kind, ...] = get_args(Kind)
DOMAIN_AREAS: tuple[DomainArea, ...] = get_args(DomainArea)
RISK_LEVELS: tuple[RiskLevel, ...] = get_args(RiskLevel)
CAPABILITIES: tuple[Capability, ...] = get_args(Capability)
TARGETS: tuple[Target, ...] = get_args(Target)
SEVERITIES: tuple[Severity, ...] = get_args(Severity)
GUARDRAIL_CATEGORIES: tuple[GuardrailCategory, ...] = get_args(GuardrailCategory)

# ------------------------------------------------------------------ field types

KEBAB = r"[a-z0-9]+(?:-[a-z0-9]+)*"
Id = Annotated[str, StringConstraints(pattern=f"^{KEBAB}$", max_length=64)]
SkillName = Annotated[str, StringConstraints(pattern=f"^{KEBAB}$", min_length=2, max_length=64)]
Version = Annotated[str, StringConstraints(pattern=r"^\d+\.\d+(?:\.\d+)?$")]
Domain = Annotated[
    str,
    StringConstraints(pattern=f"^(?:{'|'.join(DOMAIN_AREAS)})(?:/{KEBAB})+$", max_length=80),
]
TemplatePath = Annotated[str, StringConstraints(pattern=f"^templates/{KEBAB}\\.md$")]
ReferencePath = Annotated[str, StringConstraints(pattern=f"^references/{KEBAB}\\.md$")]

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Line = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]

T = TypeVar("T")


def _unique(items: list[T]) -> list[T]:
    seen: set[T] = set()
    for item in items:
        if item in seen:
            raise PydanticCustomError("duplicate_item", "{item!r} is listed twice", {"item": item})
        seen.add(item)
    return items


_UNIQUE = Field(json_schema_extra={"uniqueItems": True})

# Lists whose items must be distinct (also marked `uniqueItems` in schema.json).
IdList = Annotated[list[Id], _UNIQUE, AfterValidator(_unique)]
CapabilityList = Annotated[list[Capability], _UNIQUE, AfterValidator(_unique)]
TargetList = Annotated[list[Target], _UNIQUE, AfterValidator(_unique)]


class SpecModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


# ------------------------------------------------------------------ sections


class SkillMeta(SpecModel):
    name: SkillName = Field(
        description="Kebab-case skill name; becomes the folder name. Unique in the registry."
    )
    version: Version = Field(description='Version of this skill, e.g. "1.0". Quote it in YAML.')
    title: Title = Field(description="Human-readable name, e.g. AI Engineer.")
    kind: Kind = Field(
        description="role: acts as a professional; task: one repeatable job; "
        "workflow: a multi-step process."
    )
    domain: Domain = Field(
        description="<area>/<sub-area>, e.g. technology/ai. The area comes from a closed list; "
        "legal, medical and finance are high-risk."
    )
    summary: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)
    ] = Field(description="One or two sentences: what the skill makes the agent do.")


class Triggers(SpecModel):
    use_when: list[Line] = Field(
        min_length=1, max_length=10, description="Situations in which the agent should load it."
    )
    avoid_when: list[Line] = Field(
        default_factory=list, max_length=10, description="Situations that look similar but are not."
    )


class Expertise(SpecModel):
    principles: list[Text] = Field(
        min_length=1, max_length=20, description="Rules of thumb an expert in this role follows."
    )


class Procedure(SpecModel):
    id: Id = Field(description="Stable kebab-case id.")
    title: Title
    steps: list[Text] = Field(min_length=1, max_length=30, description="Ordered steps.")
    produces: IdList = Field(
        default_factory=list, description="Ids of the outputs this procedure produces."
    )
    uses: IdList = Field(
        default_factory=list,
        description="Ids of the knowledge references this procedure relies on.",
    )


class Output(SpecModel):
    id: Id = Field(description="Stable kebab-case id.")
    template: TemplatePath = Field(description="Template file in the package: templates/<name>.md.")
    title: Title | None = None
    sections: list[Line] = Field(
        default_factory=list, max_length=20, description="Headings of the template, in order."
    )


class Guardrail(SpecModel):
    id: Id = Field(description="Stable kebab-case id.")
    rule: Text = Field(description="What the agent must or should (not) do.")
    severity: Severity = Field(description="must: never break it; should: strong default.")
    category: GuardrailCategory = Field(
        default="general",
        description="High-risk domains need a 'must' disclaimer and a 'must' human_review rule.",
    )


class Tools(SpecModel):
    """Abstract capabilities only, never platform or vendor tool names."""

    required: CapabilityList = Field(
        default_factory=list, description="Capabilities the skill cannot work without."
    )
    optional: CapabilityList = Field(
        default_factory=list, description="Capabilities the skill uses when available."
    )


class Reference(SpecModel):
    id: Id = Field(description="Stable kebab-case id.")
    file: ReferencePath = Field(description="Reference file in the package: references/<name>.md.")
    title: Title | None = None
    sources: IdList = Field(
        min_length=1, description="Ids of the sources (see /sources) this reference is built from."
    )


class Knowledge(SpecModel):
    references: list[Reference] = Field(default_factory=list, max_length=30)


class Source(SpecModel):
    id: Id = Field(description="Stable kebab-case id, e.g. src-1.")
    url: HttpUrl
    retrieved: date = Field(description="Date the page was retrieved (YYYY-MM-DD).")
    title: Line | None = Field(default=None, description="The page's own title.")
    licence: Line | None = Field(default=None, description="The source licence, when known, e.g. CC BY 4.0. Omit it if unknown.")


class Evaluation(SpecModel):
    test_prompts: list[Text] = Field(
        min_length=1, max_length=50, description="Requests the skill should handle well."
    )
    rubric: list[Line] = Field(
        min_length=1, max_length=20, description="What a good answer does; used by the judge."
    )
    should_not_trigger: list[Text] = Field(
        default_factory=list,
        max_length=50,
        description="Requests that must NOT load the skill (trigger-accuracy tests).",
    )


class SkillSpec(SpecModel):
    """A platform-neutral skill, compiled into Claude, Codex, ChatGPT or generic packages."""

    model_config = ConfigDict(title="SkillSpec")

    spec_version: Literal["0.2"] = Field(description='Always "0.2" for this schema. Quote it.')
    skill: SkillMeta
    triggers: Triggers
    expertise: Expertise
    procedures: list[Procedure] = Field(min_length=1, max_length=30)
    outputs: list[Output] = Field(default_factory=list, max_length=30)
    guardrails: list[Guardrail] = Field(default_factory=list, max_length=30)
    tools: Tools = Field(default_factory=Tools)
    knowledge: Knowledge = Field(default_factory=Knowledge)
    sources: list[Source] = Field(default_factory=list, max_length=100)
    evaluation: Evaluation
    targets: TargetList = Field(min_length=1, description="Platforms to compile for.")


# ------------------------------------------------------------------ schema.json


def json_schema() -> dict[str, Any]:
    """The published JSON Schema (draft 2020-12) for SkillSpec."""
    schema = SkillSpec.model_json_schema(mode="validation")
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": SCHEMA_ID,
        "x-spec-version": SPEC_VERSION,
        **schema,
        "description": (
            "SkillSpec v0.2. This schema holds the per-field rules. Cross-field rules (referenced "
            "ids must exist, high-risk guardrails, description length, ...) are checked by the "
            "API with core.spec.validate_spec and returned as issues with JSON Pointer paths."
        ),
    }


def render_schema() -> str:
    return json.dumps(json_schema(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
