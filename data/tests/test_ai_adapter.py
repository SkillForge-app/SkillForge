"""DE-05: the adapter to AI's functions (skillforge_data/adapters/ai.py).

The wrapping logic is tested here with stand-ins shaped like AI's objects (plain attributes, `model_dump`), so these tests run on
every machine and in CI without AI's package. The contract tests against the real package are in test_ai_adapter_real.py (`ai_real`).
"""
import importlib
import subprocess
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from fakes import T0, FakeEmbed, fake_config, fake_normalise_url

from skillforge_data.adapters import ai as adapter
from skillforge_data.interfaces import ExtractedPage, PipelineError
from skillforge_data.pipeline.process import RawPage, process_document

DATA_DIR = Path(__file__).resolve().parents[1]
LONG_FORM = (
    "Qdrant/bge-small-en-v1.5-onnx-Q@aa8f8b060edb00e03bfdd08813a2949946c8ba55"
    "#model_optimized.onnx:sha256=51f1bd0addd6e859e42c2c8021a5e5461385bb676a649f4b269aa445449f2431"
)  # as written in AI's docs/ai/retrieval.md, "The pinned embedding model"


# ------------------------------------------------------------------------------------------ stand-ins
class Dumpable(SimpleNamespace):
    def model_dump(self, mode="python"):
        return {"findings": [], "removed": self.removed, "invisible_chars": 0, "rejected": False}


def ai_page(*, ok=True, texts=("alpha text", "beta text"), reasons=()):
    chunks = [
        SimpleNamespace(chunk_id=f"docs.example.org-aaaaaaaa-{i:08d}", text=t, position=i, word_count=2,
                        content_hash=f"{i:064x}", section=["Intro", "Part"], concepts=["c1"])
        for i, t in enumerate(texts)
    ]
    return SimpleNamespace(
        url="https://docs.example.org/guide", title="Guide", retrieved=date(2026, 11, 5), extractor="trafilatura",
        text="clean text", quality=SimpleNamespace(ok=ok, reasons=tuple(reasons), language="en"),
        concepts=["x"], chunks=chunks if ok else [], screening=Dumpable(removed=2),
    )


# ------------------------------------------------------------------------------------ embedding_version
def test_embedding_version_has_the_long_form_of_retrieval_md():
    assert adapter.EMBEDDING_VERSION == LONG_FORM
    assert adapter.embedding_version("a/b", "r" * 40, "m.onnx", "h" * 64) == f"a/b@{'r' * 40}#m.onnx:sha256={'h' * 64}"


# ------------------------------------------------------------------------------------------ conversion
def test_an_ai_page_becomes_our_extracted_page():
    page = adapter.convert_page(ai_page())
    assert isinstance(page, ExtractedPage)
    assert (page.url, page.title, page.text, page.quality_ok, page.language) == ("https://docs.example.org/guide", "Guide", "clean text", True, "en")
    assert page.screening == {"findings": [], "removed": 2, "invisible_chars": 0, "rejected": False}
    assert [c.text for c in page.chunks] == ["alpha text", "beta text"]
    first = page.chunks[0]
    assert (first.chunk_id, first.position, first.word_count, first.section, first.concepts) == (
        "docs.example.org-aaaaaaaa-00000000", 0, 2, ("Intro", "Part"), ("c1",))
    assert first.content_hash == f"{0:064x}"


def test_a_rejected_page_keeps_its_reasons_and_has_no_chunks():
    page = adapter.convert_page(ai_page(ok=False, reasons=("too_short", "injection")))
    assert not page.quality_ok and page.quality_reasons == ("too_short", "injection") and page.chunks == ()


def test_screening_given_as_a_dict_is_kept_as_it_is():
    raw = ai_page()
    raw.screening = {"removed": 1}
    assert adapter.convert_page(raw).screening == {"removed": 1}


def test_make_extract_calls_ai_with_the_url_date_and_config_and_converts():
    calls = []

    def fake_extract_page(html, *, url, retrieved, config):
        calls.append((html, url, retrieved, config))
        return ai_page()

    config = SimpleNamespace(tag="my config")
    extract = adapter.make_extract(config, extract_page=fake_extract_page)
    page = extract(b"<html>", url="https://docs.example.org/guide", retrieved=date(2026, 11, 5))
    assert calls == [(b"<html>", "https://docs.example.org/guide", date(2026, 11, 5), config)]
    assert page.chunks[0].text == "alpha text"


def test_a_page_ai_refuses_is_a_pipeline_error():
    def refuse(html, *, url, retrieved, config):
        raise ValueError(f"not an http(s) URL: {url!r}")          # AI's ExtractionInputError is a ValueError

    extract = adapter.make_extract(SimpleNamespace(), extract_page=refuse)
    with pytest.raises(PipelineError, match="refused"):
        extract(b"x", url="ftp://x", retrieved=date(2026, 11, 5))


# ----------------------------------------------------------------------------------------------- embed
def vec(n=384, value=0.5):
    return [value] * n


def test_embed_passes_texts_and_role_and_returns_lists_of_floats():
    seen = []

    def embed_sync(texts, *, model_role):
        seen.append((list(texts), model_role))
        return [vec() for _ in texts]

    out = adapter.make_embed(embed_sync=embed_sync)(("a", "b"))
    assert seen == [(["a", "b"], "embedding")] and len(out) == 2 and all(len(v) == 384 for v in out)


def test_embed_of_nothing_makes_no_call():
    def never(texts, *, model_role):
        raise AssertionError("must not be called")

    assert adapter.make_embed(embed_sync=never)([]) == []


@pytest.mark.parametrize(
    ("vectors", "why"),
    [([vec()], "1 vectors for 2 texts"), ([vec(), vec(383)], "383 dimensions"), ([vec(), vec(value=float("nan"))], "finite"),
     ([vec(), vec(value=float("inf"))], "finite")],
)
def test_wrong_vectors_are_a_pipeline_error(vectors, why):
    with pytest.raises(PipelineError, match=why):
        adapter.make_embed(embed_sync=lambda texts, *, model_role: vectors)(["a", "b"])


def test_an_error_from_embed_sync_is_a_pipeline_error():
    def inside_a_loop(texts, *, model_role):
        raise RuntimeError("asyncio.run() cannot be called from a running event loop")

    with pytest.raises(PipelineError, match="embed_sync failed"):
        adapter.make_embed(embed_sync=inside_a_loop)(["a"])


# --------------------------------------------------------------------------------- the whole pipeline
def test_the_adapter_works_in_the_pipeline_with_ai_shaped_objects(db):
    """process_document with the adapter's wrappers over AI-shaped stand-ins stores the page, with the config's chunk_config."""
    config = fake_config()
    extract = adapter.make_extract(
        config.extract_config, extract_page=lambda html, *, url, retrieved, config: ai_page(texts=("alpha text", "beta text", "gamma")))
    fake_vectors = FakeEmbed()
    embed = adapter.make_embed(embed_sync=lambda texts, *, model_role: fake_vectors(texts))
    page = RawPage(url="https://docs.example.org/guide", content=b"<html>x</html>", fetched_at=T0, domains=["technology/ai"],
                   content_type="text/html")
    result = process_document(db, page, config=config, extract=extract, embed=embed, normalise_url=fake_normalise_url)
    assert result.status == "processed", result.error
    assert db.execute("SELECT count(*) FROM knowledge.chunks").fetchone()[0] == 3
    assert db.execute("SELECT count(*) FROM knowledge.embeddings").fetchone()[0] == 3


# --------------------------------------------------------------------------------------- lazy import
def test_importing_the_adapter_does_not_import_ai_code():
    code = (f"import sys; sys.path.insert(0, {str(DATA_DIR)!r})\n"
            "import skillforge_data.adapters.ai\n"
            "bad = [m for m in sys.modules if m == 'core' or m.startswith('core.')]\n"
            "assert not bad, bad\n")
    done = subprocess.run([sys.executable, "-I", "-c", code], cwd=DATA_DIR,
                          capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr


def test_without_ai_installed_the_first_use_says_how_to_install_it(monkeypatch):
    real_import = importlib.import_module

    def no_ai(name, *args, **kwargs):
        if name == "core" or name.startswith("core."):
            raise ModuleNotFoundError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(adapter.importlib, "import_module", no_ai)
    for call in (lambda: adapter.normalise_url("https://x.org"), adapter.default_extract_config, adapter.make_embed,
                 adapter.embedding_version_from_ai):
        with pytest.raises(ImportError, match="not installed"):
            call()
