# devcard — CLAUDE.md

Live embeddable SVG dev-stats card driven by real Claude Code / git activity.
Cloudflare Worker + D1 render the public card; a local Python hook captures
events. Public repo, **MIT** (github.com/augbastos/devcard). Live at
`card.devcard.workers.dev/svg?user=augbastos`.

## Read first
- `README.md` — architecture, privacy/security model, capture-mode table,
  counting rules (merge behaviour, event identity, `code edits` semantics)
- `CHANGELOG.md` — what changed and why, newest first
- `worker/src/index.ts` — routing, ingest validation/caps, i18n strings
- `worker/schema.sql` — public D1 schema (proof: no project/path column exists)
- `hook/devcard_lib.py` — local SQLite schema, token loading, sync

## Verified commands
```powershell
cd worker; npm ci                      # pinned toolchain (CI uses this too)
cd worker; npm run dev                 # wrangler dev (add --remote for real D1)
cd worker; npm run typecheck           # tsc on src AND test — must stay clean
cd worker; npm test                    # vitest in workerd + local D1
cd worker; npm run deploy              # wrangler deploy → card.devcard.workers.dev
C:/Python314/python.exe -m unittest discover -s hook -p "test_*.py"   # all hook suites
C:/Python314/python.exe setup.py       # full wizard (new deployments)
```
CI (`.github/workflows/ci.yml`) runs both suites on every PR and on `master`:
hook on Python 3.9/3.11/3.13, worker on Node 20. It needs no Cloudflare account
and no secret, so fork PRs run it in full. The `scpe` workflows are an AI-use
disclosure gate, not a test of the code.

## Invariants (the product's promise — never violate)
- **Project names/file paths never reach D1 or the card.** The sync payload is a
  SQL projection that excludes `project_key`; the D1 schema has no column for it.
  Any new query/field must preserve this.
- **INGEST_TOKEN is never printed, logged, or committed.** It lives in
  `worker/.dev.vars` (gitignored) and `~/.claude/devcard/token`. Read it into a
  shell variable; a leak already forced one rotation.
- **Capture modes are exclusive per machine** (`~/.claude/devcard/mode` = `claude`
  or `git`) — both at once double-counts lines. This machine runs `claude`.
- **`edit`/`write` and `diff` are different units and must not be summed.**
  `edit`/`write` = one agent tool call (claude mode); `diff` = one
  per-commit, per-language aggregate (git mode). The card only prints the
  "code edits" stat when there are agent edits to report.
- **Event identity is `(source_id, client_event_id)`, never the rowid alone.**
  A rowid restarts at 1 on every install and after every `events.db` deletion.
  `source_id` is random and opaque — never derive it from hostname, username,
  MAC or any path.
- **The namespace belongs to the EVENT.** Local `events.source_id` is stamped at
  insert and never changes; a batch may mix `legacy` (queued before this install
  had an id) with the current id. Re-sending an un-acknowledged backlog under a
  new id counts the same work twice — that is the whole reason the column
  exists, so never "simplify" it back to a per-batch field.
- **No source id means send NOTHING.** Never fall back to `legacy` — that
  silently merges this machine's rowids with every other unidentified install.
  Events stay unsynced and are retried; `get_unsynced_events` refuses to return
  unstamped rows so this cannot be got wrong by accident.
- **Tests must never touch `~/.claude/devcard/`.** `test_git_integration.py`
  redirects `DB_PATH`/`ERROR_LOG_PATH`/`SOURCE_ID_PATH`/`GITHUB_CACHE_PATH` in
  `setUp` and asserts the redirection took. This is not theoretical: while these
  suites were being written, a run wrote eight rows into the live `events.db`
  (caught before the syncer published them) because the paths were default
  arguments, bound at import, so patching the module constant did nothing.
- Every dynamic string interpolated into SVG goes through `escapeXml` (it's
  strict XML — HTML entities like `&middot;` break rendering in browsers).
- Never commit: `.dev.vars`, `.wrangler/`, `*.db`, `docs/superpowers/` (internal
  PT docs, deliberately kept out of the public repo).

## Gotchas
- Hooks fail silently by design (never block Claude Code) — debugging starts at
  `~/.claude/devcard/errors.log`, not stdout.
- Cloudflare edge 403s Python urllib's default User-Agent — the hook sends
  `User-Agent: devcard-hook/1.0`; don't remove it.
- `wrangler.toml` carries the real database_id + GITHUB_USERNAME + TIMEZONE on
  purpose (deployment config, not secrets). The hook's endpoint is NOT source
  config any more — it lives in `~/.claude/devcard/worker-url` (or
  `DEVCARD_WORKER_URL`); don't reintroduce the `WORKER_INGEST_URL` rewrite.
- Card is served via `<img>`: links inside SVG don't click there (browser
  limitation, same as all stats cards).
- Levels/XP exist in data but are deliberately NOT rendered (anti-inflation
  tuning pending) — don't "helpfully" re-add them.
- **`repo_count` is the GitHub owned-repo total** (public + private, read via the
  local `gh` CLI), NOT a count of `known_repos` rows. Those rows are raw cwds —
  scratchpads, `node_modules`, and eleven subfolders of one repo included — and
  publishing them straight is what made the card claim **115 repos against a
  real 40**. `local_repo_count()` (distinct git roots) is the no-`gh` fallback;
  the raw row count is never published.
- Tests must never let `log_error` hit the real `~/.claude/devcard/errors.log` —
  stub it. That file is the documented debugging surface; fake "boom" entries
  from test runs already polluted it once.
- The edge cache is keyed on the RESOLVED variant (`lang`, `theme`, `layout`),
  not on the request URL. Keying on the URL let `Accept-Language` decide the
  body without appearing in the key, and `Vary` is no help: workerd's local
  cache ignores it (a test proves this), and at the edge it keys per *verbatim*
  header value, so `en-US,en;q=0.9` and `en-GB,en;q=0.7` would be two entries of
  the identical English card.
- `git rev-parse --git-path hooks/post-commit` answers RELATIVE to the directory
  it ran in. Join it back onto that directory, never onto the process cwd.

## State (2026-09-07 — update when it changes)
v2 live: heatmap (16w, timezone-aware), real streak + flame, staleness line,
6 themes (?theme= default/dark/light/gentle/cyberpunk/terminal), 4 layouts
(?layout= full/banner/half/vertical). Worker split into modules (queries/themes/
render/render-layouts/svg-utils).

**2026-09-07 hardening pass — in the working tree, NOT committed and NOT
deployed.** Event identity (`source_id` + migration 0001), safe theme/lang
lookups, resolved-variant cache key, merge-commit counting, `git rev-parse`
hook installation, `diff` vs `edit` semantics, setup.py hardening, and a real
CI. 86 worker tests + 127 hook tests, all green locally. See `CHANGELOG.md`.

⚠️ **Deploy order matters.** The Worker and the schema go together: apply
`worker/migrations/0001_event_source_id.sql` with the deploy, or the new
`source_id` bind hits a column that does not exist. The hook may be updated
before or after — an older Worker ignores the extra `source_id` key, and a newer
Worker files a hook that omits it under `legacy`.

✅ **`master` IS deployed.** Verified 2026-09-07 with
`npx wrangler deployments list --name card`: the newest deployment is
**2026-09-02T07:16Z**, and the live response carries `s-maxage=300` +
`Vary: Accept-Language`, which only exist from `f26cb35` onward. The earlier
"still the 2026-07-05 build" warning was true on 2026-09-01 and went stale after
the 09-02 deploy — do not repeat it without re-checking.

⛔ **The cache language bug is LIVE right now.** Measured against
`card.devcard.workers.dev` on 2026-09-07, on a variant nobody had requested:
first visitor `Accept-Language: en-US` → English; the next two, `pt-BR` and
`es-ES`, both got **English**. The first visitor's language freezes into the
entry for everyone. `Vary: Accept-Language` is on the response and does NOT save
it — so the docs' Vary guarantee does not apply to this `caches.open("default")`
path in practice. This is what the resolved-variant cache key fixes.
Audit: `C:\IA\_audits\devcard-audit-2026-09-01.md`.
