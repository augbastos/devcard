# Privacy and security

## What leaves your machine

| Data | Local SQLite | Public D1/card |
|---|---|---|
| Language, lines added/removed | ✅ | ✅ |
| Event type, timestamp | ✅ | ✅ |
| Repo **count** (a number) | ✅ | ✅ |
| Random installation id (`source_id`) | ✅ | ✅ (stored, never rendered) |
| Project names / paths | ✅ (never leaves) | ❌ no column exists |
| File names, code content | ❌ never stored | ❌ |
| Hostname, username, MAC address | ❌ never read | ❌ |

The sync payload is built from a SQL projection that physically excludes project
identifiers, and the public schema has nowhere to put them. Ingest is
token-gated and idempotent. The whole request body is three keys — `events`,
`repo_count`, `source_id` — and the test suite asserts that on the serialized
bytes, not on a comment.

## What the repo count actually counts

It is the number of repositories you **own on GitHub** — public plus private —
read locally through the `gh` CLI (already authenticated on your machine) and
shipped as a single integer. No GitHub token ever goes near the Worker, and the
number matches what the card's `N repos →` link resolves to.

If `gh` isn't installed or the call fails, the card falls back to counting the
distinct **git repository roots** you've worked in, resolved from the working
directories the hook recorded. Those directories stay local; only the total is
published.

The raw count of working directories is deliberately never published. A cwd is
not a repo: agent scratchpads, `node_modules`, and eleven subfolders of one
project would each register as "a repo" and inflate the number several-fold.

## Security model

The card is designed so it can't be turned against its owner.

- **No inbound surface on your machine.** The hook opens no ports and listens to
  nothing — it only makes outbound HTTPS calls to *your* Worker. There is
  nothing on your computer for an attacker to connect to.
- **Ingest is locked down.** `POST /ingest` requires a secret token, enforces
  strict schema validation (types, ranges, event-type whitelist), caps batch
  size (100 events) and body size (256 KB), and skips anything malformed instead
  of erroring.
- **The public endpoint is read-only aggregate data.** `GET /svg` runs fixed,
  parameterized SQL over anonymous aggregates. The `user` parameter is only ever
  *compared* against your configured username — never used in a query or a
  fetch.
- **Rendering is injection-safe.** Every dynamic string (badge labels, repo
  names, notes) is XML-escaped before entering the SVG; the SVG contains no
  scripts.
- **Query parameters cannot reach an inherited property.** `?theme=`, `?lang=`
  and `?layout=` are resolved with own-property lookups, so `?theme=constructor`
  falls back to the default instead of resolving `Object.prototype.constructor`
  (which used to 500 the card).
- **Secrets never touch git.** The token lives in Wrangler's secret store + your
  env; `.dev.vars` is gitignored, and on macOS/Linux the local token file is
  written `0600`.
