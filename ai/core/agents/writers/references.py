"""Reference writer (AI-13): one `references/<id>.md` per SkillSpec reference, every claim cited.

    files = await write_references(result.spec, result.passages, result.evidence)

For each reference the model gets only the passages its sources came from (the Architect's
`evidence`), wrapped as untrusted data (AI-19 layer 3), and returns structure, not Markdown:
sections of claims, each claim citing chunk ids. The code then checks every claim:
- it cites at least one chunk, and only chunks of this reference's evidence;
- it does not copy a passage (copied_fields: 12+ consecutive words);
- it has no URL or domain (citations are rendered by the code, never written by the model);
- AI-19's screen_text finds no override, role-marker, secret or exfiltration text.
A failing claim gets one repair call; still failing, it is dropped and counted. The Markdown is
rendered by the code, so a file can never hold an uncited claim (AI-13's done-when).
"""

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import Field

from core.agents.architect import copied_fields
from core.knowledge import UNTRUSTED_DATA_RULE, Passage, screen_text, wrap_passages
from core.knowledge.types import ChunkId
from core.llm import LLMOutputInvalid, LLMRefused, LLMUnavailable, complete
from core.spec import Issue, SkillSpec
from core.spec.models import Reference, Source, SpecModel, Text, Title

PROMPT = "writers/references"
MAX_CALLS = 2  # one write, one repair
# screen_text categories that make a claim an error (the same split as check_spec's errors).
ERROR_CATEGORIES = frozenset({"override", "role_marker", "multilingual", "secret", "exfiltration"})
_URL = re.compile(
    r"\bhttps?://\S+|\bwww\.\S+|\b(?:[a-z0-9-]+\.)+"
    r"(?:com|org|net|gov|edu|io|ai|dev|app|co|uk|us|info|eu|int|mil)\b",
    re.IGNORECASE,
)


class WriterUnavailable(Exception):
    """The model provider failed; retry the job later."""


class WriterRefused(Exception):
    """The model refused to write a reference file."""


# ------------------------------------------------------------------ what the model returns


class ClaimDraft(SpecModel):
    text: Text = Field(description="One factual statement, in your own words.")
    cite: list[ChunkId] = Field(
        default_factory=list, description="chunk_id of each passage that supports the claim."
    )


class SectionDraft(SpecModel):
    heading: Title
    claims: list[ClaimDraft] = Field(min_length=1, max_length=12)


class ReferenceDraft(SpecModel):
    sections: list[SectionDraft] = Field(min_length=1, max_length=6)


# ------------------------------------------------------------------ what the writer returns


@dataclass(frozen=True)
class Claim:
    section: str
    text: str
    chunk_ids: tuple[str, ...]


@dataclass(frozen=True)
class ReferenceFile:
    reference_id: str
    path: str  # references/<id>.md, as in the spec
    title: str
    markdown: str  # "" when no claim survived
    claims: tuple[Claim, ...]
    dropped: tuple[Issue, ...] = ()  # claims removed after the repair, by path and reason
    calls: int = 0
    issues: tuple[Issue, ...] = ()  # file-level problems (no evidence, no valid reply)

    @property
    def ok(self) -> bool:
        return bool(self.claims)


# ------------------------------------------------------------------ checks


def claim_issues(draft: ReferenceDraft, passages: Sequence[Passage]) -> list[Issue]:
    """Errors for claims that are uncited, cite outside the evidence, copy a passage, hold a URL
    or contain injection text. Paths are /sections/<i>/claims/<j>; messages hold no claim text."""
    allowed = {p.chunk_id for p in passages}
    issues: list[Issue] = []
    fields = []
    for i, section in enumerate(draft.sections):
        for j, claim in enumerate(section.claims):
            path = f"/sections/{i}/claims/{j}"
            fields.append((path, claim.text))
            if not claim.cite:
                issues.append(Issue(path, "uncited", "the claim cites no passage"))
            elif outside := [c for c in claim.cite if c not in allowed]:
                issues.append(
                    Issue(
                        path,
                        "cite_outside_evidence",
                        f"{len(outside)} cited chunk id(s) are not passages of this reference",
                    )
                )
            if _URL.search(claim.text):
                issues.append(Issue(path, "url_in_claim", "a URL or domain; cite instead"))
            if any(f.category in ERROR_CATEGORIES for f in screen_text(claim.text)):
                issues.append(
                    Issue(path, "injection", "text that overrides instructions or asks for data")
                )
    issues += copied_fields(fields, passages)
    return issues


# ------------------------------------------------------------------ rendering


def render(
    title: str, claims: Sequence[Claim], passages: Sequence[Passage], sources: Sequence[Source]
) -> str:
    """The reference file: sections of cited claims, then the numbered sources (one per page,
    numbered by first use). Built by the code: the model never writes a URL or a marker."""
    by_chunk = {p.chunk_id: p for p in passages}
    by_url = {str(s.url): s for s in sources}
    numbers: dict[str, int] = {}
    lines = [f"# {title}", ""]
    section = None
    for claim in claims:
        if claim.section != section:
            section = claim.section
            lines += [f"## {section}", ""]
        marks = []
        for chunk_id in claim.chunk_ids:
            url = str(by_chunk[chunk_id].source_url)
            n = numbers.setdefault(url, len(numbers) + 1)
            if f"[{n}]" not in marks:
                marks.append(f"[{n}]")
        lines.append(f"- {claim.text} {''.join(marks)}")
    lines += ["", "## Sources", ""]
    for url, n in sorted(numbers.items(), key=lambda kv: kv[1]):
        source = by_url.get(url)
        name = (source.title if source and source.title else None) or url
        retrieved = source.retrieved.isoformat() if source else ""
        lines.append(f"{n}. {name}. <{url}>" + (f" Retrieved {retrieved}." if retrieved else ""))
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------ the writer


def _inputs(
    spec: SkillSpec,
    ref: Reference,
    passages: Sequence[Passage],
    previous: ReferenceDraft | None = None,
    issues: Sequence[Issue] = (),
) -> dict[str, Any]:
    return {
        "skill_title": spec.skill.title,
        "skill_summary": spec.skill.summary,
        "reference_title": ref.title or ref.id,
        "knowledge": wrap_passages(passages),
        "knowledge_rule": UNTRUSTED_DATA_RULE,
        "chunk_ids": [p.chunk_id for p in passages],
        "previous": json.dumps(previous.model_dump(mode="json"), indent=1) if previous else "",
        "issues": [str(i) for i in issues],
    }


async def _call(inputs: Mapping[str, Any]) -> ReferenceDraft | None:
    try:
        return await complete(PROMPT, inputs, ReferenceDraft)
    except LLMRefused as exc:  # a subclass of LLMOutputInvalid: check it first
        raise WriterRefused("the model refused to write a reference file") from exc
    except LLMOutputInvalid:
        return None
    except LLMUnavailable as exc:
        raise WriterUnavailable(f"model unavailable: {type(exc).__name__}") from exc


async def write_reference(
    spec: SkillSpec, ref: Reference, passages: Sequence[Passage]
) -> ReferenceFile:
    """One reference file from the passages of its evidence (at most MAX_CALLS model calls)."""
    path, title = ref.file, ref.title or ref.id
    if not passages:
        issue = Issue("", "no_evidence", "no retrieved passage backs this reference")
        return ReferenceFile(ref.id, path, title, "", (), issues=(issue,))
    draft = await _call(_inputs(spec, ref, passages))
    calls = 1
    issues = claim_issues(draft, passages) if draft is not None else []
    if draft is None or issues:
        repaired = await _call(_inputs(spec, ref, passages, draft, issues or _invalid()))
        calls = 2
        if repaired is not None:
            draft, issues = repaired, claim_issues(repaired, passages)
    if draft is None:
        return ReferenceFile(ref.id, path, title, "", (), calls=calls, issues=tuple(_invalid()))
    bad = {i.path: i for i in issues}
    claims: list[Claim] = []
    dropped: list[Issue] = []
    for i, section in enumerate(draft.sections):
        for j, claim in enumerate(section.claims):
            problem = bad.get(f"/sections/{i}/claims/{j}")
            if problem is not None:
                dropped.append(problem)
            else:
                claims.append(Claim(section.heading, claim.text, tuple(dict.fromkeys(claim.cite))))
    markdown = render(title, claims, passages, spec.sources) if claims else ""
    return ReferenceFile(ref.id, path, title, markdown, tuple(claims), tuple(dropped), calls)


def _invalid() -> list[Issue]:
    return [Issue("", "llm_output_invalid", "the reply did not match the reference schema")]


async def write_references(
    spec: SkillSpec,
    passages: Sequence[Passage],
    evidence: Mapping[str, Sequence[str]],
) -> list[ReferenceFile]:
    """A file for each reference of the spec, in spec order. `passages` and `evidence` are the
    Architect's (ArchitectResult.passages / .evidence)."""
    by_chunk = {p.chunk_id: p for p in passages}
    files = []
    for ref in spec.knowledge.references:
        own = [by_chunk[c] for c in evidence.get(ref.id, ()) if c in by_chunk]
        files.append(await write_reference(spec, ref, own))
    return files


@dataclass(frozen=True)
class ReferenceSummary:
    """Counts for an evaluation report."""

    files: int = 0
    files_ok: int = 0
    claims: int = 0
    uncited: int = 0
    dropped: dict[str, int] = field(default_factory=dict)


def summarise(files: Sequence[ReferenceFile]) -> ReferenceSummary:
    from collections import Counter

    dropped = Counter(i.code for f in files for i in f.dropped)
    return ReferenceSummary(
        files=len(files),
        files_ok=sum(f.ok for f in files),
        claims=sum(len(f.claims) for f in files),
        uncited=sum(1 for f in files for c in f.claims if not c.chunk_ids),
        dropped=dict(dropped),
    )


__all__ = [
    "Claim",
    "ClaimDraft",
    "ReferenceDraft",
    "ReferenceFile",
    "ReferenceSummary",
    "SectionDraft",
    "WriterRefused",
    "WriterUnavailable",
    "claim_issues",
    "render",
    "summarise",
    "write_reference",
    "write_references",
]
