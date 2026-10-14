# The serverless card

`devcard publish` renders the card on your machine and commits it to a branch
of a public repository you own. There is no server, no database in the cloud,
no token and no Node. This page is how it works and where everything lives.

```
your machine                                            your repository, branch devcard-data
────────────                                            ────────────────────────────────────
hook ─> ~/.claude/devcard/events.db                      README.md
          │                                              card.svg        ◄── <picture> in your README
          └─ aggregate ─> machines/<id>.json ──┐         card-dark.svg   ◄── (dark GitHub theme)
                                               ├─ push ─> machines/<id-of-this-machine>.json
          other machines' files (fetched) ─────┘         machines/<id-of-another-machine>.json
                     merge ─ render ─┘
```

## When it publishes

- **Automatically, while you work.** The capture hooks already start a
  detached background process after an edit (claude mode) or a commit (git
  mode). On a machine set up with `devcard init`, that process runs `publish`,
  which does nothing unless 15 minutes have passed since its last check.
- **Once more when the window closes.** A publish skipped by that rule leaves
  one background process waiting (`devcard publish --when-due`, at most one per
  machine) that publishes when the 15 minutes are up — so the last edits of a
  session go out within 15 minutes rather than at the start of the next one.
- **By hand**, with `devcard publish` (same 15-minute rule) or
  `devcard publish --force`.
- **Not when nothing changed.** If the rendered files and this machine's numbers
  are identical to what the branch holds, nothing is pushed. A machine's
  `updated_at` only moves when its numbers do, so an idle machine does not push.

### How fresh the card is

Honestly: **up to about 20 minutes: 15 minutes between publishes plus 5 minutes
of raw file caching**. The legacy Worker
card was live within about half a minute; this one is not.

1. Up to 15 minutes between publishes (the debounce above). Nothing publishes
   while you are not coding: the trigger is the hook, not a timer.
2. `raw.githubusercontent.com` serves the files with `Cache-Control:
   max-age=300`, so up to 5 more minutes there.

SVGs served by `raw.githubusercontent.com` are not proxied through GitHub's
image proxy (camo), so there is no additional proxy cache in this path.

The card states its own date ("updated 2025-10-09") rather than "5min ago",
because a static file cannot keep a relative time true.

## Where things live

On each machine, in `~/.claude/devcard/` (next to the hook's database):

| File | What |
|---|---|
| `config.json` | Your GitHub username, the target `owner/name`, layout, theme, language, optional timezone, badges, pinned repos. Not secret; never published. Its presence is what makes the hooks publish. |
| `source-id` | This machine's random id (16 random bytes). Names its file on the branch. |
| `events.db` | The hook's local database. Holds working directories; never published. |
| `publish/<owner>__<name>/` | A private bare git repository publishing goes through. Safe to delete. |
| `publish-state.json` | When this machine last checked and last pushed. Delete it to lift the debounce once. |
| `publish.lock`, `publish-pending` | A publish in progress, and the one waiting for the window to close. Removed when they finish; ignored after 10 and 20 minutes. |
| `avatar.json` | Your GitHub avatar as a data URI, cached for a day. |

On the branch `devcard-data` of the repository you chose:

| Path | What |
|---|---|
| `card.svg`, `card-dark.svg` | The card, merged across every machine, for light and dark GitHub themes |
| `machines/<id>.json` | One file per machine, written only by that machine |
| `README.md` | A note that the branch is generated |
| `.devcard` | Ownership marker with format version 1 |

## Several machines

Each machine writes **only its own** `machines/<id>.json`, and renders the card
from all of them. Counts add up: lines, languages, events, lines per day. The
repository count does not — every machine reads the same GitHub account, so the
largest one is used. `first_ts` is the earliest, `updated_at` the latest.

Set every machine up with `devcard init` and the same repository. Machines that
publish at the same moment cannot overwrite each other: each push is a
`--force-with-lease` against the commit that machine read, and a lost race is
redone on top of the winner's commit (up to three times).

A machine whose `events.db` is deleted gets a new id; its old file stays on the
branch, so the work it recorded keeps counting. To drop a machine's numbers,
remove its file while retaining a single root commit and the `.devcard` marker.
An ordinary edit that adds a parent commit is refused on the next publish.
The file will not come back unless that machine publishes again.

Days are computed in each machine's own timezone (or `timezone` in its
`config.json`). Two machines in different zones may disagree about which day a
late-night edit belongs to.

## The branch

The branch is an **orphan** — it shares no history with your other branches —
and every publish replaces it with a **single root commit**. That keeps the
repository from growing a commit per publish, and it means the branch's history
is not a record of anything. Commits are authored as
`devcard <devcard@devcard.invalid>`, never with your git identity, so no
`user@hostname` default can end up in a public repository.

An existing branch is accepted only with the `.devcard` format marker, the
generated card layout and a single root commit. A branch containing unrelated
files or history is refused, as is the repository's default branch. An older
unmarked branch is refused too; it is never taken over automatically.

Because each publish is a force-push, a branch protection rule or ruleset that
blocks force-pushes on `devcard-data` will make publishing fail. Leave that one
branch unprotected (or pick a repository where it is).

## Authentication

Over HTTPS, publishing uses `gh`'s login: the credential helper `gh auth
git-credential` is passed to git for each command, which is what `gh auth
setup-git` would write into your global config — without touching it. The
publisher ignores global and system git configuration, disables hooks and
commit signing, and passes only this credential helper explicitly. Run
`gh auth login` once. With `--remote <url>` (or `remote` in `config.json`) you
can push over SSH or to any URL your own git credentials reach instead.

devcard never creates repositories, branches other than `devcard-data`, gists or
releases.

## Commands

```bash
devcard init                 # checks, capture hook, target repo, first publish, embed snippet
devcard publish [--force]    # publish now (debounced unless --force)
devcard render --out DIR     # this machine's card only, written locally; publishes nothing
devcard status               # configuration, machine id, last push, embed snippet
```

## Migrating from the Worker

Run `devcard init` on each machine. A machine that also has a Worker configured
(`~/.claude/devcard/worker-url`) keeps syncing there as before, so both cards
stay current while you switch your README to the `<picture>` embed. When the
Worker card is no longer embedded anywhere, delete `worker-url` and `token` from
each machine.

History before `devcard init` is included: the aggregate is built from the whole
local `events.db`, not only from events captured after setup. What the Worker
holds and the local databases do not (for example a machine you no longer have)
is not carried over.
