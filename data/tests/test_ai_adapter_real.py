"""DE-05: contract tests of the adapter against the REAL `skillforge` package (AI's `core`).

Marker `ai_real`: deselected by default (`addopts` in pyproject.toml), because they need the optional extra `ai` (spaCy, fastembed,
litellm...). Run them with `pytest -m ai_real` in an environment where `skillforge` is installed. When AI changes one of the things
pinned here, a failure is the point: it tells DE before a re-extraction does.

NOTE (16 Nov 2026): these tests were written from AI's source on main and have not been run yet: the package is not installed here.
"""
import pytest
from fakes import fake_normalise_url

from skillforge_data.adapters import ai as adapter
from skillforge_data.interfaces import ExtractedPage, PipelineError
from skillforge_data.pipeline.config import PipelineConfig

pytestmark = pytest.mark.ai_real

DEFAULT_FINGERPRINT = "f33bf1b5f2bab420ecf719317d4e792bedd401f8957c9503cea0814553545483"   # docs/ai/extraction.md


@pytest.fixture(scope="module")
def knowledge():
    return pytest.importorskip("core.knowledge")


def test_normalise_url_is_ai_s_documented_example(knowledge):
    url = "https://WWW.Example.org/Guide/?utm_source=x&id=2#top"
    assert adapter.normalise_url(url) == "https://www.example.org/Guide?id=2"
    assert fake_normalise_url(url) == adapter.normalise_url(url), "our test fake follows the real rule on this example"
    with pytest.raises(ValueError):
        adapter.normalise_url("ftp://example.org/x")


def test_the_default_config_has_the_pinned_fingerprint_and_the_chunking_we_read(knowledge):
    config = adapter.default_extract_config()
    assert config.fingerprint() == DEFAULT_FINGERPRINT
    assert (config.chunking.target_words, config.chunking.overlap_words) == (180, 40)
    assert adapter.default_extract_config(("a" * 64,)).fingerprint() == DEFAULT_FINGERPRINT, "site_boilerplate is not in the fingerprint"


def test_the_pipeline_config_takes_size_and_overlap_from_ais_config(knowledge):
    config = PipelineConfig(pipeline_version="p1", embedding_version=adapter.EMBEDDING_VERSION,
                            extract_config=adapter.default_extract_config())
    assert config.chunk_config() == {"size": 180, "overlap": 40, "splitter": "sentence", "pipeline_version": "p1",
                                     "extract_fingerprint": DEFAULT_FINGERPRINT}


def test_embedding_version_matches_models_yaml(knowledge):
    assert adapter.embedding_version_from_ai() == adapter.EMBEDDING_VERSION


def test_embed_with_ais_fake_gateway_gives_384_unit_vectors(knowledge):
    llm = pytest.importorskip("core.llm")
    with llm.use_fake():
        vectors = adapter.make_embed()(["first text", "second text"])
    assert len(vectors) == 2 and all(len(v) == 384 for v in vectors)
    assert all(abs(sum(x * x for x in v) - 1.0) < 1e-3 for v in vectors)


PAGE = ("<html><head><title>Guide to pgvector</title></head><body><main><h1>Guide to pgvector</h1>"
        + "".join(f"<p>Section {i} explains how the vector index stores embeddings for fast similarity search in a database, "
                  f"and why the number {i} matters for tuning recall against latency in real systems.</p>" for i in range(30))
        + "</main></body></html>")


def test_extract_page_through_the_adapter_gives_our_page(knowledge):
    from datetime import date
    extract = adapter.make_extract()
    page = extract(PAGE, url="https://Docs.Example.org/guide/?utm_source=x", retrieved=date(2026, 11, 5))
    assert isinstance(page, ExtractedPage)
    assert page.url == "https://docs.example.org/guide"
    if page.quality_ok:
        assert page.chunks and len({c.chunk_id for c in page.chunks}) == len(page.chunks)
        assert all(len(c.content_hash) == 64 and c.text for c in page.chunks)
    else:
        assert page.quality_reasons and page.chunks == ()


def test_a_url_ai_refuses_is_a_pipeline_error(knowledge):
    from datetime import date
    with pytest.raises(PipelineError):
        adapter.make_extract()(PAGE, url="ftp://example.org/x", retrieved=date(2026, 11, 5))
