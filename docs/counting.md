# What the numbers mean

Two capture modes, counting different things on purpose.

**`git` mode** reads `git diff --numstat` per commit, so a line is a real net
change. Commits count invocations that produce a commit; `--amend` is excluded,
because it rewrites one already counted.

**`claude` mode** counts written output — an edit counts the region it replaced,
a write counts the file. That is why the card says *lines written* rather than
*lines of code*: it measures what a session produced, not the size of a
codebase.

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

## Event identity, and using two machines

Each event carries the local SQLite rowid that produced it, and ingest ignores a
row it has already stored — that is what makes a retried batch after a lost
response count once instead of twice.

A rowid alone is not a global identity, though: every install's sequence starts
at 1. So each installation also generates a random, opaque `source_id` (16 bytes
of `secrets.token_hex`, cached in `~/.claude/devcard/source-id`), and identity is
the pair. That means:

- **two machines can share one backend** — machine B's event 1 is no longer
  mistaken for machine A's and silently dropped;
- **deleting `~/.claude/devcard/events.db` is safe** — the restarted rowid
  sequence continues in the same namespace instead of colliding with history;
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
