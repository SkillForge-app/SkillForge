"""Licence detection for a fetched page (sources.license, sources.license_source).

Rules (an assumption of DE-04; docs/data-architecture.md only says "latest known SPDX id, or 'unknown'"):

1. Only a licence the page itself declares is used: `<link rel="license" href=...>` or `<a rel="license" href=...>`,
   `<meta name="license" content=...>` (also `dcterms.license`), or `"license"` in JSON-LD.
2. The declared URL or id is mapped to an SPDX id with the table below (Creative Commons, MIT, Apache, BSD, ISC, MPL, GPL...).
   A value we cannot map gives 'unknown'. Nothing is guessed from a footer text or from the absence of a licence.
3. The result is stored with `license_source = 'page'`. Whether a licence is permissive enough to use as an example is
   decided later (DE-08), not here: CC-BY-NC is detected, not approved.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser

UNKNOWN = "unknown"

_CC = re.compile(r"creativecommons\.org/licenses/([a-z\-]+)/(\d\.\d)", re.IGNORECASE)
_CC_ZERO = re.compile(r"creativecommons\.org/publicdomain/zero/1\.0", re.IGNORECASE)
_URL_TABLE = (
    (re.compile(r"opensource\.org/licen[sc]es?/mit\b", re.IGNORECASE), "MIT"),
    (re.compile(r"apache\.org/licenses/LICENSE-2\.0", re.IGNORECASE), "Apache-2.0"),
    (re.compile(r"opensource\.org/licen[sc]es?/apache-2\.0", re.IGNORECASE), "Apache-2.0"),
    (re.compile(r"opensource\.org/licen[sc]es?/bsd-3-clause", re.IGNORECASE), "BSD-3-Clause"),
    (re.compile(r"opensource\.org/licen[sc]es?/bsd-2-clause", re.IGNORECASE), "BSD-2-Clause"),
    (re.compile(r"opensource\.org/licen[sc]es?/isc", re.IGNORECASE), "ISC"),
    (re.compile(r"mozilla\.org/(?:en-US/)?MPL/2\.0", re.IGNORECASE), "MPL-2.0"),
    (re.compile(r"gnu\.org/licenses/gpl-3\.0", re.IGNORECASE), "GPL-3.0-only"),
    (re.compile(r"gnu\.org/licenses/agpl-3\.0", re.IGNORECASE), "AGPL-3.0-only"),
    (re.compile(r"spdx\.org/licenses/([A-Za-z0-9.+-]+?)(?:\.html)?$", re.IGNORECASE), None),    # the id is in the URL
)
_SPDX_IDS = {
    "mit": "MIT", "apache-2.0": "Apache-2.0", "bsd-3-clause": "BSD-3-Clause", "bsd-2-clause": "BSD-2-Clause",
    "isc": "ISC", "mpl-2.0": "MPL-2.0", "cc0-1.0": "CC0-1.0", "unlicense": "Unlicense",
}


@dataclass(frozen=True)
class LicenseInfo:
    spdx: str                 # an SPDX id, or 'unknown'
    declared: str | None      # what the page said, for the log
    source: str               # 'page' or 'unknown'


NOT_FOUND = LicenseInfo(UNKNOWN, None, "unknown")


def to_spdx(value: str) -> str:
    """Map a licence URL or id to an SPDX id; 'unknown' when it is not in the table."""
    value = value.strip()
    if m := _CC.search(value):
        kind, version = m.group(1).upper(), m.group(2)
        return f"CC-{kind}-{version}"
    if _CC_ZERO.search(value):
        return "CC0-1.0"
    if value.lower() in _SPDX_IDS:
        return _SPDX_IDS[value.lower()]
    for pattern, spdx in _URL_TABLE:
        if m := pattern.search(value):
            return spdx or _SPDX_IDS.get(m.group(1).lower(), UNKNOWN)
    return UNKNOWN


class _Collector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.declared: list[str] = []
        self._in_jsonld = False
        self._jsonld: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag in ("link", "a") and "license" in a.get("rel", "").lower().split() and a.get("href"):
            self.declared.append(a["href"])
        elif tag == "meta" and a.get("name", "").lower() in ("license", "dcterms.license") and a.get("content"):
            self.declared.append(a["content"])
        elif tag == "script" and a.get("type", "").lower() == "application/ld+json":
            self._in_jsonld = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._in_jsonld = False

    def handle_data(self, data: str) -> None:
        if self._in_jsonld:
            self._jsonld.append(data)

    def jsonld_licenses(self) -> list[str]:
        found: list[str] = []
        try:
            data = json.loads("".join(self._jsonld))
        except ValueError:
            return found
        stack = [data]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                value = node.get("license")
                if isinstance(value, str):
                    found.append(value)
                elif isinstance(value, dict) and isinstance(value.get("@id"), str):
                    found.append(value["@id"])
                stack.extend(node.values())
            elif isinstance(node, list):
                stack.extend(node)
        return found


def detect_license(content: bytes | str) -> LicenseInfo:
    """The licence a page declares about itself, as an SPDX id; NOT_FOUND ('unknown') if it declares none we know."""
    text = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else content
    parser = _Collector()
    try:
        parser.feed(text)
    except Exception:  # noqa: BLE001 - broken HTML must not stop the crawl; no licence found
        return NOT_FOUND
    for declared in [*parser.declared, *parser.jsonld_licenses()]:
        spdx = to_spdx(declared)
        if spdx != UNKNOWN:
            return LicenseInfo(spdx, declared, "page")
    return NOT_FOUND
