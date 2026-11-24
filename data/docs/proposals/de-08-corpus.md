# Proposal: what the SKILL.md corpus (DE-08 collector) still needs from the schema

Status: proposal, **not applied**. No schema or view was changed. 17 November 2026.

## What the collector uses today (no schema change needed)

`skillforge_data/corpus/` stores an allowed file as: a `sources` row with `source_type = 'skill_md'` (already allowed by the CHECK), `url`, `host`,
`license` (the SPDX id) and `license_source = 'repo'` (already allowed: `page`, `repo`, `manual`, `unknown`); and one `documents` row through
`record_document_version()` with `content_hash`, `fetched_at`, `license`, `http_status = 200`, the title `owner/repo: path`, and `raw_object_key`
when a storage is given. Checked: all values fit the existing columns and CHECKs; the tests insert them.

## What is missing (each is optional; none blocks the collector)

1. **Refused files leave no trace except the log and the run report.** The collector counts them by licence (`CorpusReport.refused_by_licence`) but nothing is
   written to the database, so DE-11 cannot alert on "the corpus shrank" or "many files refused". Options: (a) a counter `crawl_runs.pages_refused`
   (the crawler could use it too, for pages whose licence it refuses) and a run row per collector run; (b) a small `corpus_runs` table.
   I prefer (a): one run concept. **Backend must approve** (schema).
2. **No place for the repository and the commit.** `sources.url` is the only identifier, so repo name, path and commit are inside the URL. A URL with a
   branch name (`/blob/main/...`) is stable but not immutable; a URL with a commit SHA is immutable but every commit would be a **new source**. The collector uses
   whatever URL the client gives. Attribution (`licensing.attribution(url, licence)`) works with either. If AI needs "which commit did this example come from",
   add `sources.repo_ref text` (nullable). Question for AI.
3. **The licence is the repository's, not the file's.** GitHub reports one SPDX id per repository. A `SKILL.md` inside a sub-folder with its own `LICENSE`, or a
   repository with several licences, is judged by the repository's id (`NOASSERTION` and `other` are read as unknown, so refused). That is **assumption**: stricter is
   safe, but some good files are lost. Reading the nearest `LICENSE` file with `detect_licence_text` is possible (the function exists) and costs one more call per file.
4. **A withdrawal deletes rows.** If a repository changes to a refused licence, the collector deletes the source and its documents (cascade) so the file cannot be used
   any more. The raw object is removed later by the orphan sweep. It is the safe reading of "only permissive files used"; **to confirm with AI**: should we instead keep the
   row, mark it unusable, and let the consumer filter (a column or a view change, which is a contract change)?
5. **Which domain does a skill file serve?** `source_domains` is empty for these sources. AI decides how example skills are chosen; if by domain, someone must set them.

## Not proposed

Storing the content of refused files, or their hashes: "only permissively licensed files used" and "store only what is needed". The collector never downloads them.
