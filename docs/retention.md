# Event retention

Short version: **nothing is deleted, on purpose.** This page gives the capacity
reasoning behind that, a way to measure your own installation, and the trigger
that should change the decision.

## What grows

| Table | Where | Grows with | Bounded? |
|---|---|---|---|
| `events` | local SQLite | every captured edit/write/diff/commit | no |
| `events` | D1 | every synced event | no |
| `known_repos` | local SQLite | distinct working directories | effectively yes |
| `agg_language`, `agg_event_type`, `agg_totals` | D1 | languages / event types / one row | yes |
| `agg_day` | D1 | one row per active day | **yes — pruned** |

`agg_day` was the only rollup that would have grown forever (a row a day), and
the nightly rebuild deletes everything older than the heatmap window plus a
fortnight of slack (`AGG_DAY_KEEP_DAYS` in `worker/src/index.ts`).

## Capacity, in orders of magnitude

`claude` mode is the chattier capture mode — one row per agent tool call rather
than one per commit — so it sets the upper bound. A reference installation used
for daily, agent-heavy work produced **a few hundred events a day**. Rounded up
generously:

```
~500 events/day            →  ~200,000 events/year
one D1 events row          ≈  100 bytes, indexes included
                           →  ~20 MB/year
D1 free-tier storage       =  5 GB   →  centuries of headroom
```

Storage is not the constraint, and neither are reads: the card renders from
rollups only, so a render costs a fixed handful of rows no matter how large
`events` becomes. The only full pass is the nightly rebuild — about 200,000 rows
a day at that rate, against a free-tier allowance of 5,000,000 rows read per day.

The per-row estimate is deliberately pessimistic: a D1 row here is six integers,
a short language name and a 32-character installation id, plus the unique index
on `(source_id, client_event_id)`.

## Measure your own

The numbers above are an envelope, not a promise. Your installation's own,
without trusting anybody's estimate:

```bash
cd worker
npx wrangler d1 info devcard            # database size, as Cloudflare bills it
npx wrangler d1 execute devcard --remote --command \
  "SELECT COUNT(*) AS events, (MAX(ts) - MIN(ts)) / 86400 AS days,
          COUNT(*) * 86400.0 / MAX(1, MAX(ts) - MIN(ts)) AS per_day
   FROM events"
```

Divide the size by `events` for your real bytes per row, and multiply `per_day`
by 365 for your yearly growth.

## Why deleting would cost more than it saves

Raw `events` is load-bearing for exactly one thing: the nightly
`rebuildRollups`, which recomputes `agg_language`, `agg_event_type` and
`agg_totals` **from the full table**. Delete old rows and those totals shrink
to whatever survived — the card's lifetime "lines written" would silently fall
every time the pruner ran.

Making retention safe therefore means more than a `DELETE`:

1. a compacted base row (per language, per type, per day) holding everything
   older than the retention window;
2. a rebuild that starts from that base instead of from zero;
3. a way to tell an already-compacted range from a live one, so a re-run does
   not double-count the base.

That is a real amount of machinery, and at tens of megabytes a year it buys
nothing. Building it now would trade a working invariant ("the rollups can
always be rebuilt from the events") for complexity that solves no observed
problem.

## The trigger

Revisit if any of these becomes true:

- `events` passes ~5 million rows (decades at the rate above, much sooner for a
  shared deployment);
- the nightly rebuild starts approaching D1's daily read allowance;
- a deployment needs the raw history gone for a privacy or legal reason.

The first two are visible in the D1 dashboard. The third is a policy decision,
not a capacity one, and would want the compaction design above rather than a
bare `DELETE`.

## What is already safe to prune

- `agg_day` — pruned nightly, no action needed.
- Local `known_repos` — stores raw working directories and stays small; only the
  *count* of distinct git roots is ever published.
- Local `events` — delete `~/.claude/devcard/events.db` if you want your local
  history gone. `~/.claude/devcard/source-id` survives the deletion, so the
  restarted row-id sequence continues in the same namespace and events already
  synced are neither re-sent nor re-counted.

## Read performance, locally

The syncer asks for `WHERE synced = 0` every time it runs. On a table that only
grows, that would be a scan of the entire history several times a minute, so
`init_db` creates a partial index:

```sql
CREATE INDEX IF NOT EXISTS idx_events_unsynced ON events(id) WHERE synced = 0
```

which is what makes leaving the table to grow cheap rather than merely
tolerable. It is created on existing databases too, not just new ones.
