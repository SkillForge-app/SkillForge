# Proposal: a table for the per-host site boilerplate (DE-09)

Status: proposal, not applied. No schema or view was changed. 8 November 2026; updated 17 November 2026 after Backend's first review (in principle agreed).

## Why

[data-architecture.md](../data-architecture.md) ("Site boilerplate: once per host, in the DE-09 cache") says AI's `find_site_boilerplate(...)`
should run **once per host, not once per page**, and its result be cached with the domain knowledge cache: a small record per host with the
sentence hashes that `ExtractConfig.site_boilerplate` needs. The schema has no place for it, so the pipeline cannot reuse it between runs and the
cache code in `skillforge_data/cache.py` does not cover it.

## What AI's code says about the hashes (read from `ai/core/knowledge/extract.py` on main; **from the code, waiting for AI to confirm**)

| Question | Answer in the code |
|---|---|
| Hash type | `sha256` hex digest, **64 lower-case hex characters** (`_sentence_key`) |
| What is hashed | the sentence lower-cased, whitespace collapsed (`" ".join(s.lower().split())`), UTF-8; only sentences of **6 or more words** (`SITE_BOILERPLATE_MIN_WORDS`) |
| Selection rule | a sentence found on at least `min_pages` (default 2) pages of the host |
| What `find_site_boilerplate(pages, min_pages=2)` returns | `{host: tuple[str, ...]}`, hashes **sorted**, one entry per host; `pages` are `(html, url)` pairs |
| The key (`host`) | `pydantic.HttpUrl(url).host`: lower-case, IDN as punycode, IPv6 in brackets, no port, no `user:password@`, a trailing dot is kept (measured here with pydantic 2.14.2; AI pins `<3`) |
| How it is used | `ExtractConfig(site_boilerplate=hashes)`, a `tuple[str, ...]`; **not** in `fingerprint()` (`FINGERPRINT_EXCLUDED`) |
| How big | one hash is 64 bytes; a site with a few hundred repeated sentences is some tens of kB; there is no limit in the code |

**Storage shape that follows:** one row per host, `sentence_hashes text[]` (kept in the order AI returns: sorted), each element 64 hex
(a CHECK can enforce it), plus `pages_used`, `extractor_version` (AI's `EXTRACTION_VERSION`) and `computed_at`.

## How the code of DE normalises a host today (17 Nov 2026)

They are **not** all the same:

| Where | Rule | Used for |
|---|---|---|
| `crawler/fetcher.py` `_host_key()` and `crawler/robots.py` (`_origin`, redirect host checks) | `urlsplit(url).netloc.lower()`: keeps a port (also a default one: `example.org:443` differs from `example.org`) and keeps `user:password@` | per-domain rate limit, robots.txt cache key |
| `crawler/fetcher.py` deny-list check | `urlsplit(url).hostname.lower()`: no port, no user info | deny-list |
| `crawler/run.py`, `pipeline/process.py`, `licensing.py` | `(urlsplit(canonical).hostname or "").lower()`: no port, no user info, **IPv6 without brackets**, IDN not converted | `knowledge.sources.host` |
| `storage/keys.py` | `host.lower()` of the stored value | object keys |
| `cache.py` | reads `sources.host` as stored | domain cache |
| AI `normalise_url` | host lower-case, **non-default port kept, default port dropped (pydantic)**, no `user:password@`, IPv6 in brackets | canonical URL |
| AI `find_site_boilerplate` | `HttpUrl.host`: as above, no port, punycode | the key of its result |

Consequences: the same site can have two rate-limit buckets (`example.org` and `example.org:443` if a URL is written with the port),
a host with a user name in the URL would get its own bucket and its own robots.txt entry, an IDN host would not match the key AI returns,
and an IPv6 host is `::1` in our table but `[::1]` in AI's.

**Decision (proposed; not implemented, because this task changes proposals only):** one small module (`skillforge_data/hosts.py`)
with the rules of AI's `normalise_url`, and every place above calls it:

- `host_of(url)`: lower-case, IDN as punycode, IPv6 in brackets, **no port, no `user:password@`**, computed from `normalise_url(url)`. It is
  the value of `sources.host`, the key of `host_boilerplate`, the deny-list check and the object keys. It equals AI's
  `HttpUrl(url).host`, so `find_site_boilerplate(...)[host_of(url)]` always finds the entry.
- `origin_of(url)`: `scheme://host[:port]` with a **non-default** port kept and a default one dropped. It is the key of the rate limiter
  and of the robots.txt cache (a different port is a different server).

Both start from `normalise_url`'s output, so a spelling cannot differ between the crawler, the cache and AI. A migration for old rows
is not needed for hosts written without a port, user name or IDN; rows with such a host would be rewritten by the same helper.

## Proposed SQL

```sql
CREATE TABLE knowledge.host_boilerplate (
    host              text        PRIMARY KEY CHECK (host = lower(host) AND btrim(host) <> '' AND host !~ '[/@:]'
                                                       OR host ~ '^\[[0-9a-f:.]+\]$'),   -- host_of(): no port, no user info
    sentence_hashes   text[]      NOT NULL DEFAULT '{}'
                      CHECK (array_to_string(sentence_hashes, '') ~ '^[0-9a-f]*$'),        -- sha256 hex, as AI returns them
    pages_used        integer     NOT NULL CHECK (pages_used >= 0),   -- how many pages of the host it was computed from
    extractor_version integer     NOT NULL,                           -- AI's EXTRACTION_VERSION when it was computed
    computed_at       timestamptz NOT NULL DEFAULT now()
);
```

### Writing it: the older write must not beat the newer one

Two workers can compute the same host at the same time. The write is an upsert that keeps the **newer** computation, decided by
`computed_at` (the time the pages were read, not the time of the write):

```sql
INSERT INTO knowledge.host_boilerplate (host, sentence_hashes, pages_used, extractor_version, computed_at)
VALUES (%(host)s, %(hashes)s, %(pages)s, %(version)s, %(computed_at)s)
ON CONFLICT (host) DO UPDATE
SET sentence_hashes   = EXCLUDED.sentence_hashes,
    pages_used        = EXCLUDED.pages_used,
    extractor_version = EXCLUDED.extractor_version,
    computed_at       = EXCLUDED.computed_at
WHERE EXCLUDED.computed_at > knowledge.host_boilerplate.computed_at;     -- an older write does nothing
```

When the `WHERE` is false the statement changes no row; the caller can detect that (`rowcount = 0`) and read the stored record
instead of using its own.

### Expiry and recompute policy (**assumption**: nothing in AI's code or the task plan says; to be confirmed by AI)

- A record is **stale** after **30 days** (same as the web freshness rule in `skillforge_data/freshness.py`), or when its
  `extractor_version` differs from AI's current `EXTRACTION_VERSION`, or when the host now has at least twice the `pages_used` it was
  computed from (more pages find more repeated sentences).
- A stale record is **still used** until the recompute finishes; it is replaced by the upsert above.
- Recompute at most once per host per crawl run, not once per page, with `min_pages = 2` (AI's default), only when the host has at least
  2 stored pages. A host with fewer pages gets no row (an empty tuple is the same as no record).

The record is not part of the chunk config hash (AI's fingerprint leaves `site_boilerplate` out on purpose), so changing it does not rebuild
chunks by itself; whether a changed record should trigger a re-extraction of the host's pages is for AI to say.

### Tested (17 Nov 2026)

The `CREATE TABLE` and the upsert above were run on a throwaway database (dropped afterwards; the real database was not touched):
a first write is stored; an **older** `computed_at` changes nothing (`rowcount = 0`) and the stored hashes stay; a **newer** one replaces
them; `[::1]` is accepted; `Example.org`, `example.org:8080`, `u@example.org` and a non-hex hash are rejected by the CHECKs.

## Who must approve

- **Backend**: it is a change to the database schema (shared with Backend).
- **AI**: they own the content and the format of `site_boilerplate` (hash type and length, how it ages, when to recompute), and the function that makes it.
- Not a change to `knowledge_views.sql`: AI and the retrieval API do not read this table.

After it is applied the local database volume must be reset (`docker compose down -v`, then `up -d`), because the root `compose.yaml` applies the schema
only on the first start of an empty volume.

## What the code will do once it exists

`cache.py` gets two functions: read the record for a host (and tell if it is older than the freshness window or from another `extractor_version`),
and write it after AI's function ran. `process_document` takes the hashes through the extraction adapter. Until then nothing in P2 depends on it.
