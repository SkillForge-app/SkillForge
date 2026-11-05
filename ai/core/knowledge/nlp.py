"""Language detection and spaCy processing for extraction (AI-10).

spaCy has no language detector of its own, so py3langid (the library trafilatura also uses)
picks the language first. Only then does spaCy's English pipeline split sentences and find key
concepts. Both models load once per process.
"""

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import lru_cache

import spacy
from py3langid.langid import MODEL_FILE, LanguageIdentifier
from spacy.language import Language
from spacy.tokens import Doc, Span, Token

SPACY_MODEL = "en_core_web_sm"
# Entity types that name a concept worth indexing; dates, numbers and places are not concepts.
CONCEPT_ENTITIES = frozenset({"ORG", "PRODUCT", "LAW", "EVENT", "WORK_OF_ART"})
_DROP_POS = frozenset({"DET", "PRON", "PUNCT", "SYM", "NUM", "SPACE"})
_MAX_TERM_TOKENS = 5
_LANGUAGE_SAMPLE_CHARS = 20_000


@lru_cache(maxsize=1)
def load_nlp() -> Language:
    return spacy.load(SPACY_MODEL)


@lru_cache(maxsize=1)
def _identifier() -> LanguageIdentifier:
    return LanguageIdentifier.from_model_file(MODEL_FILE, norm_probs=True)


def detect_language(text: str) -> tuple[str, float]:
    """(ISO 639-1 code, confidence 0–1). Text with no letters gives a low confidence."""
    lang, confidence = _identifier().classify(text[:_LANGUAGE_SAMPLE_CHARS])
    return str(lang), round(float(confidence), 4)


@dataclass(frozen=True)
class Sentence:
    text: str
    terms: tuple[str, ...]  # concept candidates found in this sentence, in order


def analyse(texts: Sequence[str]) -> list[list[Sentence]]:
    """Split each text into sentences, each with its concept candidates. Same order as input."""
    return [_sentences(doc) for doc in load_nlp().pipe(texts, batch_size=64)]


def _sentences(doc: Doc) -> list[Sentence]:
    spans: list[Span] = list(doc.noun_chunks)
    covered = {i for span in spans for i in range(span.start, span.end)}
    spans += [
        ent
        for ent in doc.ents
        if ent.label_ in CONCEPT_ENTITIES and not covered.intersection(range(ent.start, ent.end))
    ]
    by_sentence: dict[int, list[tuple[int, str]]] = {}
    for span in spans:
        term = _term(span)
        if term:
            by_sentence.setdefault(span.sent.start, []).append((span.start, term))
    return [
        Sentence(
            sent.text.strip(),
            tuple(term for _, term in sorted(by_sentence.get(sent.start, []))),
        )
        for sent in doc.sents
        if sent.text.strip()
    ]


def _term(span: Span) -> str | None:
    # "the FTC's Endorsement Guides" -> "ftc endorsement guide": leading and trailing
    # determiners, pronouns and punctuation dropped, possessives dropped, lowercase, the head
    # noun lemmatised, inner hyphens kept ("e-e-a-t"). Stop-word-only or short terms are dropped.
    tokens = list(span)
    while tokens and (tokens[0].pos_ in _DROP_POS or tokens[0].is_punct):
        tokens.pop(0)
    while tokens and (tokens[-1].pos_ in _DROP_POS or tokens[-1].is_punct):
        tokens.pop()
    words = [t for t in tokens if not t.is_punct and t.tag_ != "POS"]
    if not words or len(words) > _MAX_TERM_TOKENS or all(t.is_stop for t in words):
        return None
    head = words[-1]  # only the head noun is lemmatised: "breaking changes" -> "breaking change"
    term = ""
    for t in tokens:
        if t.tag_ == "POS":
            term = term.rstrip() + (t.whitespace_ or "")
        else:
            term += (_lemma(t) if t is head else t.text.lower()) + t.whitespace_
    term = " ".join(term.split())
    if len(term) < 3 or not any(c.isalpha() for c in term):
        return None
    return term


def _lemma(token: Token) -> str:
    text = token.text
    if len(text) > 2 and text.endswith("s") and text[:-1].isupper():  # "LLMs" -> "llm"
        return text[:-1].lower()
    return str(token.lemma_).lower()


def rank_concepts(
    terms: Iterable[str], *, boost: frozenset[str] = frozenset(), top: int
) -> list[str]:
    """Best terms first. Score: frequency, doubled for a multi-word term ("prompt injection"
    says more than "page") and doubled again when the term is in a title or heading (`boost`).
    Ties go alphabetically, so the order is deterministic."""
    scored = {
        term: n * (2 if " " in term or "-" in term else 1) * (2 if term in boost else 1)
        for term, n in Counter(terms).items()
    }
    return [term for term, _ in sorted(scored.items(), key=lambda kv: (-kv[1], kv[0]))][:top]
