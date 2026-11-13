"""The AI-09 review sheet: the top sources for each seed benchmark domain, for a person to judge.

AI-09 is done when every domain passes: at least 7 of its top 10 sources are good
(authoritative, on topic and usable) and none of its top 5 is junk. The automatic checks
below must hold before the sheet is worth reviewing. Each judged sheet keeps the verdict in
its JSON (`human_review`), and every new sheet lists those earlier verdicts as its history.
"""

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from core.knowledge.search import (
    AUTHORITATIVE_TIERS,
    PER_SITE,
    SearchProvider,
    SourceList,
    discover_sources,
    load_registry,
    site_of,
)
from core.spec.models import HIGH_RISK_AREAS
from evaluation.common import AI_ROOT, write_new_files

REPORTS_DIR = AI_ROOT / "evaluation" / "sources" / "reports"
SEED_SKILLS = AI_ROOT / "evaluation" / "benchmarks" / "seed" / "skills"
TOP = 10
PASS_GOOD = 7
JUNK_FREE_TOP = 5


@dataclass(frozen=True)
class SeedRequest:
    """The seed skill as a light request: build_queries uses its name."""

    skill_name: str
    summary: str
    expected_outputs: tuple[str, ...] = ()


def seed_domains() -> dict[str, SeedRequest]:
    """domain -> its seed skill, from evaluation/benchmarks/seed/skills (10 domains)."""
    seeds: dict[str, SeedRequest] = {}
    for path in sorted(SEED_SKILLS.glob("*.yaml")):
        data: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
        seeds[data["domain"]] = SeedRequest(data["name"], data["summary"])
    return seeds


def automatic_checks(lists: list[SourceList]) -> dict[str, bool]:
    registry = load_registry()
    sources = [(s, lst) for lst in lists for s in lst.sources]
    return {
        # The rules may leave fewer than TOP; below PASS_GOOD a domain could never pass.
        f"every domain has at least {PASS_GOOD} sources": all(
            PASS_GOOD <= len(lst.sources) <= TOP for lst in lists
        ),
        "no blocked source in any list": not any(
            b.matches(s.url, s.host, s.title) for s, _ in sources for b in registry.blocked
        ),
        f"at most {PER_SITE} pages per site, besides pins": all(
            max(_per_site(lst).values(), default=0) <= PER_SITE for lst in lists
        ),
        "nothing with excluded terms is set to crawl": not any(
            s.crawl and s.licence == "excluded-terms" for s, _ in sources
        ),
        "nothing robots.txt disallows is set to crawl": not any(
            s.crawl and s.robots == "disallowed" for s, _ in sources
        ),
        "high-risk domains crawl only official or academic sources": not any(
            s.crawl and _area(lst) in HIGH_RISK_AREAS and s.tier not in AUTHORITATIVE_TIERS
            for s, lst in sources
        ),
        f"the top {TOP} holds crawlable sources only": all(s.crawl for s, _ in sources),
    }


def _area(lst: SourceList) -> str:
    return lst.domain.split("/", 1)[0]


def _per_site(lst: SourceList) -> dict[str, int]:
    """Pages per site, not counting pins: a pin is never capped."""
    counts: dict[str, int] = {}
    for s in lst.sources:
        if not s.pinned:
            counts[site_of(s.host)] = counts.get(site_of(s.host), 0) + 1
    return counts


async def build_review(
    provider: SearchProvider | None = None, today: date | None = None
) -> tuple[str, list[SourceList], dict[str, bool]]:
    lists = [
        await discover_sources(domain, request, limit=TOP, provider=provider)
        for domain, request in seed_domains().items()
    ]
    return (today or date.today()).isoformat(), lists, automatic_checks(lists)


_SHEET = re.compile(r"sources-(\d{4}-\d{2}-\d{2})(?:-(\d+))?\.json")


def review_history(out_dir: Path = REPORTS_DIR) -> list[dict[str, Any]]:
    """The verdicts on earlier sheets (their JSON's `human_review`), oldest first."""
    sheets = []
    for path in out_dir.glob("sources-*.json"):
        match = _SHEET.fullmatch(path.name)
        if match:
            sheets.append(((match[1], int(match[2] or 1)), path))
    history = []
    for _, path in sorted(sheets):
        review = json.loads(path.read_text(encoding="utf-8")).get("human_review")
        if review:
            history.append({"sheet": path.with_suffix(".md").name, **review})
    return history


def write_review(
    day: str, lists: list[SourceList], checks: dict[str, bool], out_dir: Path = REPORTS_DIR
) -> tuple[Path, Path]:
    history = review_history(out_dir)
    data = {
        "date": day,
        "pass_rule": {"top": TOP, "good_needed": PASS_GOOD, "junk_free_top": JUNK_FREE_TOP},
        "checks": checks,
        "history": history,
        "domains": [lst.model_dump(mode="json") for lst in lists],
    }
    md_path, json_path = write_new_files(
        out_dir,
        f"sources-{day}",
        {
            ".md": render_markdown(day, lists, checks, history),
            ".json": json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        },
    )
    return md_path, json_path


def render_markdown(
    day: str,
    lists: list[SourceList],
    checks: dict[str, bool],
    history: list[dict[str, Any]] | None = None,
) -> str:
    registry = load_registry()
    passed = all(checks.values())
    lines = [
        f"# AI-09 source review ({day})",
        "",
        f"**Automatic checks: {'PASS' if passed else 'FAIL'}.** **Human review: PENDING.**",
        "",
        f"**Pass rule:** a domain passes when at least {PASS_GOOD} of its top {TOP} sources "
        f"are good and none of its top {JUNK_FREE_TOP} is junk. AI-09 is done when all "
        f"{len(lists)} domains pass.",
        "A source is **good** when it is all three:",
        "- **authoritative:** official, academic or a recognised expert source, not a blog or "
        "SEO page",
        "- **on topic:** about this domain, useful for a skill in it",
        "- **usable:** we may crawl and summarise it (see licence and robots)",
        "",
        f"Search results were recorded on 2026-10-26 (fake provider); registry "
        f"v{registry.version}. Licence notes are defaults for a legal reviewer, not legal "
        "advice. Robots `unknown` means the recording machine could not fetch robots.txt; "
        "DE-04 checks it again before crawling.",
        "In high-risk areas (legal, medical, finance) only official and academic sources are "
        "set to crawl; others stay listed with crawl: no. Legal sources name their "
        "jurisdiction.",
        "Order: a domain's pinned sources (hand-checked in the registry) come first; then "
        "sources outside the domain's jurisdiction (legal/contracts: US) and pages with no "
        "title rank below the rest, whatever their score.",
        f"Only a pin can bring into the top {TOP} an unknown site, a page with no topic word "
        "in its title or URL, or a source the registry names for other areas only. Sources "
        f"with crawl: no are listed apart, under the top {TOP}.",
        "",
        "## Automatic checks",
        "",
        "| Check | Result |",
        "|---|---|",
        *[f"| {name} | {'✅' if ok else '❌'} |" for name, ok in checks.items()],
        "",
        "## Summary",
        "",
        "Reviewer: ________  Date: ________",
        "",
        "| Domain | Good / 10 | Junk in top 5 | Pass |",
        "|---|---|---|---|",
        *[f"| {lst.domain} | __ | yes / no | pass / fail |" for lst in lists],
        "",
        *_history_lines(history or []),
    ]
    for lst in lists:
        lines += [f"## {lst.domain}", "", "Queries: " + " · ".join(f"`{q}`" for q in lst.queries)]
        lines.append("")
        for i, s in enumerate(lst.sources, 1):
            lines += [
                f"### {lst.domain} #{i}: {s.title or s.host}",
                "",
                f"<{s.url}>  ",
                f"Tier: **{s.tier}** (score {s.score}) · licence: `{s.licence}` · robots: "
                f"`{s.robots}` · crawl: {'yes' if s.crawl else 'no'}  ",
                f"Why: {'; '.join(s.reasons)}",
                "",
                "- [ ] authoritative  - [ ] on topic  - [ ] usable  → **good / bad**",
                "",
            ]
        if lst.listed:
            lines += [
                f"**Listed, not crawled ({len(lst.listed)}):** ranked, but crawl: no, so not in "
                f"the top {TOP} and never sent to DE-04.",
                "",
                *[f"- <{s.url}> {s.title or s.host} ({s.tier}): {'; '.join(s.reasons)}"
                  for s in lst.listed],
                "",
            ]  # fmt: skip
        counts: dict[str, int] = {}
        for r in lst.rejected:
            key = r.reason if not r.reason.startswith("duplicate") else "duplicate of a kept URL"
            counts[key] = counts.get(key, 0) + 1
        lines += [
            f"**{lst.domain}: good __ / {TOP} · junk in top {JUNK_FREE_TOP}: yes / no → "
            "pass / fail**",
            "",
            f"Rejected candidates ({len(lst.rejected)}), by reason (check none were wrongly "
            "dropped):",
            "",
            *[f"- {n} × {reason}" for reason, n in sorted(counts.items(), key=lambda kv: -kv[1])],
            "",
            "<details><summary>Rejected URLs</summary>",
            "",
            *[f"- {r.url} — {r.reason}" for r in lst.rejected],
            "",
            "</details>",
            "",
        ]
    return "\n".join(lines)


def _history_lines(history: list[dict[str, Any]]) -> list[str]:
    if not history:
        return []
    lines = [
        "## Review history",
        "",
        "| Sheet | Reviewer | Date | Result | Domains passing |",
        "|---|---|---|---|---|",
    ]
    for h in history:
        domains = h.get("domains", {})
        passing = sum(1 for d in domains.values() if d.get("passed"))
        lines.append(
            f"| {h['sheet']} | {h['reviewer']} | {h['date']} | "
            f"{'PASS' if h.get('passed') else 'FAIL'} | {passing} / {len(domains)} |"
        )
    lines.append("")
    for h in history:
        good = " · ".join(f"{name} {d['good']}" for name, d in h.get("domains", {}).items())
        lines += [f"**{h['sheet']}:** good per domain: {good}.", ""]
        lines += [f"- {note}" for note in h.get("notes", [])]
        lines.append("")
    return lines
