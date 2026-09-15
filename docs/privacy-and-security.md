# Privacy and security

devcard is **content-private**: code, file names, paths and project names stay on
your machine. It is not *activity-private* — publishing your activity is what a
stats card is for — so this page is precise about which activity leaves, and
what a visitor can read from the card.

## What leaves your machine

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
| Repository **count** | ✅ | ✅ (one integer) |
| Project names, working directories | ✅ | ❌ no column exists |
| File names, code content | ❌ never stored | ❌ |
| Hostname, username, MAC address | ❌ never read | ❌ |

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
language mix, commit and edit counts, the repository count, the date tracking
started, a 16-week heatmap of lines **per day** (in your configured timezone),
your streak, and how long ago the last sync was ("updated 5min ago"). That is a
public record of which days you coded, and of whether you are coding right now.
It shows no projects, no files and no per-event timeline.

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
- The Python side has no third-party dependencies.
- Every GitHub Action is pinned to a commit SHA, and the Gitleaks image to a
  digest. Dependabot proposes updates to npm packages and Actions after a
  seven-day cooldown; security updates are not delayed.
- Pull requests run dependency review, Gitleaks over the full history, and
  CodeQL. GitHub secret scanning and push protection are enabled on the
  repository.

## Reporting a vulnerability

Use GitHub's private vulnerability reporting: the **Security** tab of this
repository → *Report a vulnerability*. Please do not open a public issue for it.
