"""DE-08: licence policy. Two separate policies, decided by AI (Zeyad) for the project:

(a) Public SKILL.md files (examples we may copy from): ONLY open licences are allowed. Everything else is refused, and "no licence"
    counts as refused (without a licence all rights are reserved). `check_skill_file_licence` answers allowed or refused with a reason;
    `register_skill_file` stores url + licence of an allowed file as a `skill_md` source, so the attribution is always possible.

(b) Web pages from AI's `crawl_list()`: the list says how a site is licensed with a short label; `web_page_licence` maps the label to
    the value stored in `sources.license` / `sources.license_source` (the column accepts 'page', 'repo', 'manual', 'unknown').
    If the page itself declares a licence (crawler.license.detect_license), that wins.

Nothing here hides or shows chunks: no view depends on the licence (a decision for AI, see docs/p3-progress.md).
"""
from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from urllib.parse import urlsplit

import psycopg

from .store import upsert_source

logger = logging.getLogger("skillforge_data.licensing")

UNKNOWN = "unknown"

# ------------------------------------------------------------------------------------------ (a) SKILL.md files
OPEN_LICENCES: frozenset[str] = frozenset(
    {"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC", "CC0-1.0", "Unlicense", "CC-BY-4.0"}
)

_CANONICAL = {name.lower(): name for name in OPEN_LICENCES}
_ALIASES = {
    "apache 2.0": "Apache-2.0", "apache-2": "Apache-2.0", "apache license 2.0": "Apache-2.0", "apache license, version 2.0": "Apache-2.0",
    "bsd-3": "BSD-3-Clause", "bsd 3-clause": "BSD-3-Clause", "bsd-2": "BSD-2-Clause",
    "bsd 2-clause": "BSD-2-Clause", "cc0": "CC0-1.0", "cc by 4.0": "CC-BY-4.0", "the unlicense": "Unlicense",
    "mit license": "MIT", "isc license": "ISC",
}


@dataclass(frozen=True)
class LicenceDecision:
    allowed: bool
    license: str            # the normalised SPDX id (or expression); 'unknown' when there is none
    reason: str             # why it is allowed or refused (for logs and reports)


def normalise_licence(value: str | None) -> str:
    """'mit' -> 'MIT', 'Apache License 2.0' -> 'Apache-2.0'. Anything else is returned stripped; empty gives 'unknown'."""
    text = (value or "").strip()
    if not text or text.lower() in ("unknown", "none", "noassertion", "other", "unlicensed", "proprietary", "all rights reserved"):
        return UNKNOWN
    key = text.lower()
    return _CANONICAL.get(key) or _ALIASES.get(key) or text


def _refusal_reason(spdx: str) -> str:
    s = spdx.upper()
    if s == UNKNOWN.upper() or not s:
        return "no licence: all rights are reserved"
    if "-NC" in s or s.endswith("-NC") or "NONCOMMERCIAL" in s:
        return "non-commercial licence"
    if re.search(r"-ND\b|-ND-", s) or "NODERIV" in s:
        return "no-derivatives licence"
    if "CC-BY-SA" in s:
        return "share-alike licence (CC-BY-SA)"
    if "GPL" in s:              # GPL, LGPL, AGPL
        return "GPL-family licence"
    if s.startswith("MPL") or "MOZILLA" in s:
        return "MPL licence"
    return f"licence {spdx} is not on the open-licence list"


def check_skill_file_licence(licence: str | None) -> LicenceDecision:
    """Is a public SKILL.md file with this licence usable as an example? Default is no.

    A simple SPDX expression is read: "A OR B" is allowed when one alternative is open (the user may choose it); "A AND B" only when
    all of them are. Parentheses and WITH exceptions are not understood and are refused.
    """
    spdx = normalise_licence(licence)
    if spdx == UNKNOWN:
        return LicenceDecision(False, UNKNOWN, _refusal_reason(UNKNOWN))
    if re.search(r"[()]|\bWITH\b", spdx, re.IGNORECASE):
        return LicenceDecision(False, spdx, "licence expression not understood")
    if re.search(r"\sOR\s", spdx, re.IGNORECASE):
        parts = [normalise_licence(p) for p in re.split(r"\sOR\s", spdx, flags=re.IGNORECASE)]
        open_parts = [p for p in parts if p in OPEN_LICENCES]
        if open_parts:
            return LicenceDecision(True, spdx, f"may be used under {open_parts[0]}")
        return LicenceDecision(False, spdx, _refusal_reason(spdx))
    if re.search(r"\sAND\s", spdx, re.IGNORECASE):
        parts = [normalise_licence(p) for p in re.split(r"\sAND\s", spdx, flags=re.IGNORECASE)]
        bad = [p for p in parts if p not in OPEN_LICENCES]
        if bad:
            return LicenceDecision(False, spdx, _refusal_reason(bad[0]))
        return LicenceDecision(True, spdx, "all licences are open")
    if spdx in OPEN_LICENCES:
        return LicenceDecision(True, spdx, "open licence")
    return LicenceDecision(False, spdx, _refusal_reason(spdx))


# Phrases that identify a LICENSE file. The restricted families come first: a file that mentions two licences is read as the
# stricter one (so it is refused, never allowed by mistake).
_LICENSE_TEXT: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"GNU AFFERO GENERAL PUBLIC LICENSE", re.IGNORECASE), "AGPL-3.0-only"),
    (re.compile(r"GNU LESSER GENERAL PUBLIC LICENSE", re.IGNORECASE), "LGPL-3.0-only"),
    (re.compile(r"GNU GENERAL PUBLIC LICENSE", re.IGNORECASE), "GPL-3.0-only"),
    (re.compile(r"Mozilla Public License", re.IGNORECASE), "MPL-2.0"),
    (re.compile(r"Attribution-NonCommercial", re.IGNORECASE), "CC-BY-NC-4.0"),
    (re.compile(r"Attribution-NoDerivatives|Attribution-NoDerivs", re.IGNORECASE), "CC-BY-ND-4.0"),
    (re.compile(r"Attribution-ShareAlike", re.IGNORECASE), "CC-BY-SA-4.0"),
    (re.compile(r"CC0 1\.0 Universal", re.IGNORECASE), "CC0-1.0"),
    (re.compile(r"Creative Commons Attribution 4\.0", re.IGNORECASE), "CC-BY-4.0"),
    (re.compile(r"This is free and unencumbered software released into the public domain", re.IGNORECASE), "Unlicense"),
    (re.compile(r"Apache License\s+Version 2\.0", re.IGNORECASE), "Apache-2.0"),
    (re.compile(r"Permission is hereby granted, free of charge, to any person obtaining a copy", re.IGNORECASE), "MIT"),
    (re.compile(r"Permission to use, copy, modify, and/or distribute this software for any purpose with or without fee", re.IGNORECASE), "ISC"),
]
_BSD = re.compile(r"Redistribution and use in source and binary forms, with or without\s+modification", re.IGNORECASE)
_BSD_NAME = re.compile(r"Neither the name of", re.IGNORECASE)


def detect_licence_text(text: str) -> str:
    """The SPDX id of a LICENSE file's text, or 'unknown'. Only well-known texts are recognised; nothing is guessed."""
    for pattern, spdx in _LICENSE_TEXT:
        if pattern.search(text):
            return spdx
    if _BSD.search(text):
        return "BSD-3-Clause" if _BSD_NAME.search(text) else "BSD-2-Clause"
    return UNKNOWN


@dataclass(frozen=True)
class SkillFileRecord:
    url: str
    license: str
    source_id: uuid.UUID


def register_skill_file(conn: psycopg.Connection, url: str, licence: str | None) -> tuple[LicenceDecision, SkillFileRecord | None]:
    """Keep a public SKILL.md file as a source (`source_type = 'skill_md'`) with its url and licence, only if the licence is open.

    A refused file is NOT stored (so it can never be returned as an example); the reason is logged and returned. `licence` is an SPDX id
    (for example from the repository's metadata) or `detect_licence_text(LICENSE text)`.
    """
    decision = check_skill_file_licence(licence)
    if not decision.allowed:
        logger.info("skill file refused: %s (%s)", url, decision.reason)
        return decision, None
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError(f"not an http(s) URL: {url}")
    source_id = upsert_source(conn, url=url, host=parts.hostname.lower(), source_type="skill_md",
                              license=decision.license, license_source="repo")
    return decision, SkillFileRecord(url, decision.license, source_id)


def attribution(url: str, licence: str) -> str:
    """The line to show next to something taken from a licensed file."""
    return f"{url} ({licence})"


# ------------------------------------------------------------------------------------------ (b) web pages
@dataclass(frozen=True)
class WebLicence:
    license: str             # for sources.license: an SPDX id, a LicenseRef-..., or 'unknown'
    license_source: str      # for sources.license_source: 'manual', 'page' or 'unknown'

    @property
    def summarise_and_cite_only(self) -> bool:
        """No licence we know: the default is to summarise and cite, not to copy."""
        return self.license == UNKNOWN


# The labels of crawl_list() (AI) -> how the site is licensed. Decided by AI; a person decided each label, so the source is 'manual'.
WEB_LICENCE_LABELS: dict[str, WebLicence] = {
    "public-domain-us-gov": WebLicence("LicenseRef-us-gov-public-domain", "manual"),
    "cc-by-4.0": WebLicence("CC-BY-4.0", "manual"),
    "cc-by-sa-4.0": WebLicence("CC-BY-SA-4.0", "manual"),
    "copyright-summarise-and-cite": WebLicence(UNKNOWN, UNKNOWN),
}


def web_page_licence(label: str | None, page_licence: str | None = None) -> WebLicence:
    """The licence of a web page. A licence the page declares itself (detect_license) wins; else the label of the crawl list.

    An empty or unknown label gives 'unknown' (summarise and cite): a label we do not know is never read as permission.
    """
    if page_licence and page_licence != UNKNOWN:
        return WebLicence(page_licence, "page")
    if not label:
        return WebLicence(UNKNOWN, UNKNOWN)
    known = WEB_LICENCE_LABELS.get(label.strip().lower())
    if known is None:
        logger.warning("unknown crawl_list licence label %r: treated as unknown", label)
        return WebLicence(UNKNOWN, UNKNOWN)
    return known
