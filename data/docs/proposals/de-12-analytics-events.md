# Proposal: analytics event schema (DE-12)

Status: proposal, **not applied**; a first draft to be corrected by the consumers. 17 November 2026.
DE-12 in the task plan: *event schema and dashboards (requests, success rate, cost, ratings)*. **Done when: the dashboard is used in the weekly review.** Needs: BE-18.
**This schema is a contract: producer DE, consumers Frontend and Backend.** Per `CLAUDE.md` it changes only through a PR that they approve. Nothing here is a decision: I only
wrote a draft so there is something to correct. **Which events exist is for Frontend and Backend to say** (questions below); the catalog is my guess from the four words in the task text.

## Design

- **One append-only table of events**, `analytics.events`, partitioned by month (assumption: partitions keep deletes cheap: retention drops a partition).
- **One envelope for all events**, and the event-specific fields in `properties jsonb`. Adding a new event or a new optional property needs no migration.
- **Each event name has a version** (`schema_version`). Within a version only additive changes (a new optional property); a breaking change (rename, remove, change a type) is a new version, and the old one is
  produced until every consumer has moved. This is the contract rule.
- **No personal data in an event.** The actor is an anonymous key (`actor_key`): a random id of the account or the session that Backend creates, never an email or a name. Free text typed by a user
  (the request text) is **not an allowed property**; only counts, ids, enumerated values and numbers. A CHECK refuses a short list of property names that smell like personal data (a safety net, not a
  guarantee).
- **Deletion:** if an `actor_key` identifies an account, a deletion request must be able to remove that actor's events (`DELETE ... WHERE actor_key = $1`; an index on it). Open question 3 of
  `de-13-user-data.md`.

## Proposed SQL

```sql
CREATE SCHEMA analytics;

CREATE TABLE analytics.events (
    event_id       uuid        NOT NULL,                       -- created by the producer: sending the same event twice is harmless
    event_name     text        NOT NULL CHECK (event_name ~ '^[a-z][a-z0-9_]*$'),
    schema_version integer     NOT NULL CHECK (schema_version >= 1),
    occurred_at    timestamptz NOT NULL,                       -- when it happened, by the producer's clock
    received_at    timestamptz NOT NULL DEFAULT now(),
    producer       text        NOT NULL CHECK (producer IN ('frontend', 'backend', 'data', 'ai')),
    actor_key      text,                                        -- anonymous account or session key, or NULL (system events)
    properties     jsonb       NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(properties) = 'object'),
    PRIMARY KEY (event_id, occurred_at),
    CHECK (NOT (properties ?| ARRAY['email', 'name', 'user_name', 'password', 'prompt', 'request_text', 'ip', 'ip_address']))
) PARTITION BY RANGE (occurred_at);

CREATE INDEX events_name_time_idx ON analytics.events (event_name, occurred_at);
CREATE INDEX events_actor_idx ON analytics.events (actor_key) WHERE actor_key IS NOT NULL;
```

Partitions are created by a small monthly job (not part of this proposal), for example `CREATE TABLE analytics.events_2026_11 PARTITION OF analytics.events FOR VALUES FROM ('2026-11-01') TO ('2026-12-01')`.
A `DEFAULT` partition catches events with a wrong clock so that none is lost.

## Draft event catalog (**my guess**: each row needs its producer's yes or no)

| Event | Producer | Properties (all optional unless marked) | Used for |
|---|---|---|---|
| `skill_requested` | backend | `domain`, `platform` (`claude_code` or `codex`), `request_id` **required** | requests per week |
| `skill_generated` | backend | `request_id` **required**, `outcome` **required** (`success`, `failure`, `rejected`), `duration_ms`, `cost_usd`, `input_tokens`, `output_tokens`, `model`, `failure_reason` (an enumerated code, not text) | success rate, cost |
| `skill_downloaded` | frontend | `request_id` **required**, `platform` | conversion |
| `skill_rated` | frontend | `request_id` **required**, `rating` **required** (integer 1 to 5), `has_comment` (boolean; **never the comment**) | ratings |
| `retrieval_called` | data | `domain`, `passages` (count), `latency_ms`, `cache` (`hit`, `miss`) | knowledge usage, cache use (DE-09) |
| `crawl_run_finished` | data | `run_id` **required**, `status`, `pages_fetched`, `pages_failed`, `duplicate_rate` | pipeline health (also in DE-11) |

`request_id` is what ties a request, its result, its download and its rating together; it must be the same random id in all of them (it is not the user's id).

## Dashboards (queries for the weekly review; draft)

```sql
-- requests, success rate, cost and rating, per week
SELECT date_trunc('week', occurred_at) AS week,
       count(*) FILTER (WHERE event_name = 'skill_requested')                                    AS requests,
       round(100.0 * count(*) FILTER (WHERE event_name = 'skill_generated' AND properties->>'outcome' = 'success')
             / NULLIF(count(*) FILTER (WHERE event_name = 'skill_generated'), 0), 1)              AS success_rate_pct,
       round(sum((properties->>'cost_usd')::numeric) FILTER (WHERE event_name = 'skill_generated'), 2) AS cost_usd,
       round(avg((properties->>'rating')::numeric) FILTER (WHERE event_name = 'skill_rated'), 2)  AS avg_rating
FROM analytics.events
GROUP BY 1 ORDER BY 1 DESC;
```

Tested on a throwaway database (17 Nov 2026): the table, a monthly partition and a default partition, inserts, the refusal of events with `email` or `prompt` properties, and this query
(3 requests, 66.7% success, cost 0.35, average rating 4.5 on the test events). Not tested: volume.

The dashboard tool is open (plain SQL views, Metabase, Grafana): see question 6.

## Questions for Frontend

1. Which user actions do you want measured (page views, a generation started, a download, a rating, a share)? Please list the events you would emit and their fields; the table above is only a guess.
2. How do you send an event: through a Backend endpoint (recommended: one place that validates), or directly? Who generates `event_id` and `request_id`?
3. What identifies a visitor before login: a session cookie id? Do you need consent handling (a banner) before any event is sent, and which events are allowed without it?
4. Which questions should the weekly review answer? (Please write them as sentences: "how many requests per domain", "which step loses users".) The dashboards come from the questions, not from the events.

## Questions for Backend (BE-18)

1. Do you already log requests and costs somewhere? If yes, is analytics a copy of that or a new source? Duplicate sources give two answers to the same question.
2. What is `actor_key`: the account id, a hash of it, a session id? It must not be reversible to an email. Who creates it?
3. Where do events go: your service inserts into `analytics.events` (then it needs a role with `INSERT` only), or sends them to a queue that a DE job reads?
4. Cost: do you know the cost of a generation (`cost_usd`) at request time, or only later? Is it the model cost only?
5. A **new schema `analytics`** in the shared database: acceptable? Who owns migrations (which tool)? Partitioning by month needs a monthly job: who runs it?
6. Retention for events (assumption: 24 months for aggregates, 13 months for raw events; nobody has agreed a number) and the deletion path (question 3 of `de-13-user-data.md`).

## Questions for the owner

Who attends the weekly review and which tool should they open? (The "Done when" is that the dashboard is *used*.)

## Not proposed

Event collection from the browser (a script, a pixel), A/B testing, and per-user profiles.
