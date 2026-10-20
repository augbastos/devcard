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

Publication first requires explicit category grants in `consent` (all default
No). `init --yes` does not grant them. Use `devcard privacy` to review and
`privacy --grant <category>` / `--revoke <category>` to update them. With no
grants, hooks keep capture local and `publish` refuses. Missing sections are
absent from the card, and only authorized fields enter machine JSON. Agent and
usage lines each require both category consent and their `card.show_agents` or
`card.show_usage` display toggle. A hidden line does not hide authorized JSON.
Agent consent includes daily active minutes; usage consent includes daily
agent/model-family token and cost buckets.

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
| `config.json` | Your GitHub username, the target `owner/name`, layout, theme, language, optional timezone, badges, pinned repos. Not secret; never published. Its presence and category grants enable hook publication. |
| `source-id` | This machine's random id (16 random bytes). Names its file on the branch. |
| `events.db` | The hook's local database. Holds working directories; never published. |
| `publish/<owner>__<name>/` | A private bare git repository publishing goes through. Safe to delete. |
| `publish-state.json` | When this machine last checked, last pushed the card and last attempted/updated the README for the target repository, plus a short README failure reason if needed. Delete it to reset the local timers. |
| `publish.lock`, `publish-pending` | A publish in progress, and the one waiting for the window to close. Removed when they finish; ignored after 10 and 20 minutes. |
| `avatar.json` | Your GitHub avatar as a data URI, cached for a day. |

On the branch `devcard-data` of the repository you chose:

| Path | What |
|---|---|
| `card.svg`, `card-dark.svg` | The card, merged across every machine, for light and dark GitHub themes |
| `lang/body.svg`, `lang/body-dark.svg` | Optional README body, without the language bar or bottom edge |
| `lang/<n>.svg`, `lang/<n>-dark.svg`, `lang/cap-*.svg` | Optional language-hover slices and end caps, with light/dark variants |
| `machines/<id>.json` | One file per machine; denied categories are also removed from carried files |
| `README.md` | A note that the branch is generated |
| `.devcard` | Ownership marker with format version 1 |

## README language hover

`readme_hover` defaults to `false`. `devcard init` asks whether to enable it
after the publication consent questions, default **No**. For unattended setup,
pass `--readme-hover` explicitly. You can change the setting later without
publishing anything:

```bash
devcard readme --enable
devcard readme --disable
devcard readme
```

The setting only takes effect with `consent.languages: true`; it grants no
publication consent itself. Add these markers around your existing card in
`README.md` on the publish repository's default branch:

```html
<!-- devcard:start -->
Your existing card snippet goes here.
<!-- devcard:end -->
```

On publish, devcard commits body and strip SVGs alongside the full card on `devcard-data`.
It uses the card legend's language/Other grouping, colours and slice titles.
The README block forms one visual card in a single `<p>`: a body `<picture>`
at `width="100%"`, then the left cap, per-language slices and right cap. The
body omits the language bar and closes the space it occupied, keeping the
legend, heatmap and footer. Its rounded frame extends below the viewBox, so
the bottom is flat, with no bottom border or corners. The strip supplies the
bar, surrounding space, bottom border and rounded bottom corners. Body and
strip share an 840px canvas, 28px padding, background, border and corner radius.
Every image uses `align="top"`, with no whitespace between adjacent tags;
the strip is last so paragraph line-box slack falls below the card.
Each `<picture>` has a dark source; slices carry an
`<img title="Python 41.8%">`. URLs point to `raw.githubusercontent.com` on
`devcard-data`; no Worker is involved. A browser cannot hover inside a single
SVG embedded as an image, so each tooltip needs its own image.

The split supports `full` (the default) and `wide`, including partial-consent
cards that have a language section. Other layouts, or cards without that
section, use the normal single-image embed without per-language tooltips and
do not generate hover files. The normal `card.svg` and `card-dark.svg` embeds
keep their existing layouts and language bars unchanged.

Widths use the legacy Worker's layout: narrow segments get a four-pixel target
at the nominal 840-pixel card width, paid for from larger segments. Titles keep
the true shares. Integer percentage units and end caps make the row total
exactly 100%, without spaces between images. Old body and slice files disappear from
the generated tree when the number of slices shrinks, hover is disabled or
languages consent is revoked.

The HTML titles and widths live in the README. If both markers exist and the
block changed, devcard makes one ordinary commit, `devcard: refresh language bar`,
on the existing default branch, preserving its history, other files and the
README's LF/CRLF endings. A missing README or markers causes a skip and a
one-time local log hint. Invalid UTF-8, symlink or executable README files get
a distinct hint and are left untouched. An unchanged block never creates a
commit. A failed README update never fails the card publication: its attempt
timestamp and a short reason are saved locally, and one log line reports it.
Further README attempts wait more than 24 hours, even with `publish --force`,
before fetching or pushing the default branch again. Branch protection can
reject this direct README update when it requires a pull request. A competing
edit that rejects a fast-forward push is preserved and retried the next day.

README updates are limited to one per **more than 24 hours**, recorded locally
per machine and target repository; `publish --force` does not bypass this timer.
Several machines have independent timers. Images can update every 15 minutes
while README shares and widths wait for the next eligible publish. If a publish
shrinks the slice set, old README image URLs can be unavailable until that
refresh, because stale slice files are removed on every data publish.
Disabling hover or revoking languages stops README updates; remove the marked block
manually if you also want to remove previously written labels. Existing commits
and GitHub caches can retain old labels.

`scripts/refresh_readme.py` remains an optional legacy Worker client. Its
newline-preserving marker replacement is shared with the package; serverless
publishing does not call the script or its `/embed` endpoint.

## Several machines

Each machine updates its own `machines/<id>.json`, applies its consent allowlist
to carried machine files, and renders the card from the remaining data.
Revocation removes denied categories across machines; matching valid files
otherwise stay byte-identical. Counts add up: lines, languages, events, lines per day. The
repository count does not — every machine reads the same GitHub account, so the
largest one is used. `first_ts` is the earliest, `updated_at` the latest.

The repository count defaults to public repositories. Including private ones
requires both `repo_count` and `repo_count_private`. A count with unknown
visibility is omitted unless private counting is allowed. Language-only files
contain percentages; when absolute counts are unavailable, the language mix
averages the available machines equally instead of inventing line totals.

Set every machine up with `devcard init` and the same repository. Machines that
publish at the same moment cannot overwrite each other: each push is a
`--force-with-lease` against the commit that machine read, and a lost race is
redone on top of the winner's commit (up to three times).

Consent settings remain local to each machine. Apply revocations everywhere,
or stop other machines, so a machine with older grants cannot republish data.
`devcard unpublish` disables publication on this machine and deletes only a
verified devcard-owned branch. GitHub may keep old raw files cached or
accessible by commit hash for a while afterward.

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
devcard privacy              # review or --grant/--revoke a publication category
devcard readme [--enable|--disable]  # opt-in daily README language hover
devcard unpublish            # disable publication and remove the owned data branch
```

## Migrating from the Worker

Run `devcard init` on each machine. A machine that also has a Worker configured
(`~/.claude/devcard/worker-url`) syncs there only when `languages`, `activity`,
`totals` and `repo_count` are all granted and the repository count is available.
Partial consent holds legacy events locally. Switch your README to the
`<picture>` embed when ready. When the
Worker card is no longer embedded anywhere, delete `worker-url` and `token` from
each machine.

History before `devcard init` is included: the aggregate is built from the whole
local `events.db`, not only from events captured after setup. What the Worker
holds and the local databases do not (for example a machine you no longer have)
is not carried over.
