# devcard — CLAUDE.md

Live embeddable SVG dev-stats card driven by real Claude Code / git activity.
Cloudflare Worker + D1 render the public card; a local Python hook captures
events. Public repo, **MIT** (github.com/augbastos/devcard). Live at
`card.devcard.workers.dev/svg?user=augbastos`.

## Read first
- `README.md` — architecture, privacy/security model, capture-mode table
- `worker/src/index.ts` — routing, ingest validation/caps, i18n strings
- `worker/schema.sql` — public D1 schema (proof: no project/path column exists)
- `hook/devcard_lib.py` — local SQLite schema, token loading, sync

## Verified commands
```powershell
cd worker; npm run dev                 # wrangler dev (add --remote for real D1)
cd worker; npx tsc --noEmit            # typecheck (must stay clean)
cd worker; npm run deploy              # wrangler deploy → card.devcard.workers.dev
C:/Python314/python.exe hook/test_devcard_lib.py    # 16 tests, must pass
C:/Python314/python.exe setup.py       # full wizard (new deployments)
```
No CI exists — run tests + tsc manually before any push.

## Invariants (the product's promise — never violate)
- **Project names/file paths never reach D1 or the card.** The sync payload is a
  SQL projection that excludes `project_key`; the D1 schema has no column for it.
  Any new query/field must preserve this.
- **INGEST_TOKEN is never printed, logged, or committed.** It lives in
  `worker/.dev.vars` (gitignored) and `~/.claude/devcard/token`. Read it into a
  shell variable; a leak already forced one rotation.
- **Capture modes are exclusive per machine** (`~/.claude/devcard/mode` = `claude`
  or `git`) — both at once double-counts lines. This machine runs `claude`.
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
  purpose (deployment config, not secrets).
- Card is served via `<img>`: links inside SVG don't click there (browser
  limitation, same as all stats cards).
- Levels/XP exist in data but are deliberately NOT rendered (anti-inflation
  tuning pending) — don't "helpfully" re-add them.

## State (2026-07-06 — update when it changes)
v2 live: heatmap (16w, timezone-aware), real streak + flame, staleness line,
6 themes (?theme= default/dark/light/gentle/cyberpunk/terminal), 4 layouts
(?layout= full/banner/half/vertical). Worker split into modules (queries/themes/
render/render-layouts/svg-utils).
