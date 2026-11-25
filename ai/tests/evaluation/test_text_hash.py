"""AI-25: data-file hashes are the same on Windows (CRLF checkout) and Linux (LF), and the
hashes in old reports (raw bytes of a CRLF checkout) can still be verified."""

import hashlib
from pathlib import Path

from evaluation.analyzer import data as analyzer_data
from evaluation.common import HASH_SCHEME, match_recorded_hash, text_sha256
from evaluation.safety import data as safety_data

LF = b"name: x\nrequests:\n  - id: a\n"
CRLF = LF.replace(b"\n", b"\r\n")


def test_lf_and_crlf_give_the_same_hash(tmp_path: Path) -> None:
    (tmp_path / "lf.yaml").write_bytes(LF)
    (tmp_path / "crlf.yaml").write_bytes(CRLF)
    assert text_sha256(tmp_path / "lf.yaml") == text_sha256(tmp_path / "crlf.yaml")
    assert text_sha256(LF) == hashlib.sha256(LF).hexdigest()


def test_a_new_entry_matches_only_its_lf_form() -> None:
    assert match_recorded_hash(text_sha256(LF), CRLF, HASH_SCHEME) == "sha256-lf"
    crlf_hash = hashlib.sha256(CRLF).hexdigest()
    assert match_recorded_hash(crlf_hash, LF, HASH_SCHEME) is None


def test_a_legacy_entry_hashed_on_a_windows_checkout_still_verifies() -> None:
    # Reports written before AI-25 hashed the raw bytes of a CRLF checkout and have no scheme.
    crlf_hash = hashlib.sha256(CRLF).hexdigest()
    assert match_recorded_hash(crlf_hash, LF) == "legacy-crlf"
    assert match_recorded_hash(crlf_hash, CRLF) == "legacy-crlf"
    assert match_recorded_hash(hashlib.sha256(LF).hexdigest(), LF) == "sha256-lf"
    assert match_recorded_hash("0" * 64, LF) is None


def test_mixed_endings_in_the_raw_bytes_are_a_legacy_raw_match() -> None:
    mixed = b"a\r\nb\nc\r\n"
    assert match_recorded_hash(hashlib.sha256(mixed).hexdigest(), mixed) == "legacy-raw"


def test_analyzer_sources_record_the_scheme_and_lf_hashes() -> None:
    seed, *files = analyzer_data.sources()
    assert seed.hash == "manifest-dataset-sha256"
    for source, path in zip(files, analyzer_data.FILES.values(), strict=True):
        assert source.hash == HASH_SCHEME
        assert source.sha256 == text_sha256(path)


def test_safety_sources_record_the_scheme() -> None:
    own = [s for s in safety_data.sources() if s.get("hash") == HASH_SCHEME]
    assert len(own) == len(safety_data.FILES)
    for entry, path in zip(own, safety_data.FILES.values(), strict=True):
        assert entry["sha256"] == text_sha256(path)
