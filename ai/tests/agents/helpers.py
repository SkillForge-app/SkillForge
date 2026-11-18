import json
from collections.abc import Mapping, Sequence
from typing import Any, TypeVar

from pydantic import BaseModel

from core.analysis import AnalyzedRequest
from core.llm import load_prompt
from core.pipeline import example_request, example_spec

T = TypeVar("T", bound=BaseModel)


def good_spec() -> dict[str, Any]:
    """A valid SkillSpec (the ai-engineer example) as JSON-ready data."""
    data: dict[str, Any] = json.loads(example_spec("ai-engineer").model_dump_json())
    return data


def bad_spec() -> dict[str, Any]:
    """Valid per field, but cites a source that does not exist (cross-field error)."""
    data = good_spec()
    data["knowledge"]["references"].append(
        {"id": "extra", "file": "references/extra.md", "sources": ["src-missing"]}
    )
    return data


def screened(name: str = "ai-engineer", **changes: Any) -> AnalyzedRequest:
    data = json.loads(example_request(name).model_dump_json())
    data.update(changes)
    return AnalyzedRequest.model_validate_json(json.dumps(data))


class ScriptedGateway:
    """Returns the next scripted output (or raises it) per prompt id; records every call."""

    def __init__(self, script: Mapping[str, Sequence[Any]]) -> None:
        self.script = {k: list(v) for k, v in script.items()}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def complete(
        self,
        prompt_id: str,
        inputs: Mapping[str, Any],
        output_model: type[T],
        *,
        model_role: str | None = None,
    ) -> T:
        load_prompt(prompt_id).render(inputs)  # the real prompt must accept the inputs
        self.calls.append((prompt_id, dict(inputs)))
        item = self.script[prompt_id].pop(0)
        if isinstance(item, Exception):
            raise item
        return output_model.model_validate_json(json.dumps(item))

    async def embed(
        self, texts: Sequence[str], *, model_role: str = "embedding"
    ) -> list[list[float]]:
        raise NotImplementedError

    def prompts(self) -> list[str]:
        return [p for p, _ in self.calls]
