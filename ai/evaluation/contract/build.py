"""Builds the generated files of the frontend contract (docs/ai/frontend-contract/).

Everything here runs the real code: RealPipeline over a FakeGateway (whose model answers are
the fixture files in tests/fixtures/llm/ or the examples in ai/examples/), FakePipeline, the AI-16
harness with a fake answer/judge gateway, and check_gap over the fixture skill cards. Tables are
read from the code (Literal types, constants, the validator's Issue calls), with the line they
come from.
"""

import ast
import hashlib
import json
import os
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any, TypeVar, get_args

from pydantic import BaseModel

from core.analysis import AnalyzedRequest, gap_checker
from core.analysis import types as analysis_types
from core.analysis.gap_checker import (
    FixtureSkillIndex,
    GapCheck,
    IndexInfo,
    SkillCard,
    check_gap,
    decide,
    load_cards,
    load_settings,
)
from core.knowledge import extract
from core.llm import FakeGateway, LLMUnavailable, load_prompt, use_fake
from core.llm.errors import ConfigError, DeadlineExceeded, LLMRefused
from core.llm.gateway import BACKEND_ENV
from core.pipeline import (
    ProgressEvent,
    RealPipeline,
    StepResult,
    example_request,
    example_spec,
    interface,
)
from core.pipeline.fake import _unanswered
from core.spec import SPEC_VERSION, SkillSpec, draft_description
from evaluation.harness import evaluate as harness
from evaluation.harness.data import SkillBenchmark, load_skill
from evaluation.harness.evaluate import GeneratedAnswer, JudgeResult, run_benchmark, write_report

T = TypeVar("T", bound=BaseModel)

AI_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = AI_ROOT / "docs" / "ai" / "frontend-contract"
LLM_FIXTURES = AI_ROOT / "tests" / "fixtures" / "llm"
GAP_CARDS = AI_ROOT / "tests" / "fixtures" / "gap" / "skills.yaml"
SEED_RELEASE = AI_ROOT / "evaluation" / "benchmarks" / "seed" / "releases" / "1.0.0"
HARNESS_SCHEMA = AI_ROOT / "evaluation" / "harness" / "report.schema.json"
SPEC_SCHEMA = AI_ROOT / "core" / "spec" / "schema.json"
GAP_REQUESTS = ("ai-engineer", "marketing-strategist", "review-nda")
SIMILAR_REQUEST = "review-nda"  # checked again without its own card: a related skill remains
GAP_PREFIX = "examples/gap-"
# Stamped with the clock by the code, so `check` ignores them; everything else must match.
VOLATILE_KEYS = frozenset({"created", "latency_ms"})
AI16_SKILL = "ai-engineer"
AI16_PROMPTS = 2

Files = dict[str, Any]  # path under OUT_DIR -> JSON data (a list of lines for .jsonl)


# ------------------------------------------------------------------ helpers


def _json(model: BaseModel) -> Any:
    return json.loads(model.model_dump_json())


def _fixture(path: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((LLM_FIXTURES / path).read_text(encoding="utf-8"))
    return data


def _rel(path: Path) -> str:
    return path.resolve().relative_to(AI_ROOT).as_posix()


def _line(module_path: Path, name: str) -> str:
    """`ai/...:<line>` of the top-level definition or assignment of `name` in a module."""
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    for node in tree.body:
        defines = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        if isinstance(node, defines) and node.name == name:
            return f"ai/{_rel(module_path)}:{node.lineno}"
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        if any(isinstance(t, ast.Name) and t.id == name for t in targets):
            return f"ai/{_rel(module_path)}:{node.lineno}"
    raise LookupError(f"{name} is not defined at the top of {module_path}")


def _module_path(module: Any) -> Path:
    return Path(module.__file__)


def _pattern(node: ast.expr) -> str | None:
    """A string constant as is; an f-string with each placeholder as <expression>."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts = []
        for value in node.values:
            if isinstance(value, ast.Constant):
                parts.append(str(value.value))
            elif isinstance(value, ast.FormattedValue):
                parts.append(f"<{ast.unparse(value.value)}>")
        return "".join(parts)
    return None


@contextmanager
def _env(**values: str | None) -> Iterator[None]:
    saved = {key: os.environ.get(key) for key in values}
    try:
        for key, value in values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


# ------------------------------------------------------------------ pipeline examples


async def _design(
    analyzed: AnalyzedRequest, gateway: FakeGateway, existing_names: Sequence[str] = ()
) -> tuple[StepResult[SkillSpec], list[ProgressEvent]]:
    events: list[ProgressEvent] = []
    with use_fake(gateway):
        result = await RealPipeline().design(
            analyzed, existing_names=existing_names, on_progress=events.append
        )
    return result, events


def _with_events(files: Files, stem: str, run: tuple[StepResult[Any], list[ProgressEvent]]) -> None:
    result, events = run
    files[f"examples/{stem}.result.json"] = _json(result)
    files[f"examples/{stem}.events.json"] = [_json(e) for e in events]


async def pipeline_examples() -> Files:
    files: Files = {}
    marketing = example_request("marketing-strategist")  # 4 questions, 4 answers, screened
    first_pass = _unanswered(marketing)  # the same request before the answers
    analysis = _fixture("analysis/request.json")
    questions = [q.model_dump(mode="json") for q in marketing.questions]

    # AI-05: analyze. The analysis model's answer is the fixture, with the example's questions.
    gateway = FakeGateway()
    gateway.register(
        "analysis/request", {**analysis, "needs_clarification": True, "questions": questions}
    )
    with use_fake(gateway):
        needs_input = await RealPipeline().analyze(marketing.request)
    files["examples/analyze-needs-input.result.json"] = _json(needs_input)
    with use_fake(FakeGateway()):
        files["examples/analyze-ok.result.json"] = _json(
            await RealPipeline().analyze(marketing.request)
        )
        files["examples/analyze-invalid-request.result.json"] = _json(
            await RealPipeline().analyze("")
        )
    gateway = FakeGateway()
    gateway.register(
        "analysis/safety",
        {**_fixture("analysis/safety.json"), "verdict": "block", "category": "fraud_scams"},
    )
    with use_fake(gateway):
        files["examples/analyze-blocked.result.json"] = _json(
            await RealPipeline().analyze(marketing.request)
        )

    # AI-05: clarify, on the first pass above.
    assert needs_input.value is not None
    asked = needs_input.value
    with use_fake(FakeGateway()):
        files["examples/clarify-answered.result.json"] = _json(
            await RealPipeline().clarify(asked, marketing.answers)
        )
        files["examples/clarify-all-skipped.result.json"] = _json(
            await RealPipeline().clarify(asked, [])
        )
        twice = [marketing.answers[0], marketing.answers[0]]
        files["examples/clarify-invalid-request.result.json"] = _json(
            await RealPipeline().clarify(asked, twice)
        )

    # design: the architect's answers are the fixtures (a review-nda SkillSpec).
    review = example_request("review-nda")
    _with_events(files, "design-ok", await _design(review, FakeGateway()))
    _with_events(
        files,
        "design-invalid-spec",
        await _design(review, FakeGateway(), existing_names=[review.skill_name or ""]),
    )
    gateway = FakeGateway()
    gateway.register_error("architect/generate", DeadlineExceeded("step deadline passed"))
    _with_events(files, "design-retry-later", await _design(review, gateway))
    gateway = FakeGateway()
    gateway.register_error("architect/generate", LLMRefused("refused"))
    _with_events(files, "design-blocked", await _design(review, gateway))
    _with_events(files, "design-needs-input-no-value", await _design(first_pass, FakeGateway()))
    return files


# ------------------------------------------------------------------ AI-16 examples


class _HarnessGateway:
    """Fake answer and judge models: the with-skill answer passes every rubric item, the
    without-skill answer only the non-critical ones. `fail_request` makes the with-skill answer
    for that request raise LLMUnavailable (a provider outage)."""

    def __init__(self, benchmark: SkillBenchmark, fail_request: str | None = None) -> None:
        self.critical = {item.id for item in benchmark.rubric if item.critical}
        self.fail_request = fail_request

    async def complete(
        self,
        prompt_id: str,
        inputs: Mapping[str, Any],
        output_model: type[T],
        *,
        model_role: str | None = None,
    ) -> T:
        load_prompt(prompt_id).render(inputs)  # the real prompts must accept the inputs
        result: BaseModel
        if prompt_id == harness.ANSWER_PROMPT:
            with_skill = bool(inputs["skill_instructions"])
            if with_skill and inputs["request"] == self.fail_request:
                raise LLMUnavailable("simulated outage")
            arm = "with the skill" if with_skill else "without the skill"
            result = GeneratedAnswer(answer=f"Fake answer {arm}.")
        else:
            passed_all = "with the skill" in inputs["answer"]
            result = JudgeResult.model_validate(
                {
                    "scores": [
                        {
                            "rubric_id": item["id"],
                            "passed": passed_all or item["id"] not in self.critical,
                            "rationale": "Fake judge.",
                        }
                        for item in json.loads(inputs["rubric"])
                    ]
                }
            )
        return output_model.model_validate_json(result.model_dump_json())

    async def embed(
        self, texts: Sequence[str], *, model_role: str = "embedding"
    ) -> list[list[float]]:
        raise NotImplementedError


async def _benchmark_files(
    stem: str, benchmark: SkillBenchmark, gateway: _HarnessGateway, instructions: str
) -> Files:
    with _env(**{BACKEND_ENV: "fake"}), use_fake(gateway):  # type: ignore[arg-type]
        report, results = await run_benchmark(benchmark, instructions, live=False, concurrency=1)
    with tempfile.TemporaryDirectory() as tmp:
        out = write_report(report, results, Path(tmp) / "run")
        saved = json.loads((out / "report.json").read_text(encoding="utf-8"))
        lines = (out / "predictions.jsonl").read_text(encoding="utf-8").splitlines()
    return {
        f"examples/{stem}.report.json": saved,
        f"examples/{stem}.predictions.jsonl": [json.loads(line) for line in lines],
    }


async def ai16_examples() -> Files:
    full = load_skill(SEED_RELEASE, AI16_SKILL)
    benchmark = SkillBenchmark(
        dataset=full.dataset,
        version=full.version,
        dataset_sha256=full.dataset_sha256,
        skill=full.skill,
        prompts=full.prompts[:AI16_PROMPTS],
        rubric=full.rubric,
    )
    instructions = draft_description(example_spec(AI16_SKILL))
    files = await _benchmark_files(
        "ai16-benchmark-completed", benchmark, _HarnessGateway(benchmark), instructions
    )
    failing = _HarnessGateway(benchmark, fail_request=benchmark.prompts[0].text)
    files.update(
        await _benchmark_files(
            "ai16-benchmark-completed-with-errors", benchmark, failing, instructions
        )
    )
    return files


def check_ai16(files: Files) -> list[str]:
    """Every AI-16 example object and JSONL line is valid against report.schema.json."""
    from jsonschema import Draft202012Validator  # dev extra: the check is a dev tool

    validator = Draft202012Validator(json.loads(HARNESS_SCHEMA.read_text(encoding="utf-8")))
    problems = []
    for path, data in files.items():
        if not path.startswith("examples/ai16-"):
            continue
        for item in data if isinstance(data, list) else [data]:
            for error in validator.iter_errors(item):
                problems.append(f"{path}: {error.message}")
    return problems


# ------------------------------------------------------------------ gap examples


class _OtherModelIndex:
    """An index built with another embedding model: check_gap must refuse it."""

    def __init__(self, cards: Sequence[SkillCard]) -> None:
        self.cards = list(cards)

    def info(self) -> IndexInfo:
        return IndexInfo(len(self.cards), "local/another-embedding-model", 768)

    async def search(self, vector: Sequence[float], k: int) -> list[tuple[SkillCard, float]]:
        raise AssertionError("never searched: the model check comes first")


async def gap_examples() -> Files:
    """check_gap with the local embedding model (no key, no network once downloaded)."""
    files: Files = {}
    index = FixtureSkillIndex(GAP_CARDS)
    for name in GAP_REQUESTS:
        result = await check_gap(example_request(name), indexes=[index])
        files[f"{GAP_PREFIX}{name}.json"] = _json(result)
    # A related skill but not the same one: the request whose own card is left out.
    others = [c for c in load_cards(GAP_CARDS) if c.id != f"registry:{SIMILAR_REQUEST}"]
    files[f"{GAP_PREFIX}{SIMILAR_REQUEST}-without-its-card.json"] = _json(
        await check_gap(example_request(SIMILAR_REQUEST), indexes=[FixtureSkillIndex(cards=others)])
    )
    empty = FixtureSkillIndex(cards=[])
    files[f"{GAP_PREFIX}empty-index.json"] = _json(
        await check_gap(example_request(GAP_REQUESTS[0]), indexes=[empty])
    )
    try:
        await check_gap(
            example_request(GAP_REQUESTS[0]), indexes=[_OtherModelIndex(load_cards(GAP_CARDS))]
        )
    except ConfigError as exc:
        files[f"{GAP_PREFIX}index-mismatch.error.json"] = {
            "error": type(exc).__name__,
            "message": str(exc),
        }
    else:
        raise AssertionError("check_gap accepted an index built with another model")
    return files


def check_gap_files(directory: Path = OUT_DIR) -> list[str]:
    """The saved gap examples are valid GapChecks whose verdict decide() would give."""
    problems = []
    settings = load_settings()
    paths = sorted((directory / "examples").glob("gap-*.json"))
    without = f"{SIMILAR_REQUEST}-without-its-card"
    expected = {f"gap-{n}.json" for n in (*GAP_REQUESTS, "empty-index", without)}
    expected.add("gap-index-mismatch.error.json")
    missing = expected - {p.name for p in paths}
    if missing:
        problems.append(f"missing gap examples: {sorted(missing)}; run export --gap")
    for path in paths:
        if path.name.endswith(".error.json"):
            continue
        check = GapCheck.model_validate_json(path.read_text(encoding="utf-8"))
        name = path.name.removeprefix("gap-").removesuffix(".json")
        requests = {"empty-index": GAP_REQUESTS[0], without: SIMILAR_REQUEST}
        request = example_request(requests.get(name, name))
        top = (check.matches[0].skill, check.matches[0].score) if check.matches else None
        if check.verdict != decide(request, top, settings):
            problems.append(f"{path.name}: the verdict is not what decide() gives")
        if (check.exists_threshold, check.similar_threshold) != (
            settings.exists,
            settings.similar,
        ):
            problems.append(f"{path.name}: thresholds differ from gap_checker.yaml")
    return problems


# ------------------------------------------------------------------ tables and schemas


def _literal(module: Any, name: str) -> dict[str, Any]:
    values = list(get_args(getattr(module, name)))
    return {"values": values, "source": _line(_module_path(module), name)}


def _error_codes(module: Any) -> list[dict[str, str]]:
    """Every `error_code=` given in the module, and every string _retry_code returns."""
    path = _module_path(module)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "error_code":
            pattern = _pattern(node.value)
            if pattern is not None:
                found.setdefault(pattern, f"ai/{_rel(path)}:{node.value.lineno}")
        if isinstance(node, ast.FunctionDef) and node.name == "_retry_code":
            for sub in ast.walk(node):
                if isinstance(sub, ast.Return) and sub.value is not None:
                    pattern = _pattern(sub.value)
                    if pattern is not None:
                        found.setdefault(pattern, f"ai/{_rel(path)}:{sub.lineno}")
    return [{"code": code, "source": source} for code, source in found.items()]


def _validator_codes() -> list[dict[str, str]]:
    """The `code` of every Issue(...) the SkillSpec validator can return."""
    from core.spec import validator

    path = _module_path(validator)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: dict[str, str] = {}
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "Issue"
            and len(node.args) >= 2
        ):
            pattern = _pattern(node.args[1])
            if pattern is not None:
                found.setdefault(pattern, f"ai/{_rel(path)}:{node.lineno}")
    return [{"code": code, "source": source} for code, source in sorted(found.items())]


def _messages() -> dict[str, Any]:
    path = _module_path(interface)
    return {
        name: {"text": getattr(interface, name), "source": _line(path, name)}
        for name in sorted(vars(interface))
        if name.endswith("_MESSAGE") and isinstance(getattr(interface, name), str)
    }


def _closing_events() -> list[dict[str, Any]]:
    cases = [
        ("ok", None),
        ("needs_input", "open_questions"),
        ("blocked", "blocked.other"),
        ("retry_later", "provider_unavailable"),
        ("retry_later", "deadline_exceeded"),
        ("failed", "budget_exceeded"),
        ("failed", "not_screened"),
        ("failed", "invalid_spec"),
    ]
    rows = []
    for status, code in cases:
        stage, message = interface.closing_event(status, code)  # type: ignore[arg-type]
        rows.append({"status": status, "error_code": code, "stage": stage, "message": message})
    return rows


def _lf_sha256(path: Path) -> str:
    """sha256 of the file as Git stores it (LF line endings), whatever the checkout does."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def tables() -> Files:
    settings = load_settings()
    text_limit = get_args(analysis_types.RequestText)[1]
    answer_limit = get_args(analysis_types.Answer.model_fields["text"].annotation)[0]
    return {
        "tables.json": {
            "pipeline": {
                "pipeline_version": interface.PIPELINE_VERSION,
                "StepName": _literal(interface, "StepName"),
                "StepStatus": _literal(interface, "StepStatus"),
                "Stage": _literal(interface, "Stage"),
                "error_codes": _error_codes(interface),
                "messages": _messages(),
                "closing_event": {
                    "source": _line(_module_path(interface), "closing_event"),
                    "rows": _closing_events(),
                },
            },
            "analysis": {
                "QuestionTopic": _literal(analysis_types, "QuestionTopic"),
                "HarmCategory": _literal(analysis_types, "HarmCategory"),
                "SafetyCondition": _literal(analysis_types, "SafetyCondition"),
                "questions": {
                    "min": analysis_types.MIN_QUESTIONS,
                    "max": analysis_types.MAX_QUESTIONS,
                    "source": _line(_module_path(analysis_types), "MIN_QUESTIONS"),
                },
                "request_text_max_chars": text_limit.max_length,
                "answer_text_max_chars": get_args(answer_limit)[1].max_length,
            },
            "spec_validator": {"issue_codes": _validator_codes()},
            "gap": {
                "Verdict": _literal(gap_checker, "Verdict"),
                "SkillSource": _literal(gap_checker, "SkillSource"),
                "settings": {
                    "version": settings.version,
                    "exists": settings.exists,
                    "similar": settings.similar,
                    "same_area_for_exists": settings.same_area_for_exists,
                    "tuned_on": settings.tuned_on,
                    "source": f"ai/{_rel(gap_checker.SETTINGS_PATH)}",
                },
            },
            "extraction": {
                "Reason": _literal(extract, "Reason"),
                "EXTRACTION_VERSION": {
                    "value": extract.EXTRACTION_VERSION,
                    "source": _line(_module_path(extract), "EXTRACTION_VERSION"),
                },
                "default_fingerprint": extract.ExtractConfig().fingerprint(),
            },
            "ai16": {
                "error_codes": sorted({*harness._ERROR_CODES.values(), "unexpected_error"}),
                "source": _line(_module_path(harness), "_ERROR_CODES"),
            },
            "skillspec": {
                "spec_version": SPEC_VERSION,
                "schema": f"ai/{_rel(SPEC_SCHEMA)}",
                "schema_sha256": _lf_sha256(SPEC_SCHEMA),
            },
        }
    }


def _schema(model: Any, title: str) -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        **model.model_json_schema(mode="serialization"),
        "title": title,
    }


def schemas() -> Files:
    return {
        "schemas/step-result-analyzed-request.schema.json": _schema(
            StepResult[AnalyzedRequest], "StepResult[AnalyzedRequest]"
        ),
        "schemas/step-result-skillspec.schema.json": _schema(
            StepResult[SkillSpec], "StepResult[SkillSpec]"
        ),
        "schemas/progress-event.schema.json": _schema(ProgressEvent, "ProgressEvent"),
        "schemas/issue-record.schema.json": _schema(interface.IssueRecord, "IssueRecord"),
        "schemas/gap-check.schema.json": _schema(GapCheck, "GapCheck"),
    }


# ------------------------------------------------------------------ files


async def build(*, gap: bool = False) -> Files:
    """Every generated file; the gap examples only with gap=True (they need the local model)."""
    files: Files = {**schemas(), **tables(), **await pipeline_examples(), **await ai16_examples()}
    if gap:
        files.update(await gap_examples())
    return files


def render(data: Any, path: str) -> str:
    if path.endswith(".jsonl"):
        return "".join(json.dumps(line, ensure_ascii=False) + "\n" for line in data)
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def write(files: Files, directory: Path = OUT_DIR) -> list[Path]:
    written = []
    for path, data in sorted(files.items()):
        target = directory / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render(data, path), encoding="utf-8", newline="\n")
        written.append(target)
    return written


def _stable(data: Any) -> Any:
    if isinstance(data, dict):
        return {k: _stable(v) for k, v in data.items() if k not in VOLATILE_KEYS}
    if isinstance(data, list):
        return [_stable(v) for v in data]
    return data


def _load(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line]
    return json.loads(text)


def stale(files: Files, directory: Path = OUT_DIR) -> list[str]:
    """Generated files that are missing or differ on disk (clock-stamped fields ignored)."""
    problems = []
    for path, data in sorted(files.items()):
        target = directory / path
        if not target.is_file():
            problems.append(f"missing: {path}")
        elif _stable(_load(target)) != _stable(json.loads(json.dumps(data))):
            problems.append(f"out of date: {path}")
    return problems
