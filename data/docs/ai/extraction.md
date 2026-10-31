# Extraction and chunking (AI-10, for DE-05 and AI-11)

This turns the raw HTML of one page into clean text, a quality verdict, key concepts and chunks. Each chunk becomes an A4 `Passage`. It lives in `ai/core/knowledge/`.
- **It never fetches.** DE-04 fetches, DE-05 calls this, and DE-06 stores the provenance.
- **Same input, same output:** the same HTML and config always give the same result, so re-running a DE-05 job gives the same chunks and ids.
- **Changes:** need a pull request that the AI and DE leads approve.

```python
from datetime import date
from core.knowledge import extract_page, ExtractConfig

page = extract_page(raw_html, url=fetched_url, retrieved=date.today(), config=ExtractConfig())
if page.quality.ok:
    for chunk in page.chunks:
        chunk.to_passage()   # contract A4: chunk_id, text, source_url, title, retrieved
        chunk.content_hash   # sha256 of the text, for DE-06
else:
    page.quality.reasons     # e.g. ("paywall_or_login",): store the verdict, make no chunks
```

`raw_html` can be `str` or `bytes`. Bytes are decoded as UTF-8, and other encodings are detected. A URL that is not http(s) raises `ExtractionInputError`. A bad page never raises: it comes back with `quality.reasons` set.

## For DE-05: from a fetched page to rows in the knowledge view
Data Engineering owns storage. DE-05 runs AI's code and writes the result into DE's tables. AI reads it back through the read-only view `knowledge.knowledge_chunks` (the columns are in [retrieval.md](retrieval.md#for-data-engineering-the-knowledge-view)). The same steps as `ingest_pages`, AI's local equivalent:

```python
from core.knowledge import extract_page, ExtractConfig, find_site_boilerplate
from core.llm import embed, load_config        # embed_sync(...) is the blocking version

boilerplate = find_site_boilerplate(((html, url) for html, url in batch_of_one_host))
config = ExtractConfig().model_copy(update={"site_boilerplate": boilerplate.get(host, ())})
page = extract_page(raw_html, url=fetched_url, retrieved=fetched_on, config=config)
if page.quality.ok:
    vectors = await embed([c.text for c in page.chunks], model_role="embedding")
    model = load_config().role("embedding").model        # "local/BAAI/bge-small-en-v1.5"
    # one row per chunk: chunk.chunk_id, source_url, title, retrieved, text, section, concepts,
    # content_hash, domains (from source_domains), embedding_model=model, embedding=vector
else:
    ...  # no chunks; take the page's old chunks out of the view (it may now be a paywall)
```
- **Keep AI's `chunk_id`.** The view's `chunk_id` must be `chunk.chunk_id`, not a database uuid: A4 promises the same id for the same text on the same page across re-crawls.
- **Documents get no prefix.** Embed chunk texts as they are; only queries get BGE's instruction (AI adds it).
- **Vectors:** 384 floats, unit length; DE's `CHECK` on the norm holds for them.
- **The model** runs on CPU with no API key. Fetch it once with `python -m core.llm.local_embed download`; the files are checked against the sha256 pinned in `core/llm/models.yaml` (listed in retrieval.md for `embedding_version`).
- **`domains`:** every chunk of a page serves all the page's domains (DE's `source_domains`). One row per chunk in the view, with the domains as a `text[]`.

## What you get
| Object | Fields |
|---|---|
| `ExtractedPage` | `url`, `title`, `retrieved`, `extractor` (`trafilatura`, `bs4` or `none`), `text` (the clean main text, one block per line), `quality`, `concepts` (the top 10), `chunks` (empty unless `quality.ok`) |
| `QualityReport` | `reasons`, `ok`, `word_count`, `link_density`, `short_line_ratio`, `language`, `language_confidence` |
| `Chunk` | `chunk_id`, `source_url`, `title`, `retrieved`, `text`, `section` (the H1–H3 heading path), `position`, `word_count`, `concepts` (the top 5), `content_hash`; `to_passage()` |

- **Format:** all of these are strict, frozen Pydantic models. Store them with `model_dump_json()`.
- **`chunk_id`:** `<host>-<sha256(url)[:8]>-<sha256(text)[:8]>`. A chunk keeps its id as long as its text and URL don't change, even when another part of the page is edited.
- **Title:** the page title without the site name ("SEO Starter Guide: The Basics", not "… | Google Search Central | …"). It is at most 200 characters.

## How it works
1. **Pre-clean:**
   - Read the page signals first: the JSON-LD paywall markup and any password field.
   - Then drop scripts, styles and hidden elements (`hidden`, `aria-hidden="true"`, `display:none`, `visibility:hidden`). Hidden text never reaches a chunk, which also matters for prompt injection (AI-19).
   - Also drop citation markers, reference lists and edit links.
2. **Main content:**
   - trafilatura (XML output, headings kept, `extraction_mode="precision"`). A `<br>` inside a paragraph splits it into separate lines, so "About the FTC<br>The FTC works…" never becomes "About the FTCThe FTC works…".
   - **Fallback (BeautifulSoup):** used when trafilatura finds nothing or less than `min_words`, and the fallback finds more. It takes `<main>`, then `<article>`, then `<body>`, without nav, header, footer, aside or form.
   - **Page chrome is dropped from both extractors' output:**
     - short lines that are only a link or a call to action ("Download the AI RMF 1.0", "View the AI RMF Playbook", "Learn more")
     - a "Learn more." at the end of a paragraph
     - short contact or email lines ("aiframework [at] nist.gov")
     - image placeholders ("Image")
     - short copyright lines
     Headings and real sentences stay, even when they start with "Learn more about…".
   - **Spacing:** every block boundary keeps a space, and "conduct.(Question" becomes "conduct. (Question".
3. **Site boilerplate removal (off by default):** removes a site's template text, the kind that sits inside every article body.
   - **How to switch it on:** call `find_site_boilerplate([(html, url), …])` over several pages of the same site. It returns `{host: hashes}` for the sentences of 6 or more words that repeat on at least 2 of those pages. Pass a host's hashes as `ExtractConfig(site_boilerplate=hashes)` when extracting that host's pages.
   - **What it removes:** each repeated sentence.
     - If repeated sentences make up half or more of a block, the whole block goes, and so does a short label line right before it ("About the FTC", "Your Opportunity to Comment").
     - Otherwise only the repeated sentences go.
   - **What's left out:** shorter sentences ("Yes.", "For example:") are never counted.
   - **For DE-05:** compute the hashes once per site, for example in DE-09's domain cache. Full deduplication across pages is still DE-07's job.
4. **Quality checks**, below.
5. **Language:** py3langid, because spaCy has no language detector of its own. Only English pages go on.
6. **spaCy `en_core_web_sm`:** sentences, plus key-concept candidates (noun phrases and named entities).
7. **Chunking**, below.

## Quality checks
A page is rejected when it has any of these reasons. They are always listed in this order. All thresholds are `ExtractConfig` fields.

| Reason | Rule (default) |
|---|---|
| `empty` | No main text at all, for example a JavaScript-only app shell |
| `paywall_or_login` | JSON-LD `isAccessibleForFree: false` (the schema.org paywall markup), **or** a password field with fewer than 300 words, **or** a paywall or login phrase ("subscribe to continue reading", "sign in to continue", …) with fewer than 400 words |
| `boilerplate` | Over 50% of the main text is link text (link farms), **or** over 60% of text blocks have fewer than 5 words (menus, tag lists), **or** cookie or consent wording with fewer than 300 words |
| `wrong_language` | The language is not in `languages` (default `("en",)`), or its confidence is below 0.80 |
| `too_short` | Fewer than 150 words of main text |

- **Word-count guards:** these keep normal pages from being flagged. A long article with an "Already a subscriber? Sign in" footer, or a login box in the sidebar, passes.
- **Languages:** only `en` has a spaCy pipeline. `ExtractConfig(languages=("fr",))` is rejected until a pipeline is added. To add Arabic, wire in a pipeline and an Arabic concept extractor first.

## Chunk size: the decision and why
| Setting (`ExtractConfig.chunking`) | Default |
|---|---|
| `target_words` | 180 (about 240 tokens) |
| `max_words` / `max_chars` | 250 / 1,800 |
| `min_words` | 50 |
| `overlap_sentences` / `overlap_words` | 2 / 40 (about 20%) |

- **One idea per chunk.** 150 to 250 words usually covers one point, such as one rule, one FAQ answer, or a definition with its explanation. The embedding of a focused chunk matches a question more sharply than a long chunk that mixes topics. Under about 50 words, chunks lose their context: dangling "it" and "this", or a rule without its condition.
- **It fits A4.** `Passage.text` allows 2,000 characters, so the 1,800-character cap makes every chunk a valid Passage.
- **It fits what the Architect reads.** `k = 5` gives about 1,200 tokens of focused evidence per query. That is cheap, and "Lost in the Middle" (one of the A4 sources) shows that a few relevant passages beat many marginal ones.
- **Overlap in whole sentences.** A fact that falls across a boundary is whole in at least one chunk, and the index grows only about 1.2 times. Overlap in raw tokens would cut sentences in half.
- **Headings are boundaries.** A chunk stays under one H1–H3 section, and `section` records the path.
  - **Short sections:** only a section that is itself short (under `min_words`) is packed together with the next one, headings included. That suits FAQs, where the question is the context.
  - **Leftovers:** the leftover end of a long section joins the chunk before it, never the next section.
- **Every chunk under a heading starts with that heading.** A chunk that continues a section, rather than starting it, repeats the section's heading as its first line, so an FAQ answer always comes with its question. The heading line counts toward `max_words` and `max_chars`.
- **Where a chunk may end:**
  - **Never on a heading or sub-heading (H4–H6).** It moves to the start of the next chunk, together with its text. A heading with no text after it is dropped.
  - **Never on a lone sentence that opens a new paragraph.** It moves to the next chunk with the rest of its paragraph, so on pages without headings a chunk breaks between topics, not one sentence into the next.
  - **Lists stay with their intro** (the sentence ending in ":" before them). The list is finished in the chunk when it still fits under `max_words`, or moves on whole when it fits in one chunk. A list too long for any chunk is split, but never right after the intro and a single item.
- **Overlap only inside a paragraph.** The repeated sentences are used only when the break falls inside a paragraph. A chunk that starts a new paragraph doesn't open with the end of the previous one.
- **Other rules:**
  - A short last chunk joins the one before.
  - A sentence longer than `max_words` is split at word boundaries.
  - A chunk that repeats earlier text on the same page is dropped.
- **On the 20 labelled pages** (with site boilerplate removal on):
  - there are 222 chunks
  - the median is 125.5 words, and 80% of chunks fall between 65 and 188 words (the 10th to 90th percentile)
  - the smallest is 52 words and the largest 235
- **Still to be measured.** These values are a reasoned starting point. AI-11's recall tests should compare 120, 180 and 250 words before the index is built at scale.

## Key concepts
- **What counts:** noun phrases and entities (ORG, PRODUCT, LAW, EVENT, WORK_OF_ART) from spaCy.
  - Leading determiners and pronouns are dropped.
  - Terms are lowercase, and only the head noun is lemmatised ("breaking change", "can-spam act", "e-e-a-t", "llm").
- **Score:** frequency, doubled for a multi-word term and doubled again when the term is in the title or a heading. Ties go alphabetically.
- **Output:** the top 10 for the page and the top 5 for each chunk.
- **Use:** they are metadata for AI-11 (filtering and boosting) and AI-09 (source ranking). They are not part of A4.

## Quality report (done-when)
```bash
python -m evaluation.extraction check-data        # validate tests/fixtures/pages/pages.yaml
python -m evaluation.extraction report            # writes evaluation/extraction/reports/extraction-<date>.md/.json
python -m evaluation.extraction report --no-site-boilerplate   # same, with site boilerplate removal off
```
- **What it does:** runs every labelled page (8 real, saved once and openly licensed, plus 12 hand-written failure and boundary pages) and checks the automatic gates.
- **Site boilerplate:** removal is on in the report, learned from the labelled pages of each host, as DE-05 would run it. With it off, the FTC template text fails the leak gate.
- **The gates:**

  | Check | Gate |
  |---|---|
  | Verdicts match the labels | 100% |
  | Titles match | 100% |
  | Languages match | 100% |
  | Facts that must survive are found | ≥ 95% |
  | Chunks within the word range | ≥ 90% |
  | Chunks are valid Passages | 100% |
  | Chunks end cleanly | ≥ 95% |
  | Boilerplate leaks | 0 |

- **Human review:** the report also prints 20 chunks for a person to check. They are picked with a fixed seed and spread evenly over the pages, so every page with chunks gets one before any page gets a second, and one long page cannot fill the sample. **AI-10 is done when the automatic gates pass and the reviewer marks at least 18 of 20 as good.**
- **Adding a page:**
  1. Save it once, without crawling, from an openly licensed source.
  2. Label it in `pages.yaml` with its URL, retrieved date, licence, expected reasons, `must_contain` facts and `must_not_contain` page chrome.
  3. Run both commands.

## Known limits
- **Precision mode** drops some tables built from definition lists: Google's "things we believe you shouldn't focus on" table. `extraction_mode="recall"` keeps it, but on our pages it also stopped flagging the link farm. That is why the default stays `precision`.
- **Site boilerplate needs at least 2 pages of the site.** Template text on a site we have only one page of stays in. Removal is also off unless the caller passes the hashes.
- **Topics on pages without headings:** chunks break between paragraphs, but two short paragraphs on different topics can still share a chunk. Real topic segmentation is not done.
- **Chrome rules are word lists:** call-to-action words ("Download", "View", "Learn more", …) and image placeholders are matched on short lines only. A site with other button wording keeps it.
- **Prompt injection:** dropping hidden text is the only defence here. Fuller injection checks are AI-19.
