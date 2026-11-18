"""ExtractConfig.fingerprint(): the 5th key of DE's chunk_config (AI-10)."""

from typing import Any

import pytest

from core.knowledge import ChunkSettings, ExtractConfig
from core.knowledge import extract as extract_module
from core.knowledge.extract import FINGERPRINT_EXCLUDED, _canonical

# The default config's fingerprint. If this changes, DE rebuilds its chunks: change it only on
# purpose (a new default, a new setting, or EXTRACTION_VERSION), and tell DE.
FROZEN_DEFAULT = "f33bf1b5f2bab420ecf719317d4e792bedd401f8957c9503cea0814553545483"

# One different, valid value for every hashed setting.
CHANGED: dict[str, dict[str, Any]] = {
    "min_words": {"min_words": 151},
    "extraction_mode": {"extraction_mode": "recall"},
    "languages": {"languages": ("en", "en")},  # only "en" is supported today
    "min_language_confidence": {"min_language_confidence": 0.81},
    "max_link_density": {"max_link_density": 0.51},
    "max_short_line_ratio": {"max_short_line_ratio": 0.61},
    "short_line_words": {"short_line_words": 6},
    "consent_max_words": {"consent_max_words": 301},
    "password_max_words": {"password_max_words": 301},
    "paywall_phrase_max_words": {"paywall_phrase_max_words": 401},
    "page_concepts": {"page_concepts": 11},
    "chunk_concepts": {"chunk_concepts": 6},
    "injection_screen": {"injection_screen": False},
    "injection_max_low": {"injection_max_low": 4},
    "chunking.target_words": {"chunking": ChunkSettings(target_words=181)},
    "chunking.max_words": {"chunking": ChunkSettings(max_words=251)},
    "chunking.max_chars": {"chunking": ChunkSettings(max_chars=1801)},
    "chunking.min_words": {"chunking": ChunkSettings(min_words=51)},
    "chunking.overlap_sentences": {"chunking": ChunkSettings(overlap_sentences=1)},
    "chunking.overlap_words": {"chunking": ChunkSettings(overlap_words=41)},
}


def hashed_fields() -> set[str]:
    fields = _canonical(ExtractConfig(), FINGERPRINT_EXCLUDED)
    nested = {f"chunking.{name}" for name in fields.pop("chunking")}
    return set(fields) | nested


def test_the_default_fingerprint_is_frozen() -> None:
    value = ExtractConfig().fingerprint()
    assert value == FROZEN_DEFAULT
    assert len(value) == 64 and int(value, 16) >= 0


def test_every_hashed_setting_is_covered() -> None:
    # A new ExtractConfig or ChunkSettings field fails here until it is added to CHANGED (and
    # to the list in docs/ai/extraction.md), so no setting is left out of the fingerprint.
    assert set(CHANGED) == hashed_fields()


@pytest.mark.parametrize("field", sorted(CHANGED))
def test_changing_any_hashed_setting_changes_the_fingerprint(field: str) -> None:
    assert ExtractConfig(**CHANGED[field]).fingerprint() != FROZEN_DEFAULT


def test_site_boilerplate_is_not_hashed() -> None:
    per_site = ExtractConfig(site_boilerplate=("a" * 64, "b" * 64))
    assert per_site.fingerprint() == FROZEN_DEFAULT
    assert "site_boilerplate" not in _canonical(per_site, FINGERPRINT_EXCLUDED)


def test_an_int_and_a_float_for_the_same_setting_are_one_value() -> None:
    assert (
        ExtractConfig(min_language_confidence=1).fingerprint()
        == ExtractConfig(min_language_confidence=1.0).fingerprint()
    )


def test_the_same_settings_always_give_the_same_value() -> None:
    a = ExtractConfig(languages=("en",), chunking=ChunkSettings(target_words=180))
    assert a.fingerprint() == ExtractConfig().fingerprint()


def test_a_new_extraction_version_changes_the_fingerprint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(extract_module, "EXTRACTION_VERSION", extract_module.EXTRACTION_VERSION + 1)
    assert ExtractConfig().fingerprint() != FROZEN_DEFAULT
