# What the numbers mean

Two capture modes, counting different things on purpose.

**`git` mode** reads `git diff --numstat` per commit, so a line is a real net
change. One caveat: `git commit --amend` fires `post-commit` again, and the
amended commit's whole diff is read a second time, so an amend-heavy workflow
over-reports. The same class of gap as squash merges, below.

**`claude` mode** counts written output — an edit counts the region it replaced,
a write counts the file. That is why the card says *lines written* rather than
*lines of code*: it measures what a session produced, not the size of a
codebase. Commits here are counted from the agent's own `git commit`
invocations, and `--amend` *is* excluded, because it rewrites one already
counted.

## Agent attribution

Capture modes remain **exclusive per machine**. With an installed `mode` marker,
the Claude Code hook records only in `claude` mode and the git hook records only
in `git` mode. Other marker values suppress both hooks. A missing marker retains
the legacy defaults; select one mode when installing rather than enabling both
hooks without a marker. Attribution does not change line or commit counting.

Each new hook event records its origin using a fixed allowlist:

| Agent | Meaning |
|---|---|
| `claude-code` | A Claude Code hook event, including its captured commit invocations |
| `git` | A git post-commit event, including every per-language diff row |
| `codex` | Reserved for an explicit Codex capture adapter |
| `unknown` | Origin is unavailable |

`git` identifies the capture mechanism, not the person or agent that authored a
commit. Commit messages, co-author trailers and the currently installed mode
are not used to infer authorship. There is no manual-coding attribution here.

The local SQLite upgrade adds a nullable `agent` column with an allowlist
constraint. It is idempotent and preserves existing rows, counts, sync flags
and event identities. **All rows predating attribution stay NULL and read as
`unknown`** in activity aggregates: this implementation does not infer their
origin, even from their event type. The machine's present mode cannot prove
which hook captured an older event. Missing attribution on an imported event
also reads as `unknown`; new explicit values outside the allowlist are rejected.

The extension point for Codex is a normalized event passed to
`devcard_lib.insert_event(conn, event)` with `event["agent"] = "codex"`. An
adapter must select its own exclusive machine capture mode and keep the same
counting units. This provides the schema and API, not a Codex code-edit hook;
the separate usage scanner reads Codex token logs. Git-mode commits remain
attributed to `git`.

## Estimated active time

`devcard_activity.active_minutes(events, timezone=...)` estimates activity from
captured Unix timestamps. It sorts and deduplicates timestamps **per agent**.
A gap **greater than 15 minutes** ends a session; a gap of exactly 15 minutes
continues it. Each session contributes its first-to-last elapsed time plus a
**2-minute tail**, so a single event contributes 2 minutes. Both values are
configurable through `idle_minutes` and `tail_minutes` (nonnegative minutes).
Multiple language rows and a commit at the same timestamp share one time signal.

Sessions and tails crossing midnight are split across local calendar days in
the explicitly supplied IANA timezone or Python `tzinfo`. Durations use elapsed
Unix time, including across daylight-saving changes. No machine-local timezone
is assumed. IANA names require an available timezone database; an explicit
Python `datetime.timezone` offset works without one. Interleaved agents have
independent sessions: one agent's events
cannot keep another agent's session open. Concurrent sessions can overlap, so
the sum is estimated **agent time**, which can exceed elapsed wall time; it is
not a measure of human attention or actual agent runtime.

This is an **estimate**, unlike WakaTime's editor heartbeats. Sparse commits
miss work between commits; dense edits can span time when nobody is typing.
The tail is a convention, not observed work. These numbers are unsuitable as
precise time sheets or evidence of human coding time.

`devcard_activity.export_aggregate(conn, timezone=...)` returns UTF-8 JSON bytes
with `agents` totals (events, commits, code edits, lines added/removed, bytes
added and active minutes) and `active_minutes` by ISO day and agent. Git `diff`
rows are not counted as code edits. Per-agent counts sum to the captured totals;
per-agent active minutes sum to the daily estimates. NULL agents are grouped
under `unknown`. The SQL projection excludes projects, paths, source ids and
event row ids; the exported bytes also omit languages, raw timestamps, event
types and code content. Only fixed agent labels, dates and numbers are exported.
The local dashboard always reads this export; the published machine JSON
carries it only when `card.show_agents` is on (default off), and machine merges
then sum the agent totals and daily estimates. The same flag shows the line
proportions and estimated active time on the card. Activity estimates use
the configured IANA timezone or UTC when no timezone is set. The legacy
Worker sync payload and renderer remain unchanged.

## "code edits" is a claude-mode number

The two modes do not produce a comparable *count of actions*. In `claude` mode
one row is one agent tool call. In `git` mode one row is a per-commit,
per-language aggregate — two commits touching Python and TypeScript make four
rows, which is not "four edits" in any sense a reader would assume.

So the card does not print one. Git-mode rows are stored under their own event
type (`diff`), and the **`code edits` stat only appears on a card that has agent
edits to report**; a git-captured card shows commits alone. Lines, bytes,
languages, the heatmap and the streak are computed identically in both modes and
are shown in both.

## Merge commits

A merge commit **counts as one commit and contributes no lines.**

`git diff HEAD~1 HEAD` on a merge reports every line the merged branch brought
in — lines already counted when each of those commits was made. Counting them
again inflated the card by the whole size of every branch ever merged. This is
also what `git diff-tree --cc` says: a clean merge introduces no content of its
own.

| Case | Counted as |
|---|---|
| Ordinary commit | its own diff against its parent |
| Repository's first commit | its whole tree |
| Merge commit (2+ parents) | one commit, zero lines |
| Fast-forward merge | nothing — git creates no commit, so no hook runs |
| Conflict resolution merge | one commit, zero lines |

Two known limits, stated rather than hidden. A merge that resolves conflicts by
hand can introduce genuinely new lines; those are not counted either, so that
case under-reports by a few lines instead of over-reporting by a branch. And a
**squash merge** produces an ordinary single-parent commit that is
indistinguishable from hand-written work — it is counted in full, so if the
squashed branch's own commits were also captured on this machine, those lines
are counted twice.

Most merges never reach the hook at all: git runs `post-merge`, not
`post-commit`, when it creates the merge commit itself. The ones that do arrive
are `--no-commit` merges and conflict resolutions, which end in an explicit
`git commit`.

## Using two machines with the serverless card

Each machine publishes its own totals as `machines/<source_id>.json` on the
`devcard-data` branch and renders the card from every machine's file: lines,
languages, events, bytes and lines per day are summed; the repository count is
the largest any machine reports (they all read the same GitHub account), not
the sum. Days are each machine's own local days. See
[the serverless card](serverless.md#several-machines).

## Event identity, and using two machines with the legacy Worker

Each event carries the local SQLite rowid that produced it, and ingest ignores a
row it has already stored — that is what makes a retried batch after a lost
response count once instead of twice.

A rowid alone is not a global identity, though: every install's sequence starts
at 1. So each installation also generates a random, opaque `source_id` (16 bytes
of `secrets.token_hex`, cached in `~/.claude/devcard/source-id`), and identity is
the pair. That means:

- **two machines can share one backend** — machine B's event 1 is no longer
  mistaken for machine A's and silently dropped (set up the second machine by
  [copying three files](manual-setup.md#adding-a-second-machine), not by
  re-running the installer, which rotates the token);
- **deleting `~/.claude/devcard/events.db` is safe** — a new database retires
  the old `source_id`, so its restarted rowids go out under a fresh namespace
  instead of landing on keys the Worker already holds and being discarded as
  duplicates;
- retries stay idempotent, in `events` and in the rollups the card renders from.

The `source_id` is random and carries no hostname, username, MAC address or
path. It is never rendered on the card. Existing deployments upgrade with
[`worker/migrations/0001_event_source_id.sql`](../worker/migrations/0001_event_source_id.sql);
rows and hooks that predate it keep their previous behaviour under a `legacy`
namespace, and nothing is deleted or renumbered.

**The namespace belongs to the event, not to the installation.** Each local row
records the namespace it was queued under, and a batch may mix them. That is
what makes upgrading safe: a hook that synced an event before it had an id — and
never got the response back — re-sends that event as `legacy`, matching the row
already in D1, while events captured after the upgrade go out under the new id
in the same request. Without that, upgrading would have counted the whole
un-acknowledged backlog twice.

If an installation id cannot be created or read, the hook **sends nothing** and
keeps the events for a later attempt, logging once locally. It deliberately does
not fall back to `legacy`: that would look like success while quietly merging
this machine's rowids with every other unidentified installation's. Capture is
never blocked — events are still recorded, they simply wait.

Ingest enforces plausibility server-side: events with impossible line counts,
timestamps outside a sane window, or unknown types are rejected. The card's
"tracking since" line shows how long the account has actually been measured.
