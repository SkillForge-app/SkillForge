# Questions for Backend: user data and deletion (DE-13)

Status: **questions, no proposal yet**. Nothing is applied and nothing was guessed. 17 November 2026. DE-13 "Done when" (task plan): a deletion
request removes user data within the agreed time. It needs BE-04 (auth).

## What Data Engineering holds today (checked in the schema and the code)

The `knowledge` tables hold **public web content only**: `sources` (URL, host, licence), `documents`, `chunks`, `embeddings`, `crawl_runs`,
`source_domains`, plus raw and clean text in object storage. No table has a user id, an email, or a request. `data-architecture.md` already says user
requests and accounts belong to Backend. The retention rules for what we do hold are enforced by `storage/jobs.py` (raw pages, orphans) and
`storage/retention.py` (superseded documents after 90 days, crawl runs after 12 months).

What is **not known** is what could reach us from Backend, so I wrote questions instead of a design.

## Questions

1. **What user data can reach Data Engineering?** Does Backend ever send us anything with a user id, an email, a name or free text a user typed
   (for example the request that starts a crawl for a domain)? If the answer is "nothing", DE-13 reduces to retention and a data map.
2. **Do we store requests?** `crawl_runs.skill_domain` holds the domain a run was started for. If a user's request text ever becomes a `skill_domain`, a source URL or a log
   line, that is personal data in our tables. Can Backend guarantee that only names from the fixed domain list reach us?
3. **Analytics (DE-12):** will events carry a user id (even a pseudonymous one)? If yes, a deletion request must reach the events table, and the event schema needs a deletable
   actor key from the start. Who owns that deletion: Backend (their user) or DE (our events table)?
4. **Evaluation data (DE-10):** human labels are made by people. Are the labelers' identities stored? (Our proposal `de-10-datasets.md` has no labeler id on purpose; say if one is needed.)
5. **Logs:** our logs keep 90 days (retention table). Do request logs from the API contain user data that comes with a request to us? Who deletes them?
6. **Deletion request path:** how will a deletion reach us (an API call, a queue message, a manual ticket)? What does Backend send (a user id only)?
7. **The agreed time:** the Done-when says "within the agreed time". **That time is written nowhere in the repo.** Which number is it (assumption for planning only: 30 days, the common
   legal maximum)? Who agreed it, and does it include backups (a backup older than the time still contains the user's data until it expires)?
8. **Backups (DE-14):** if user data is ever in our database, deletion must also cover backups. Is "it expires with the backup retention" acceptable, or must backups be edited?
9. **Pages that mention people:** crawled public pages can name private persons. Is a takedown request ("remove this URL") in scope? Proposed handling, no code yet: delete the
   `sources` row (documents, chunks and embeddings cascade; raw and clean objects go through the orphan sweep) and add the URL to the crawler's deny-list so it is not fetched again.
10. **Who is the contact** for privacy requests on the product side (the owner), so the process has a name on it?

## What I can build now without any answer

- The retention jobs (done: `storage/retention.py`).
- A data map in `docs/privacy.md` (which store holds what), once the answers to 1 to 3 exist.
- A "remove this URL" command with an audit line that holds no personal data (question 9).
