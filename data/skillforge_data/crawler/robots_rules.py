"""The rules of one robots.txt file, read as RFC 9309 says (what `urllib.robotparser` does not do).

- Groups: a group starts with one or more `User-agent` lines; the rules after them belong to it. The group whose agent is our product
  token (`SkillForgeBot`, the word the User-Agent header starts with; case-insensitive, whole token) is used; without one, the `*` group; without that, everything is allowed. Several groups for
  the same agent are joined.
- A rule is `Allow: <path>` or `Disallow: <path>`. In a path, `*` matches any run of characters and a final `$` means "the end of the
  URL's path and query". Any other `$` is a plain character. A path that does not start with `/` or `*` is ignored. An empty
  `Disallow:` allows everything.
- The URL is matched as `path` plus `?query`. Of all the rules that match, **the longest one wins** (the length of its path as written),
  whatever its place in the file; when an Allow and a Disallow are equally long, **Allow wins**. No matching rule means allowed.
- `Crawl-delay` is not in the RFC; the first value found in the used group(s) is kept (a number of seconds).

Matching uses plain string searches, not regular expressions, so a hostile file cannot make it slow with many `*`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

_PERCENT = re.compile(r"%[0-9a-fA-F]{2}")


def _normalise(text: str) -> str:
    """Upper-case the hex digits of percent escapes, so `%2f` and `%2F` are the same."""
    return _PERCENT.sub(lambda m: m.group(0).upper(), text)


@dataclass(frozen=True)
class _Rule:
    allow: bool
    pattern: str                      # as written, without the final `$`
    anchored: bool                    # the pattern ended with `$`
    length: int                       # the length of the path as written (the longest rule wins)
    parts: tuple[str, ...]            # the pattern cut at every `*`

    def matches(self, text: str) -> bool:
        first = self.parts[0]
        if not text.startswith(first):
            return False
        pos = len(first)
        if len(self.parts) == 1:
            return len(text) == len(first) if self.anchored else True
        for part in self.parts[1:-1]:
            found = text.find(part, pos)
            if found < 0:
                return False
            pos = found + len(part)
        last = self.parts[-1]
        if self.anchored:
            return len(text) - len(last) >= pos and text.endswith(last)
        return text.find(last, pos) >= 0


def _rule(allow: bool, value: str) -> _Rule | None:
    value = _normalise(value)
    if not value or value[0] not in "/*":
        return None                                   # an empty Disallow, or a path we cannot read: no rule
    anchored = value.endswith("$")
    pattern = value[:-1] if anchored else value
    return _Rule(allow, pattern, anchored, len(value), tuple(pattern.split("*")))


class RobotsRules:
    def __init__(self, rules: list[_Rule] | None = None, crawl_delay: float | None = None) -> None:
        self._rules = rules or []
        self.crawl_delay = crawl_delay

    @classmethod
    def empty(cls) -> RobotsRules:
        """No rules: everything is allowed."""
        return cls()

    @classmethod
    def parse(cls, text: str, product_token: str) -> RobotsRules:
        groups: list[tuple[list[str], list[_Rule], list[float]]] = []
        after_agent = False                          # the previous useful line was a User-agent line
        for raw in text.lstrip("﻿").splitlines():
            line = raw.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            field, value = (part.strip() for part in line.split(":", 1))
            field = field.lower()
            if field == "user-agent":
                if after_agent and groups:
                    groups[-1][0].append(value.lower())
                else:
                    groups.append(([value.lower()], [], []))
                after_agent = True
            elif field in ("allow", "disallow", "crawl-delay") and groups:
                after_agent = False
                if field == "crawl-delay":
                    try:
                        delay = float(value)
                    except ValueError:
                        continue
                    if delay >= 0:
                        groups[-1][2].append(delay)
                elif (rule := _rule(field == "allow", value)) is not None:
                    groups[-1][1].append(rule)
        token = product_token.lower()
        chosen = [g for g in groups if token in g[0]] or [g for g in groups if "*" in g[0]]
        rules = [rule for g in chosen for rule in g[1]]
        delays = [d for g in chosen for d in g[2]]
        return cls(rules, delays[0] if delays else None)

    def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        target = _normalise((parts.path or "/") + (f"?{parts.query}" if parts.query else ""))
        best: _Rule | None = None
        for rule in self._rules:
            if rule.matches(target) and (best is None or (rule.length, rule.allow) > (best.length, best.allow)):
                best = rule
        return True if best is None else best.allow
