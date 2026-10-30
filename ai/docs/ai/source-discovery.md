# Source discovery (AI-09, for DE-04 and Track B)

This finds which pages to crawl for a domain (and optionally a skill request), ranks them by authority and says whether we may use them. It lives in `ai/core/knowledge/search.py`, with the rules as data in `core/knowledge/sources.yaml`.
- **It feeds the rest of the pipeline:** DE-04 crawls the list, AI-10 extracts the pages and AI-11 indexes them.
- **Changing the registry:** a pull request that the AI lead and the DE lead approve.

```python
from core.knowledge import discover_sources

found = await discover_sources("legal/contracts", request=analyzed_request, limit=10)
found.queries        # the searches that were run
found.sources        # RankedSource list, best first: crawlable sources only (at most `limit`)
found.listed         # ranked but crawl=False (e.g. the high-risk rule): shown, never crawled
found.crawl_list()   # [(url, licence)]: the hand-off to DE-04, only what we may crawl
found.rejected       # [(url, reason)]: blocked, duplicate, robots-disallowed, unknown site, no topic word, other areas only, site cap
```

`discover_sources_sync(...)` is the blocking version, for scripts.

## RankedSource
| Field | Meaning |
|---|---|
| `url`, `host`, `title`, `snippet` | The page, cleaned: lowercase host, no fragment, no tracking parameters |
| `tier` | `official`, `academic`, `reference` or `unknown` (see below) |
| `score`, `reasons` | Why the page is ranked where it is, e.g. "US standards body (NIST); matched 2 of 2 topic words; search rank 1; found by 2 queries; an authority for technology" |
| `licence` | The note DE-04 stores with the page (see below) |
| `robots` | `allowed`, `disallowed` or `unknown` for `SkillForgeBot` |
| `crawl` | False in a high-risk area (legal, medical, finance) unless the tier is `official` or `academic`, with the reason "high-risk area needs an authoritative source". Such sources go to `listed`, never into `sources`. Sources robots.txt disallows or whose terms forbid reuse are dropped (see `rejected`) |
| `pinned` | True for a hand-picked registry pin |
| `best_rank`, `queries` | The best search position, and how many of the queries found it |

## How it works
1. **Queries.** At most 8 per domain, worded from data in `sources.yaml` with no LLM, so the same input always gives the same queries. In order:
   - **From the skill request:** the skill's name ("review NDA contracts guide") and its first expected output.
   - **Domain hints** (`domains:` in `sources.yaml`): extra queries for a domain whose generic queries came back off topic, e.g. "non-disclosure agreement NDA guide" for `legal/contracts`. Most of them name the domain's authority ("sre.google postmortem culture"), which works with any search engine; `site:` alone was often ignored by the recording tool. A domain's hints can also set:
     - `terms` ("NDA", "contract law", ...): these also count as on-topic words when ranking.
     - `authorities`: the sites the reviewer named as the domain's experts (e.g. Cornell LII, GOV.UK, Nolo and the ABA for `legal/contracts`). They get a bonus when ranking.
     - `exclude`: words that mark a page off topic for this domain ("medicare" for `marketing/strategy`).
     - `templates: false`: skip the generic templates (`legal/contracts`, whose templates brought back procurement handbooks).
     - `pinned`: hand-picked pages that search alone did not reach, each with the title a person checked and the date they opened it. A pin is in the list even when no search finds it, and it always ranks first, in registry order. It skips the block, exclude and weak-match tests, since a person checked it, and the site cap. It still goes through robots.txt, the licence and the high-risk crawl rule.
     - `jurisdiction`: the jurisdiction the domain's skills need (`US` for `legal/contracts`, since review-nda is about US law). Sources outside it rank below those inside it, and keep their label.
   - **Pinned today:**
     - `technology/ai`: the NIST AI Risk Management Framework, Google's Rules of Machine Learning, and the OWASP Top 10 for LLM and Gen AI Apps.
     - `legal/contracts`: the Cornell LII Wex entries for non-disclosure agreements, contracts and trade secrets, and the USPTO trade secret policy page.
     - `hr/recruiting`: EEOC prohibited employment practices, DOL hiring, and SHRM interview questions.
     - `marketing/strategy`: the FTC advertising and marketing hub, the FTC endorsement guides FAQ, and SBA's "Plan your business" (market research and marketing).
     - The ABA consumer contract guide is not pinned: americanbar.org refused our requests (HTTP 403), so no one could open it to check it.
   - **From the domain topic:** "{topic} {hint}", "{topic} best practices", "{topic} guidelines site:.gov", "{topic} guide site:.edu" and "{topic} standards".
   - **Hints today:** every seed domain. `technology/software-engineering` has terms only ("code review", "SWEBOK"), so pages on code review keep at least one topic word; PR also counts "ethics" (the PRSA code).
2. **Search.** Each query goes to the provider, which returns 10 results per query.
3. **Clean and merge.** Copies of one page meet: tracking parameters, `www.` and `www2.`, AMP and Markdown copies, a trailing slash, a leading locale folder and an `/index.php/` prefix are folded together. A page that several queries find counts as found by each of them.
4. **Block.** A URL matching a blocklist rule is dropped with its reason.
   - **Spam:** SEO spam planted on hijacked parts of real sites, such as fake PDF download paths or `mail.` and `my-test.` subdomains serving articles.
   - **Copies:** mirrors and archives (crawl the original instead).
   - **Social media and user forums**, which their terms often forbid scraping.
   - **Uploaded documents:** document dumps and homework sites.
   - **Shops and media:** video, audio and shop pages.
   - **Low-value pages:** aggregators and AI summaries, plus tag, category, feed and paginated listing pages.
   - **Pages about content rather than content:**
     - library catalogue records (`/Record/`, `libcat.`, NLM's catalogue)
     - event, webinar, workshop and class pages, and continuing-education (`ce.`) courses
     - university program marketing (`.edu/.../programs/`, `degrees/`, `admissions/`)
   - **Staging and test copies:** a subdomain named for staging, test or dev (`ccrsstg-acquia.`, `stagingmolly.`, `app-dev.`). Crawl the live site instead.
   - **Pages about the organisation itself:**
     - its own job and careers pages (`/jobs/`, `/careers/`, `/job-vacancies/`)
     - freedom-of-information requests and disclosure logs (`disclosures.`, `/foi/`, `freedom-of-information`, Welsh `atisn` requests)
     - "Transparency data" publications. A block can match the page title (`title_pattern`) as well as the URL.
   - **Landing and index pages that only list links:** a site's home page, `..._home/` pages, site maps and A-Z indexes.
   - **Library guides** (`libguides.`, `guides.library.*.edu`, `library.*.edu`, `/c.php?g=`, or "LibGuides" in the title). These used to rank as reference; they are blocked because they only list links.
   - **Mailing-list archive messages** (`/ListArchives/`, `/pipermail/`).
5. **Rank.** The score adds up:
   - the authority tier: official 100, academic 80, reference 60, unknown 30
   - relevance: up to 20, for the share of words matched in the title and URL, using the best of the domain topic and its hint terms (the reason says which, e.g. `matched 2 of 2 words of "contract law"`)
   - the search position: up to 10
   - agreement: +5 per extra query that found it, at most 10
   - area fit: +10 when the registry names the source as an authority for this domain's area, −15 when it names it only for other areas
   - named authority: +30 for a site in the domain's `authorities` (its own host, or its registrable site, so `legacy.sba.gov` counts for `sba.gov` but a parish council does not count for `gov.uk`)
   - **Only a pin brings in these:**
     - an `unknown` site
     - a page with no topic word in its title or URL
     - a source the registry names for other areas only (e.g. Atlassian, an `operations` source, in `technology/ai`), unless this domain names it as an authority
   - A page with an `exclude` word is dropped. Ties go by URL.
   - **Registry rules can cover part of a site:** `path_prefix` narrows a rule to one path, e.g. `github.com/google/eng-practices` is official documentation while the rest of GitHub stays unknown.
   - **Legal sources name their jurisdiction** in the reasons, e.g. `jurisdiction: US (federal)`. It comes from the registry's `jurisdiction` field, else `US (federal)` for listed federal public-domain sites, else the host suffix (`.gov` is `US (state or local)`, `.uk` is `UK`, `.eu` is `EU`, ...), else `unknown`. Known federal `.gov` hosts (cbca.gov, census.gov, justice.gov, uscourts.gov, ...) are listed in the registry as federal public domain, so they read `US (federal)`.
   - **High-risk areas** (legal, medical, finance, `HIGH_RISK_AREAS`): only `official` and `academic` sources get `crawl=True`. `reference` and `unknown` sources keep their rank, for review, with `crawl=False`, so they never reach `crawl_list()`.
   - **Order:** the score orders sources within each of these groups, top to bottom:
     1. pinned sources
     2. the rest, with titles, inside the domain's jurisdiction
     3. the same, but with no page title
     4. sources outside the jurisdiction
     5. the same, but with no page title

     A page "with no title" has a title that is only its host name ("www.ftc.gov"). The reasons say why a page was moved down, e.g. `jurisdiction: UK (not US: ranked below US sources)` or `no page title (ranked below pages with titles)`.
6. **De-duplicate, cap and check.** Best first:
   - **One document on two sites:** a PDF or Office file whose name has the same words is kept once. `SWEBOK_Guide_2004.pdf` and `SWEBOK_2004.pdf` count as one document; filler words such as "guide" and "final" and short numbers are ignored.
   - **Same-title pages:** two pages on one site with the same title are kept once. A trailing " | site name" is ignored, so "Hiring" and "Hiring | U.S. Department of Labor" match. A title that is only the host name ("www.ftc.gov") never counts as a match.
   - **Site cap:** at most 2 pages per site; www2 and dev copies count as the same site.
   - **robots.txt** is checked, and a disallowed page is dropped.

## Licence notes (defaults for a legal reviewer, not legal advice)
| Note | Meaning |
|---|---|
| `public-domain-us-gov` | US federal government work (17 U.S.C. 105). Only listed federal sites get it; state and foreign `.gov` sites don't |
| `cc-by-4.0`, `cc-by-sa-4.0` | Creative Commons: attribute (and share alike) |
| `copyright-summarise-and-cite` | The default: use only short summaries and always cite (spec §5) |
| `excluded-terms` | The terms forbid reuse: never on the crawl list |

## robots.txt
- **Production (`HttpRobots`):** fetches each site's robots.txt once and follows RFC 9309. A 4xx answer means no rules, so the page is allowed. A 5xx or no answer means assume everything is disallowed.
- **DE-04 still enforces robots.txt** when it crawls. AI-09 checks ahead and labels.
- **The fake (`FixtureRobots`):** uses robots.txt files saved once on 2026-10-26 under `tests/fixtures/search/robots/`. A host the recording laptop couldn't reach (timeouts, a TLS chain it couldn't verify, a dead DNS name) has no file and shows as `unknown`. It isn't marked disallowed, because that would blame the site for a local problem.

## Search providers
`SKILLFORGE_SEARCH` picks the provider:
- **`fake` (the default until we have a key):** replays the results recorded on 2026-10-26 in `tests/fixtures/search/results.yaml`, covering 97 queries. Some of these are kept from earlier registry versions, so not every one is still run.
- **`brave`:** the Brave Search API, with the key in `BRAVE_SEARCH_API_KEY`.

**Recommendation: Brave Search API.** Prices were checked on 2026-10-26.
- **Price:** $5 per 1,000 searches, with a $5 monthly credit, which is about 1,000 free searches a month. A card is needed, and you can set a $5 hard cap.
- **Why Brave:** it has its own full-web index and returns simple JSON, with up to 50 queries a second.
- **Our cost:** at most 8 queries per domain, so refreshing 50 domains takes at most 400 queries ($2). A monthly refresh fits inside the free credit.
- **The alternative:** Tavily, at $8 per 1,000 basic searches with 1,000 free credits a month and no card.
- **Not an option:** Google Custom Search is closed to new customers and shuts down on 1 Jan 2027.

**To switch:** set `BRAVE_SEARCH_API_KEY` and `SKILLFORGE_SEARCH=brave`, then run `pytest -m live tests/knowledge/test_search.py` once. It costs about $0.005.

## Review sheet (done-when)
```bash
python -m evaluation.sources check-data   # the registry is valid and every query has recorded results
python -m evaluation.sources review       # writes evaluation/sources/reports/sources-<date>.md/.json
```
- **One section per seed domain:** each shows the top 10 crawlable sources, with tier, reasons, licence and robots. Below them come the "listed, not crawled" sources (crawl: no, not judged) and the rejected candidates with their reasons.
- **Fewer than 10:** the rules can leave fewer than 10 sources. The automatic check asks for at least 7, the fewest that can still pass.
- **The pass rule:** a domain passes at 7 or more good sources in its top 10, with no junk in its top 5. A good source is authoritative, on topic and usable. AI-09 is done when all 10 domains pass.
- **Never overwrites:** a second run on the same day writes `-2`.
- **Review history:** a reviewer's verdict is stored in the judged sheet's JSON as `human_review`, with reviewer, date, pass or fail, good count per domain, and notes. Every new sheet lists the earlier verdicts under "Review history".
  - **2026-10-26, Ziad Abdullah:** `sources-2026-10-26-2` failed, with 3 of 10 domains passing. The main problem was .gov and .edu pages ranking high without being useful. That review led to the non-content blocks, the duplicate checks, the named authorities and the `eng-practices` rule.
  - **2026-10-26, Ziad Abdullah:** `sources-2026-10-26-3` failed, with 7 of 10 domains passing. HR, marketing and legal failed:
    - HR: DOL's own job page at #1.
    - Marketing: untitled FTC pages and an EPA program page.
    - Legal: index, transparency-data, FOI and procurement pages.

    The fixes were pinned sources, blocks for job, FOI, transparency-data and index pages, real titles for untitled pages (and demotion when there is still none), and US-first ranking for legal.
  - **2026-10-26, Ziad Abdullah:** `sources-2026-10-26-4` failed, with 8 of 10 domains passing. Two failed:
    - technology/ai: an Atlassian course, a Medium post and a 0-topic-word Idaho page.
    - legal/contracts: CBCA in the top 5, and crawl: no sources taking top places.

    The fixes were general rules: a pin is needed for unknown sites, pages with no topic word and sources for other areas only; crawl: no sources are listed apart. Also pins for technology/ai and federal `.gov` hosts in the registry.
  - **2026-10-26, Ziad Abdullah:** `sources-2026-10-26-5` **passed**: all 10 domains, with no junk in any top 5. **AI-09 is done.** Legal passed at the minimum (7 of 8), and its #6-8 are UK sources.

**Follow-ups:** switch to Brave Search when a key exists; add more US legal pins over time.

## Known limits
- **The ranking can only pick from what search returns.** Generic domain queries ("AI best practices") bring back many vendor blogs. The `site:.gov` and `site:.edu` queries are what bring in authoritative candidates. Better queries are the main lever, which is what the domain hints are for. Even then, the recording tool did not return some named authorities' best pages: no Cornell LII Wex NDA entry, no SHRM structured-interview toolkit and no IPR press-relations page. Brave, which honours `site:`, should do better.
- **The authority bonus lifts any page of the site.** A named authority's off-topic page (e.g. a press-office news item) can still rank high. That is why no CIPR query is run: the recorded search returned only its newsroom.
- **The fake has no snippets.** The recording tool returns none, so relevance uses titles and URLs. Brave returns descriptions, which improves relevance.
- **Some recorded titles were only the host name.** Each such page was fetched once, on 2026-10-26, honouring robots.txt, to record its real `<title>`. The fixture keeps the search tool's version as `search_title`. Pages that still have no title (PDFs, refused requests) rank below titled ones.
- **US-centric.** Federal public-domain rules and US suffixes are listed in most detail. Other countries' government sites rank as official, with the default licence. A legal source's jurisdiction tells the reviewer when a page describes another country's or a single state's law.
