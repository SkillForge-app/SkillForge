"""SkillSpec validation: schema errors and cross-field rules, reported as one list of issues.

    result = validate_spec(data)            # dict (e.g. from YAML) or JSON text
    if not result.ok:
        for issue in result.errors:
            print(issue.path, issue.code, issue.message)

Every issue has a JSON Pointer `path` (e.g. /procedures/0/produces/1), a stable `code` and a
short `message`. The frontend shows them next to the field; the Skill Architect gets them back
in its repair loop. Messages never include the field's value, only its location.
"""

import difflib
import json
import re
import types
from collections.abc import Collection, Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal, Union, get_args, get_origin

import yaml
from pydantic import BaseModel, ValidationError

from core.spec.models import HIGH_RISK_AREAS, SkillSpec

IssueSeverity = Literal["error", "warning"]


@dataclass(frozen=True)
class PlatformLimits:
    name: int
    description: int
    verified: bool  # False: from the Agent Skills standard; confirm in BE-09


# Claude: https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview (2026-10-23).
# Codex docs give no explicit limit; the others are not designed yet. All use the Agent Skills
# standard values until the compilers (BE-09, BE-23) confirm them.
PLATFORM_LIMITS: dict[str, PlatformLimits] = {
    "claude": PlatformLimits(name=64, description=1024, verified=True),
    "codex": PlatformLimits(name=64, description=1024, verified=False),
    "chatgpt": PlatformLimits(name=64, description=1024, verified=False),
    "generic": PlatformLimits(name=64, description=1024, verified=False),
}
RESERVED_NAME_WORDS = {"claude": ("claude", "anthropic")}
_XML_TAG = re.compile(r"<[^<>]+>")


@dataclass(frozen=True)
class Issue:
    path: str
    code: str
    message: str
    severity: IssueSeverity = "error"

    def __str__(self) -> str:
        return f"{self.path or '/'}  {self.code}  {self.message}"


@dataclass(frozen=True)
class ValidationResult:
    spec: SkillSpec | None
    issues: tuple[Issue, ...]

    @property
    def errors(self) -> tuple[Issue, ...]:
        return tuple(i for i in self.issues if i.severity == "error")

    @property
    def warnings(self) -> tuple[Issue, ...]:
        return tuple(i for i in self.issues if i.severity == "warning")

    @property
    def ok(self) -> bool:
        return not self.errors


class SpecValidationError(ValueError):
    def __init__(self, source: str, issues: Iterable[Issue]) -> None:
        self.issues = tuple(issues)
        lines = "\n".join(f"  {issue}" for issue in self.issues)
        super().__init__(f"{source}: invalid SkillSpec\n{lines}")


# ------------------------------------------------------------------ entry points


def validate_spec(
    data: Mapping[str, Any] | str | bytes, *, existing_names: Collection[str] = ()
) -> ValidationResult:
    """Validate a SkillSpec given as a dict or JSON text.

    `existing_names`: skill names already in the registry (the backend passes them), so a new
    spec cannot take a used name. Leave empty when updating an existing skill.
    """
    if isinstance(data, Mapping):
        # JSON mode for every input: YAML dates become ISO strings, so strictness is the same
        # whether the spec came from a YAML file or from the API.
        data = json.dumps(data, default=str)
    try:
        spec = SkillSpec.model_validate_json(data)
    except ValidationError as exc:
        return ValidationResult(None, tuple(schema_issues(exc)))
    issues = sorted(_rule_issues(spec, existing_names), key=lambda i: (i.path, i.code))
    return ValidationResult(spec, tuple(issues))


def load_spec(path: str | Path, *, existing_names: Collection[str] = ()) -> SkillSpec:
    """Read a YAML (or JSON) SkillSpec file. Raises SpecValidationError if it has errors."""
    path = Path(path)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise SpecValidationError(str(path), [Issue("", "yaml_syntax", str(exc))]) from None
    if not isinstance(data, Mapping):
        raise SpecValidationError(str(path), [Issue("", "not_a_mapping", "expected a mapping")])
    result = validate_spec(data, existing_names=existing_names)
    if result.spec is None or not result.ok:
        raise SpecValidationError(str(path), result.errors)
    return result.spec


def draft_description(spec: SkillSpec) -> str:
    """The description a compiler can always build from the spec (AI-14 may write a better one).

    Used to check that a valid spec fits every target's description limit.
    """
    text = f"{spec.skill.summary} Use when: {'; '.join(spec.triggers.use_when)}."
    if spec.triggers.avoid_when:
        text += f" Not for: {'; '.join(spec.triggers.avoid_when)}."
    return text


# ------------------------------------------------------------------ schema errors


def schema_issues(exc: ValidationError, model: type[BaseModel] = SkillSpec) -> Iterator[Issue]:
    """Turn a pydantic ValidationError on `model` into issues (JSON Pointer path, code, message).

    Shared with other strict models (e.g. the seed benchmark) so all report errors the same way.
    """
    for error in exc.errors(include_url=False):
        loc = error["loc"]
        path = _pointer(loc)
        kind = error["type"]
        if kind == "extra_forbidden":
            field = str(loc[-1])
            message = f'unknown field "{field}"'
            match = difflib.get_close_matches(field, _fields_at(loc[:-1], model), n=1, cutoff=0.6)
            if match:
                message += f'; did you mean "{match[0]}"?'
            yield Issue(path, "schema.unknown_field", message)
        elif kind == "missing":
            yield Issue(path, "schema.missing", f'missing required field "{loc[-1]}"')
        else:
            message = error["msg"]
            if kind == "string_type" and isinstance(error.get("input"), int | float):
                message += ' (in YAML, quote numbers that are text, e.g. "1.0")'
            yield Issue(path, f"schema.{kind}", message)


def _pointer(loc: Iterable[int | str]) -> str:
    parts = (str(p).replace("~", "~0").replace("/", "~1") for p in loc)
    return "".join(f"/{p}" for p in parts)


def _fields_at(loc: tuple[int | str, ...], root: type[BaseModel]) -> list[str]:
    """Field names of the model found at `loc` (for "did you mean" suggestions)."""
    current: Any = root
    for part in loc:
        if isinstance(part, int):
            continue  # a list index: `current` is already the item type
        model = _model_of(current)
        if model is None or part not in model.model_fields:
            return []
        current = model.model_fields[part].annotation
    model = _model_of(current)
    return list(model.model_fields) if model else []


def _model_of(annotation: Any) -> type[BaseModel] | None:
    """Unwrap Annotated, Optional and list[...] down to a pydantic model, if there is one."""
    while True:
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            return annotation
        origin = get_origin(annotation)
        if origin in (Annotated, list, Union, types.UnionType):
            args = [a for a in get_args(annotation) if a is not type(None)]
            annotation = args[0] if args else None
        else:
            return None


# ------------------------------------------------------------------ cross-field rules


def _rule_issues(spec: SkillSpec, existing_names: Collection[str]) -> Iterator[Issue]:
    yield from _duplicate_ids(spec)
    yield from _broken_links(spec)
    yield from _duplicate_files(spec)
    yield from _kind_and_risk(spec)
    yield from _tools(spec)
    yield from _platform_rules(spec)
    if spec.skill.name in existing_names:
        yield Issue("/skill/name", "name_taken", "a skill with this name already exists")
    yield from _unused(spec)


def _duplicate_ids(spec: SkillSpec) -> Iterator[Issue]:
    collections: dict[str, Iterable[Any]] = {
        "/procedures": spec.procedures,
        "/outputs": spec.outputs,
        "/guardrails": spec.guardrails,
        "/knowledge/references": spec.knowledge.references,
        "/sources": spec.sources,
    }
    for base, items in collections.items():
        first: dict[str, int] = {}
        for i, item in enumerate(items):
            if item.id in first:
                yield Issue(
                    f"{base}/{i}/id",
                    "duplicate_id",
                    f'id "{item.id}" is already used by {base}/{first[item.id]}',
                )
            else:
                first[item.id] = i


def _broken_links(spec: SkillSpec) -> Iterator[Issue]:
    source_ids = {s.id for s in spec.sources}
    output_ids = {o.id for o in spec.outputs}
    reference_ids = {r.id for r in spec.knowledge.references}
    for r, ref in enumerate(spec.knowledge.references):
        for s, source_id in enumerate(ref.sources):
            if source_id not in source_ids:
                yield Issue(
                    f"/knowledge/references/{r}/sources/{s}",
                    "unknown_source",
                    f'source "{source_id}" is not defined in /sources',
                )
    for p, procedure in enumerate(spec.procedures):
        for o, output_id in enumerate(procedure.produces):
            if output_id not in output_ids:
                yield Issue(
                    f"/procedures/{p}/produces/{o}",
                    "unknown_output",
                    f'output "{output_id}" is not defined in /outputs',
                )
        for u, reference_id in enumerate(procedure.uses):
            if reference_id not in reference_ids:
                yield Issue(
                    f"/procedures/{p}/uses/{u}",
                    "unknown_reference",
                    f'reference "{reference_id}" is not defined in /knowledge/references',
                )


def _duplicate_files(spec: SkillSpec) -> Iterator[Issue]:
    files = [(f"/outputs/{i}/template", o.template) for i, o in enumerate(spec.outputs)]
    files += [
        (f"/knowledge/references/{i}/file", r.file) for i, r in enumerate(spec.knowledge.references)
    ]
    first: dict[str, str] = {}
    for path, file in files:
        if file in first:
            yield Issue(path, "duplicate_file", f'"{file}" is already used by {first[file]}')
        else:
            first[file] = path


def _kind_and_risk(spec: SkillSpec) -> Iterator[Issue]:
    guardrails = spec.guardrails
    if spec.skill.kind == "role" and not guardrails:
        yield Issue(
            "/guardrails", "role_needs_guardrail", "a role skill needs at least one guardrail"
        )
    area = spec.skill.domain.split("/", 1)[0]
    if area in HIGH_RISK_AREAS:
        musts = {g.category for g in guardrails if g.severity == "must"}
        if "disclaimer" not in musts:
            yield Issue(
                "/guardrails",
                "high_risk_needs_disclaimer",
                f"{area} is a high-risk domain: add a guardrail with category disclaimer and "
                "severity must",
            )
        if "human_review" not in musts:
            yield Issue(
                "/guardrails",
                "high_risk_needs_human_review",
                f"{area} is a high-risk domain: add a guardrail with category human_review and "
                "severity must",
            )


def _tools(spec: SkillSpec) -> Iterator[Issue]:
    required = set(spec.tools.required)
    for i, capability in enumerate(spec.tools.optional):
        if capability in required:
            yield Issue(
                f"/tools/optional/{i}",
                "tool_listed_twice",
                f'"{capability}" is already in /tools/required',
            )


def _platform_rules(spec: SkillSpec) -> Iterator[Issue]:
    for target in spec.targets:
        for word in RESERVED_NAME_WORDS.get(target, ()):
            if word in spec.skill.name:
                yield Issue(
                    "/skill/name", "reserved_name", f'{target} does not allow "{word}" in names'
                )
    texts = [("/skill/summary", spec.skill.summary)]
    texts += [(f"/triggers/use_when/{i}", t) for i, t in enumerate(spec.triggers.use_when)]
    texts += [(f"/triggers/avoid_when/{i}", t) for i, t in enumerate(spec.triggers.avoid_when)]
    for path, text in texts:
        if _XML_TAG.search(text):
            yield Issue(path, "xml_in_text", "remove XML-like tags (<...>); platforms reject them")
    limit, target = min((PLATFORM_LIMITS[t].description, t) for t in spec.targets)
    length = len(draft_description(spec))
    if length > limit:
        yield Issue(
            "/skill/summary",
            "description_too_long",
            f"summary plus triggers make a {length}-character description; {target} allows "
            f"{limit}. Shorten the summary or the triggers",
        )


def _unused(spec: SkillSpec) -> Iterator[Issue]:
    used_sources = {s for r in spec.knowledge.references for s in r.sources}
    for i, source in enumerate(spec.sources):
        if source.id not in used_sources:
            yield Issue(
                f"/sources/{i}",
                "unused_source",
                f'source "{source.id}" is not used by any reference',
                "warning",
            )
    produced = {o for p in spec.procedures for o in p.produces}
    for i, output in enumerate(spec.outputs):
        if output.id not in produced:
            yield Issue(
                f"/outputs/{i}",
                "unused_output",
                f'output "{output.id}" is not produced by any procedure',
                "warning",
            )
