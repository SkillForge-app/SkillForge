"""licence_for_url: Source.licence from the registry's host rule (interim until review F14)."""

import pytest

from core.knowledge import licence_for_url
from core.knowledge.search import SPDX_LICENCE, Licence


@pytest.mark.parametrize(
    ("url", "licence"),
    [
        # Listed US federal sites: public domain (the SPDX custom id DE stores).
        (
            "https://www.nist.gov/itl/ai-risk-management-framework",
            "LicenseRef-us-gov-public-domain",
        ),
        (
            "https://www.ftc.gov/business-guidance/advertising-marketing",
            "LicenseRef-us-gov-public-domain",
        ),
        # A Creative Commons site in the registry.
        ("https://genai.owasp.org/llmrisk/llm01-prompt-injection/", "CC-BY-SA-4.0"),
        # The default note (copyright-summarise-and-cite) has no reusable licence.
        ("https://arxiv.org/abs/2005.11401", None),
        ("https://example.com/page", None),
    ],
)
def test_licence_comes_from_the_host_rule(url: str, licence: str | None) -> None:
    assert licence_for_url(url) == licence


def test_every_registry_note_has_a_mapping() -> None:
    notes = set(Licence.__args__)  # type: ignore[attr-defined]
    assert set(SPDX_LICENCE) == notes
