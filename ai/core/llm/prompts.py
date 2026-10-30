"""Prompt files: format, loader and renderer (AI-03, contract A2).

A prompt lives at `prompts/<area>/<name>.md`; its prompt_id is `<area>/<name>`.

    ---
    id: analysis/request
    version: 1
    model_role: analysis
    description: Classify a skill request and extract fields
    inputs: [request_text, platform]
    ---
    # system
    You are ...
    # user
    {{ request_text }}

The lines `# system` (optional) and `# user` are reserved: they split the body into chat
messages. Each section is a Jinja2 template; every variable it uses must be a declared input.

Every content change needs a `version` bump; core/llm/prompt_lock.py enforces it in CI.
"""

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import jinja2
import jinja2.meta
import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from core.llm.errors import PromptFormatError, PromptInputError, PromptNotFound

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"

PROMPT_ID = re.compile(r"^[a-z0-9_]+(/[a-z0-9_-]+)+$")
_HEADING = re.compile(r"^# (system|user)[ \t]*$", re.MULTILINE)
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_ENV = jinja2.Environment(undefined=jinja2.StrictUndefined, autoescape=False)

Message = dict[str, str]


class PromptMeta(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=PROMPT_ID.pattern)
    version: int = Field(ge=1)
    model_role: str = "default"
    description: str
    inputs: tuple[str, ...] = ()

    @field_validator("inputs")
    @classmethod
    def _check_inputs(cls, inputs: tuple[str, ...]) -> tuple[str, ...]:
        bad = [name for name in inputs if not _IDENTIFIER.match(name)]
        if bad:
            raise ValueError(f"inputs must be Python identifiers: {bad}")
        if len(set(inputs)) != len(inputs):
            raise ValueError("inputs must be unique")
        return inputs


@dataclass(frozen=True)
class Prompt:
    meta: PromptMeta
    sha256: str
    sections: tuple[tuple[str, jinja2.Template], ...]

    @property
    def id(self) -> str:
        return self.meta.id

    @property
    def version(self) -> int:
        return self.meta.version

    def render(self, inputs: Mapping[str, Any]) -> list[Message]:
        """Render to chat messages. Inputs must match the declared inputs exactly."""
        missing = sorted(set(self.meta.inputs) - set(inputs))
        unknown = sorted(set(inputs) - set(self.meta.inputs))
        if missing or unknown:
            raise PromptInputError(f"{self.id}: missing inputs {missing}, unknown inputs {unknown}")
        try:
            return [
                {"role": role, "content": template.render(**inputs).strip()}
                for role, template in self.sections
            ]
        except jinja2.UndefinedError as exc:
            raise PromptInputError(f"{self.id}: {exc.message}") from None


def parse_prompt(text: str, prompt_id: str) -> Prompt:
    """Parse prompt file text. Line endings are normalised so the hash is the same on Windows."""
    text = text.replace("\r\n", "\n")
    if not text.startswith("---\n"):
        raise PromptFormatError(f"{prompt_id}: file must start with '---' frontmatter")
    end = text.find("\n---\n", 3)
    if end == -1:
        raise PromptFormatError(f"{prompt_id}: frontmatter is not closed with '---'")
    try:
        meta = PromptMeta.model_validate(yaml.safe_load(text[4:end]))
    except (yaml.YAMLError, ValidationError) as exc:
        raise PromptFormatError(f"{prompt_id}: bad frontmatter: {exc}") from None
    if meta.id != prompt_id:
        raise PromptFormatError(f"{prompt_id}: frontmatter id {meta.id!r} does not match path")

    parts = _HEADING.split(text[end + 5 :])
    if parts[0].strip():
        raise PromptFormatError(f"{prompt_id}: text before the first '# system' or '# user'")
    names = parts[1::2]
    if names not in (["user"], ["system", "user"]):
        raise PromptFormatError(
            f"{prompt_id}: body must be an optional '# system' section then one '# user' section"
        )

    sections = []
    used: set[str] = set()
    for role, source in zip(names, parts[2::2], strict=True):
        source = source.strip()
        if not source:
            raise PromptFormatError(f"{prompt_id}: '# {role}' section is empty")
        try:
            used |= jinja2.meta.find_undeclared_variables(_ENV.parse(source))
            sections.append((role, _ENV.from_string(source)))
        except jinja2.TemplateSyntaxError as exc:
            raise PromptFormatError(f"{prompt_id}: template error in '# {role}': {exc}") from None
    undeclared = sorted(used - set(meta.inputs))
    unused = sorted(set(meta.inputs) - used)
    if undeclared or unused:
        raise PromptFormatError(
            f"{prompt_id}: template uses undeclared inputs {undeclared}, "
            f"declares unused inputs {unused}"
        )
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return Prompt(meta=meta, sha256=digest, sections=tuple(sections))


def load_prompt(prompt_id: str, root: Path | None = None) -> Prompt:
    """Load a prompt by id from `root` (default: the repo's prompts/ folder). Cached."""
    if not PROMPT_ID.match(prompt_id):
        raise PromptNotFound(f"invalid prompt_id {prompt_id!r}; expected '<area>/<name>'")
    return _load_cached(prompt_id, (root or PROMPTS_DIR).resolve())


@cache
def _load_cached(prompt_id: str, root: Path) -> Prompt:
    path = root / f"{prompt_id}.md"
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise PromptNotFound(f"no prompt file for {prompt_id!r} under {root}") from None
    return parse_prompt(text, prompt_id)


def clear_prompt_cache() -> None:
    _load_cached.cache_clear()
