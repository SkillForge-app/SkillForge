"""The interface to GitHub that the collector needs.

There is no real implementation yet: it needs the network, an API token (a secret that DevOps provides) and the scraping network of
OPS-09. Tests use a fake. A real client must send our identified user agent and obey the rate limits of GitHub; the collector adds its own
pause between calls.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class SkillFileHit:
    """One `SKILL.md` found by a search."""

    repo: str          # "owner/name"
    path: str          # path of the file inside the repository
    url: str           # the stable web URL of the file; it is what `sources.url` stores (http or https)


class GitHubClient(Protocol):
    def search_skill_files(self, query: str, *, page: int) -> list[SkillFileHit]:
        """One page of results for files named SKILL.md. An empty list means there are no more pages."""
        ...

    def repo_licence(self, repo: str) -> str | None:
        """The SPDX id GitHub reports for the repository (its LICENSE file), or None when it has none or does not know."""
        ...

    def fetch_file(self, hit: SkillFileHit) -> bytes:
        """The content of the file. Only called for files whose repository licence is allowed."""
        ...
