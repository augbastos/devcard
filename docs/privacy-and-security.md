# Privacy and security

devcard is **content-private**: code, file names, paths and project names stay on
your machine. It is not *activity-private* — publishing your activity is what a
stats card is for — so this page is precise about which activity leaves, and
what a visitor can read from the card.

## The serverless card: what is published

`devcard publish` pushes three kinds of file to the `devcard-data` branch of the
repository you chose — a **public** repository, so everything below is readable
by anyone. Each publish replaces the branch with a new single commit; the
replaced commits are no longer on any branch, but GitHub may keep serving them
by hash for a while, so treat anything published as published.

`machines/<id>.json`, one per machine, exactly these fields:

| Field | Example | Notes |
|---|---|---|
| `languages` | `{"Python": 61234}` | Lines added per language, all time |
| `event_types` | `{"edit": 812, "commit": 95}` | Count per event type, all time |
| `days` | `{"2025-10-09": 412}` | Lines added per day, the last 126 days, in that machine's timezone |
| `bytes`, `events` | `4182230`, `1043` | Totals |
| `first_ts` | `1741000000` | Time of the machine's first recorded event |
| `repo_count` | `37` | One integer, as below |
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
`agents`, `active_minutes` and `usage` are published only when the matching opt-in
card line is on (`card.show_agents`, `card.show_usage`; both default off). With
them off, those aggregates stay in the local database and the dashboard.
`"usage": false` skips new scans but retains previously collected aggregates.
`README.md` is fixed text.

What this publishes **beyond** the Worker's card: the per-machine split of those
numbers, so how many machines you code on and how much on each, and lines per
day as raw numbers rather than heatmap shades. Commits are authored as
`devcard <devcard@devcard.invalid>`, not with your git identity.

| Data | Local SQLite | Published to your repository |
|---|---|---|
| The aggregate fields above | computed locally | ✅ |
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

Anyone who can load the card can read: total lines and bytes written, the
language mix, commit, edit and event counts, the repository count, the date
tracking started, a 16-week heatmap of lines **per day** (in your configured
timezone), your streak, how long ago the last sync was ("updated 5min ago"),
your GitHub avatar, and any badges and pinned repositories you add yourself.
That is a public record of which days you coded, and of whether you are coding
right now. It shows no files, no per-event timeline, and no projects other than
the repositories you choose to pin.

## What the repository count counts

It is the number of repositories you **own on GitHub** — public plus private —
read locally through the `gh` CLI and shipped as a single integer. No GitHub
token ever goes near the Worker. Because private repositories are included, a
visitor following the card's `N repos →` link to your profile sees a shorter
list than the number.

If `gh` isn't installed or the call fails, the count falls back to the distinct
**git repository roots** you have worked in. The raw count of working directories
is never published: agent scratchpads, `node_modules` and a project's
subfolders would each register as "a repo".

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
