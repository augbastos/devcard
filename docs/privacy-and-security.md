# Privacy and security

devcard is **content-private**: code, file names, paths and project names stay on
your machine. Collected activity stays local until you explicitly authorize
each publication category. A card and its machine JSON may reveal only the
categories you grant; hiding a card section is not a privacy control.

## Consent, review and removal

All six categories in `config.json`'s `consent` object default to `false`:

| Category | Published information when granted |
|---|---|
| `languages` | Language names and percentages; absolute language counts require `totals` too |
| `activity` | Lines per day, heatmap, streak and last update time |
| `totals` | Lines, bytes, event counts/types and the first recorded timestamp |
| `repo_count` | Number of public repositories owned on GitHub |
| `agents` | Per-agent totals and estimated active minutes, including per-day agent buckets |
| `usage` | Daily tokens and API-equivalent cost estimates by agent/model family; no log identifiers |

`consent.repo_count_private: true` separately opts into including private
repositories, and has no effect without `repo_count`. Only a literal JSON `true`
grants consent; missing, malformed or unknown values do not. `format` and the
random machine file name are publication metadata. Your chosen GitHub identity,
avatar, manually configured badges and pins remain card configuration.

`devcard init` describes each category and asks yes/no, default No. `--yes`
never grants consent; use `--consent languages,activity` to explicitly authorize
categories without prompts. `devcard privacy` displays the current allowlist
and locally recorded publication status. `privacy --grant <category>` and
`privacy --revoke <category>` save the choice and force a remote update. Denied
fields are omitted from JSON, and missing sections are omitted from the card.
`card.show_agents`, `card.show_usage` and `card.show_models` are display toggles:
even when false, authorized agent/usage data is readable in machine JSON.
Each line renders only when its data category is consented and its display
toggle is on.

```bash
devcard init --yes --user <you> --repo <you>/<you> --consent languages,activity
devcard privacy
devcard privacy --grant totals
devcard privacy --revoke activity
devcard unpublish
devcard serve
```

Old configs without consent publish **nothing new**. Hooks keep capturing and
write a one-line local notice to `errors.log` at most once a day; they never
fail the tool or commit. Review choices with `privacy` or `init`. This migration
does not automatically remove files that were already published.

A revoke applies the same allowlist to every machine file carried into the
new branch commit. Unknown/invalid machine files are removed rather than
republished. Revoking the last category uses `unpublish`: it disables this
machine's publication and deletes the whole `devcard-data` branch only after
the existing ownership marker, layout, root history and default-branch checks
pass. Foreign or default branches are refused. Failed remote cleanup leaves
the denial saved locally and reports that cleanup needs a retry. Other
machines have independent local settings; revoke or stop them as well to
prevent later republication.

**GitHub may keep old raw files cached or accessible by commit hash for a while
after unpublish or revocation.** These operations do not guarantee immediate
erasure, and cannot erase downloaded copies.

The read-only dashboard (`devcard serve`, bound to `127.0.0.1`) continues to
show all local data. It does not publish anything and needs no consent grants.

## The serverless card: what is published

`devcard publish` pushes generated files to the `devcard-data` branch of the
repository you chose — a **public** repository, so everything below is readable
by anyone. Each publish replaces the branch with a new single commit; the
replaced commits are no longer on any branch, but GitHub may keep serving them
by hash for a while, so treat anything published as published.

`machines/<id>.json`, one per machine, can contain these consented fields:

| Field | Example | Notes |
|---|---|---|
| `languages` | `{"Python": 61234}` | Lines added per language, all time |
| `language_percentages` | `{"Python": 75.0}` | Used instead of absolute counts when only languages are granted |
| `event_types` | `{"edit": 812, "commit": 95}` | Count per event type, all time |
| `days` | `{"2025-10-09": 412}` | Lines added per day, the last 126 days, in that machine's timezone |
| `lines`, `bytes`, `events` | `61234`, `4182230`, `1043` | Totals |
| `first_ts` | `1741000000` | Time of the machine's first recorded event |
| `repo_count` | `37` | One integer, as below |
| `repo_count_private` | `false` | Whether this count includes private repositories |
| `updated_at` | `1760000000` | When that machine's numbers last changed |
| `format` | `1` | File format version |
| `agents` | Per-agent counts, lines, bytes and estimated active minutes | Exact activity export: `claude-code`, `codex`, `git`, `unknown`; counts include events, commits and code edits. |
| `active_minutes` | `{"2025-10-09": {"claude-code": 12}}` | Estimated minutes per day/agent, without session identifiers or raw timestamps. |
| `usage` | Array of daily agent/model-family buckets | Exact [usage export allowlist](usage-and-cost.md#what-stays-on-the-machine), including token categories and nullable API-equivalent USD estimates. |

The file name is the machine's random `source_id` (16 random bytes) — never a
hostname, username or path. The JSON is built from SQL that names its columns
and never selects `project_key`, and a test checks the pushed bytes for the
project path, the hostname and the username.

`card.svg` and `card-dark.svg` show what the Worker's card showed (below), with
the date of the last change ("updated 2025-10-09") instead of "5min ago".
`agents` and `active_minutes` are published only with `consent.agents`; `usage`
requires `consent.usage`. Both default to false. The optional card lines also
require `card.show_agents` or `card.show_usage` (both default off); turning a
line off does not remove authorized machine JSON.
`"usage": false` skips new scans but retains previously collected aggregates.
`README.md` is fixed text.

`card.show_models: true` adds a token-share bar for model families on full/wide
cards and their optional README hover bodies. It requires `usage` consent and
positive tokens, and includes input, output, cache read and cache write.
Families below 1% and unknown models fold into Other; exact model names are
never rendered. The display toggle defaults off and does not authorize usage
publication.

Optional `stat_badges` and `milestone_badges` (both default false) publish only
the following files under `badges/`, each as `<name>.svg` and `<name>-dark.svg`:

| Names | Required category |
|---|---|
| `lines`, `milestone-lines` | `totals` |
| `streak`, `milestone-streak` | `activity` |
| `language`, `polyglot` | `languages` |
| `tokens` | `usage` |
| `multi-agent` | `agents` |

These locally generated SVGs contain only the `devcard` label and a derived
stat or milestone, without usernames, project names or paths. They introduce
no network calls or new data categories. Revoking a category or disabling
its badge switch removes its files on the next successful publish. Cached
or downloaded copies may remain. Streak milestones use the longest positive
run within the published 126-day window, rather than a lifetime record.
See [badge values and thresholds](badges.md).

Optional `readme_hover: true` also publishes `lang/<n>.svg` and
`lang/<n>-dark.svg` plus themed end caps. These use the card's existing language
data and colours, including the Other bucket; `languages` consent is required.
No additional activity category is exported. The setting defaults to false;
`devcard init` asks separately, and `devcard readme --enable/--disable` toggles it.

With hover enabled and both devcard markers present, the publisher can also
update `README.md` on the repository's default branch with language names,
shares and public image URLs. It uses the same fixed devcard commit identity,
makes a normal commit only if the block changed, and waits more than 24 hours
between successful README updates on this machine for this target. That branch
keeps ordinary history, so old README percentages remain in previous commits.
Disabling hover or revoking languages stops further README updates and removes
hover files from the next generated data tree; it does not erase an existing
README block, its history or cached images. Remove the block yourself if needed.

What this publishes **beyond** the Worker's card: the per-machine split of those
numbers, so how many machines you code on and how much on each, and lines per
day as raw numbers rather than heatmap shades. Commits are authored as
`devcard <devcard@devcard.invalid>`, not with your git identity.

| Data | Local SQLite | Published to your repository |
|---|---|---|
| The aggregate fields above | computed locally | Only granted categories |
| Individual events, timestamps of single edits | ✅ | ❌ (per-day totals only) |
| Project names, working directories | ✅ | ❌ |
| File names, code content | ❌ never stored | ❌ |
| Hostname, username, MAC address | ❌ never stored | ❌ |

There is no token and no server: nothing accepts writes except your repository,
through your own git credentials. Over HTTPS, devcard passes `gh auth
git-credential` to git for each command instead of changing your git config.
The other network calls are `gh api user` for the repository count, and one
fetch of `https://github.com/<you>.png` a day for the avatar (`"avatar": false`
in `config.json` turns that off).

Files read back from the branch are treated as untrusted: anything not in the
expected format and shape is skipped, language names longer than 32 characters
are dropped, and every string is XML-escaped when rendered.

## The legacy Worker: what leaves your machine

The legacy wire sends several categories together. Updated hooks hold events
locally unless `languages`, `activity`, `totals` and `repo_count` are all
explicitly granted. There is no partial legacy sync. The public repository
count must be available; private repositories require their separate opt-in.
The unchanged Worker may still serve data uploaded earlier; `unpublish` only
removes the serverless Git branch, not historical Worker/D1 data. Retire that
endpoint separately if it was previously configured.

Each synced event is one row of exactly these fields:

| Field | Example | Notes |
|---|---|---|
| `ts` | `1757930000` | Unix time the event was captured |
| `language` | `Python` | From the file extension; `null` for a commit |
| `lines_added`, `lines_removed` | `12`, `3` | |
| `bytes_added` | `418` | Size of the added text, not the text |
| `event_type` | `edit` | One of `edit`, `write`, `diff`, `commit` |
| `id` | `5821` | The local SQLite row id, for de-duplication |
| `source_id` | `9f2c…` | Random per installation (16 bytes of `secrets.token_hex`) |

A batch adds two things: the same `source_id`, and `repo_count`, a single
integer. The token travels in the `X-Devcard-Token` header, never in the URL or
the body.

| Data | Local SQLite | Sent to your Worker |
|---|---|---|
| The fields above | ✅ | ✅ |
| Repository **count** | computed locally, cached in `github-repos.json` | ✅ (one integer) |
| Project names, working directories | ✅ | ❌ no column exists |
| File names, code content | ❌ never stored | ❌ |
| Hostname, username, MAC address | ❌ never stored | ❌ |

The sync payload is built from a SQL projection that cannot select the project
column, and the D1 schema has nowhere to put one. The test suite asserts this on
the serialized request bytes, not on a comment.

Local data lives in `~/.claude/devcard/`. On macOS/Linux the installer restricts
that directory to your account, because `events.db` holds the working
directories that are never sent.

Cloudflare hosts the Worker, so it sees what any HTTPS host sees — including the
IP address a sync comes from. The Worker does not read or store it.

## What the card shows

With all corresponding categories authorized, a reader can see: total lines and bytes written, the
language mix, commit, edit and event counts, the repository count, the date
tracking started, a 16-week heatmap of lines **per day** (in your configured
timezone), your streak, how long ago the last sync was ("updated 5min ago"),
your GitHub avatar, and any badges and pinned repositories you add yourself.
That is a public record of which days you coded, and of whether you are coding
right now. It shows no files, no per-event timeline, and no projects other than
the repositories you choose to pin.

## What the repository count counts

It defaults to repositories you **own publicly on GitHub**, read locally via
`gh api user`'s `public_repos`. Private repositories are added only when both
`repo_count` and `repo_count_private` are granted. With that extra opt-in, a
visitor following `N repos →` may see a shorter list than the number.

If GitHub is unavailable, the public count is omitted: local git roots have
unknown visibility and cannot substitute for it. A combined legacy cache is
never reused as a public count. With private-count consent, the existing
distinct local-root fallback remains available. Legacy machine counts of
unknown visibility are omitted unless private counting is authorized. No
GitHub token is published or sent to the Worker.

## Where the token lives

The ingest token is a Worker secret on the Cloudflare side. The hook needs a copy,
and takes it from, in order:

1. `DEVCARD_INGEST_TOKEN` in the environment;
2. `~/.claude/devcard/token`, which the installer writes.

The installer creates that file **owner-only**: mode `0600` from the moment it
exists on macOS/Linux, and on Windows with inherited permissions removed and
full control granted to your account alone (the platform's `icacls`). It is the
only local copy; the installer used to write a second one into
`worker/.dev.vars`, and no longer does. Re-running the installer rotates the
token — the Worker secret first, the local copy only after that succeeded.

**Why not the OS keychain.** The obvious upgrade is Python's
[`keyring`](https://pypi.org/project/keyring/) (Windows Credential Manager,
macOS Keychain, Secret Service). It was evaluated and not adopted:

- the hook is standard library only and the syncer runs with `python -S`, which
  keeps `site-packages` — where `keyring` would live — off the path. Adopting it
  means a dependency install for every user and a slower hook process;
- on headless Linux, CI and WSL there is often no Secret Service at all, so the
  file would still be needed as a fallback — two storage paths to secure instead
  of one;
- what the keychain adds over an owner-only file is protection from other
  processes running as *you* — and those can already read everything else devcard
  keeps locally.

What remains is accepted and stated: malware running under your account can read
the token, and with it post events to your card. It cannot read anything back —
ingest is write-only — and rotating the token (re-run the installer) cuts it off.

## Security model

The card is built to be boring to attack.

- **devcard adds no inbound surface on your machine.** The hook opens no ports.
  Its only network traffic is HTTPS to *your* Worker, plus the local `gh` CLI's
  own call to GitHub for the repository count. There is no default endpoint: an
  unconfigured hook sends nothing.
- **Ingest is locked down and fails closed.** `POST /ingest` answers `503` until
  the secret exists, and `401` to a missing or wrong token, compared in constant
  time. It enforces strict validation (types, ranges, an event-type allowlist, a
  plausible timestamp window), caps a batch at 100 events and the body at 256 KB
  — counted while reading, so a false `Content-Length` does not get around it —
  and skips malformed events instead of storing them.
- **Ingest is idempotent.** Events are keyed on `(source_id, client_event_id)`,
  and only rows that were actually inserted reach the rollups, so a retried
  batch is never counted twice.
- **The public endpoint is read-only aggregate data.** `GET /svg` runs fixed,
  parameterized SQL over rollup tables. The `user` parameter is only ever
  *compared* against your configured username — never used in a query or a fetch.
- **Rendering is injection-safe.** Every dynamic string (badge labels, repo names,
  notes, tooltips) is XML-escaped. The SVG contains no script, and its response
  carries `Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline';
  img-src data:` and `X-Content-Type-Options: nosniff`, so a card opened directly
  as a document could not run or load anything even if escaping ever failed.
- **Query parameters cannot reach an inherited property.** `?theme=`, `?lang=`
  and `?layout=` are resolved with own-property lookups, so `?theme=constructor`
  falls back to the default instead of resolving `Object.prototype.constructor`.
- **Deployment config is not in git.** The database id, username and timezone
  live in the gitignored `worker/wrangler.jsonc`; the repository tracks a
  template.

## Supply chain

- The Worker's toolchain is installed with `npm ci` from a lockfile, with
  dependency install scripts disabled (`worker/.npmrc`). Nothing from npm ships
  to production except what Wrangler bundles from `worker/src`, which has no
  runtime dependencies.
- The Python side has no third-party dependencies, except `tzdata` on Windows
  (an IANA time-zone database, which Windows does not ship).
- Every GitHub Action is pinned to a commit SHA, and the Gitleaks image to a
  digest. Dependabot proposes updates to npm packages and Actions after a
  seven-day cooldown; security updates are not delayed.
- Pull requests run dependency review, Gitleaks over the full history, and
  CodeQL. GitHub secret scanning and push protection are enabled on the
  repository.

## Reporting a vulnerability

Use GitHub's private vulnerability reporting: the **Security** tab of this
repository → *Report a vulnerability*. Please do not open a public issue for it.
