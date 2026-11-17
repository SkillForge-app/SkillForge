"""DE-08: the public SKILL.md corpus.

`GitHubClient` is the interface to GitHub (a real client needs the network, a token and OPS-09). `CorpusCollector` applies the licence
policy of `skillforge_data/licensing.py`: only files with an open licence are ever stored.
"""
from .collector import CorpusCollector, CorpusReport
from .github import GitHubClient, SkillFileHit

__all__ = ["CorpusCollector", "CorpusReport", "GitHubClient", "SkillFileHit"]
