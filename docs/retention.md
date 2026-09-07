# Event retention

Short version: **nothing is deleted, on purpose.** This file records the
measurements behind that decision so the next person does not have to guess,
and names the trigger that should change it.

## What grows

| Table | Where | Grows with | Bounded? |
|---|---|---|---|
| `events` | local SQLite | every captured edit/write/diff/commit | no |
| `events` | D1 | every synced event | no |
| `known_repos` | local SQLite | distinct working directories | effectively yes |
| `agg_language`, `agg_event_type`, `agg_totals` | D1 | languages / event types / one row | yes |
| `agg_day` | D1 | one row per active day | **yes — pruned** |

`agg_day` was the only rollup that would have grown forever (a row a day), and
the nightly rebuild already deletes everything older than the heatmap window
plus a fortnight of slack (`AGG_DAY_KEEP_DAYS` in `worker/src/index.ts`).

## Measured rate

From the reference installation, 2026-07-05 to 2026-09-07 (65 days of daily
use in `claude` mode, which is the chattier of the two capture modes — it
records one row per agent tool call rather than one per commit):

```
21,066 events over 65 days  =  ~325 events/day  =  ~119,000/year
local events.db: 1.16 MB total, including project_key and both indexes
```

Row width in D1 is narrower than local (no `project_key`, no `synced`; plus
`source_id`), so:

```
projected D1 growth: roughly 6-7 MB per year of heavy daily use
D1 free tier storage: 5 GB
```

That is on the order of **centuries** of headroom, so storage is not the
constraint. Nor are reads: the card renders exclusively from rollups, so a
render costs a fixed handful of rows no matter how large `events` is. The only
thing that touches every row is the nightly rebuild — one pass over ~119k rows
a day, against a 5,000,000 reads/day allowance.

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

That is a real amount of machinery, and it buys nothing at 6 MB/year. Building
it now would trade a working invariant ("the rollups can always be rebuilt from
the events") for complexity that solves no observed problem.

## The trigger

Revisit if any of these becomes true:

- `events` passes ~5 million rows (roughly 40 years at the measured rate, or
  much sooner for a shared/multi-user deployment);
- the nightly rebuild starts approaching D1's daily read allowance;
- a deployment needs the raw history gone for a privacy or legal reason.

The first two are visible in the D1 dashboard. The third is a policy decision,
not a capacity one, and would want the compaction design above rather than a
bare `DELETE`.

## What is already safe to prune

- `agg_day` — pruned nightly, no action needed.
- Local `known_repos` — 75 rows after two months; it stores raw working
  directories, and only the *count* of distinct git roots is ever published.
- Local `events` — a user who wants their local history gone can delete
  `~/.claude/devcard/events.db`. Since the composite `(source_id,
  client_event_id)` identity landed, that is safe: `~/.claude/devcard/source-id`
  survives the deletion, so the restarted rowid sequence continues in the same
  namespace and already-synced events are neither re-sent nor re-counted. Before
  that change the same act silently dropped the first N events of the new
  database as duplicates.

## Read performance, locally

`get_unsynced_events` runs every ~20 seconds and asks `WHERE synced = 0`. On a
table that only grows that was a full scan of the entire history several times
a minute. `init_db` now creates a partial index:

```sql
CREATE INDEX IF NOT EXISTS idx_events_unsynced ON events(id) WHERE synced = 0
```

which is what makes leaving the table to grow cheap rather than merely
tolerable. It is created on existing databases too, not just new ones.
