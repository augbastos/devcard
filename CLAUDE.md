# devcard — notes for coding agents

A live, embeddable SVG card built from real coding activity. A local Python hook
captures events into SQLite; a background syncer sends anonymized rows to a
Cloudflare Worker; the Worker stores them in D1, keeps rollup tables, and renders
the card. Public repository, MIT.

```
Claude Code PostToolUse hook ─┐
                              ├─> local SQLite (offline-first) ─> syncer ─> POST /ingest ─> Worker ─> D1 ─> rollups ─> GET /svg
git post-commit hook ─────────┘
```

This file holds what stays true. What changed and when belongs in `CHANGELOG.md`,
commits and pull requests — not here.

## Where things are

| Path | What |
|---|---|
| `hook/devcard_lib.py` | Local schema, event parsing, identity (`source_id`), sync. The core of the client. |
| `hook/devcard_capture.py` | Claude Code hook entrypoint. Hot path: parse, insert, maybe spawn the syncer. |
| `hook/devcard_sync.py` | Detached syncer: drains, then drains once more when the throttle window closes. |
| `hook/devcard_git_hook.py`, `hook/install_git_hook.py` | git mode: per-commit capture, and its installer. |
| `install.py` | End-to-end installer (Cloudflare provisioning, config render, token, hook). |
| `worker/src/index.ts` | Routing, ingest validation and caps, rollup maintenance, nightly rebuild. |
| `worker/src/variants.ts` | Request → (lang, theme, layout, part) resolution and the cache key. |
| `worker/src/queries.ts` | Every D1 read the card makes. Reads rollups only, never `events`. |
| `worker/src/render*.ts`, `themes.ts`, `svg-utils.ts`, `language-bar.ts` | Pure renderers. |
| `worker/schema.sql`, `worker/migrations/` | D1 schema for a new database; upgrades for an existing one. |
| `worker/wrangler.example.jsonc` | Tracked deployment template. `install.py` renders the gitignored `wrangler.jsonc`. |
| `docs/` | Counting rules, privacy and security, limitations, retention, setup by hand. |

## Commands

```bash
python -m unittest discover -s hook -p "test_*.py"   # hook, git integration, installer
pipx run ruff==0.16.7 check .                         # lint (rules in ruff.toml)

cd worker
npm ci                 # locked toolchain; .npmrc disables dependency install scripts
npm run typecheck      # src and test
npm test               # Vitest inside workerd, against a local D1 — no account needed
npx wrangler deploy --dry-run --config wrangler.example.jsonc --outdir /tmp/bundle
npm run dev            # needs worker/wrangler.jsonc (python install.py, or copy the template)
npm run deploy         # the maintainer's call, never an agent's side effect
```

Version floors live in exactly two places: `MIN_PYTHON` in `install.py` and
`engines.node` in `worker/package.json`. Tests fail if CI's matrix or the README
disagree with them.

## Invariants — never break these

- **No project name, path, file name or code content reaches D1 or the card.**
  The sync payload is a SQL projection without `project_key`, and D1 has no
  column that could hold one. Tests assert this on the serialized bytes. Any new
  field must keep it true.
- **`INGEST_TOKEN` is never printed, logged, committed or put in a URL or body.**
  It is a Worker secret, plus one owner-only local copy (`~/.claude/devcard/token`)
  or `DEVCARD_INGEST_TOKEN`. Read it into a variable; never echo it.
- **Ingest fails closed.** No secret configured → 503. Wrong token → 401, compared
  with `crypto.subtle.timingSafeEqual`, never `===`.
- **Event identity is `(source_id, client_event_id)`**, never the rowid alone.
  `source_id` is random (`secrets.token_hex`) — never derived from hostname,
  username, MAC or a path.
- **The namespace belongs to the event.** A local row keeps the `source_id` it was
  stamped with forever; one batch may mix `legacy` and the current id. Re-sending
  a backlog under a new id double-counts, so do not "simplify" this into a
  per-batch field.
- **No source id, or no Worker URL, means send nothing.** Never fall back to
  `legacy` or to a default endpoint. Events wait and are retried.
- **Ingest is idempotent end to end**: `INSERT OR IGNORE ... RETURNING` decides
  which events landed, and only those are folded into the rollups.
- **The card renders from rollups only.** A render must not scan `events`; the
  nightly rebuild is the only full pass.
- **`edit`/`write` and `diff` are different units.** One agent tool call vs. one
  per-commit, per-language aggregate. Never sum them into "code edits".
- **Capture modes are exclusive per machine** (`~/.claude/devcard/mode`). Both at
  once counts the same lines twice.
- **Every dynamic string in SVG or embed HTML goes through `escapeXml`.** The card
  is strict XML: HTML entities such as `&middot;` break it.
- **Query parameters are resolved with own-property lookups.** `?theme=constructor`
  must fall back, not reach `Object.prototype`.
- **The edge cache key is the resolved variant**, never the request URL.
  `Accept-Language` decides the body without being in the URL, and `Vary` does
  not separate entries on the `caches.open("default")` path.
- **Hooks never block or fail the tool or the commit.** Errors go to
  `~/.claude/devcard/errors.log`, throttled.

## Rules for tests

- **A test must never touch `~/.claude/devcard/`.** Redirect `DB_PATH`,
  `ERROR_LOG_PATH`, `SOURCE_ID_PATH`, `GITHUB_CACHE_PATH`, and set
  `WORKER_INGEST_URL`/`INGEST_TOKEN` to stand-ins. Paths are read from the module
  at call time for exactly this reason — do not turn them back into default
  arguments, which bind at import and make patching a no-op.
- git behaviour is tested against real temporary repositories, not mocks.
- The Worker suite runs against real workerd and D1. Bindings are fixed in
  `vitest.config.mts`; a local `.dev.vars` must not change what a test sees.
- Outbound requests are answered by `outboundService` in `vitest.config.mts`;
  anything unmocked returns 599 rather than reaching the network.

## Gotchas

- Hooks fail silently by design — debugging starts at `~/.claude/devcard/errors.log`.
- Cloudflare's edge rejects urllib's default User-Agent; the hook sends
  `devcard-hook/1.0`.
- Do not export non-handler values from `worker/src/index.ts`. workerd rejects
  them at startup ("Incorrect type for map entry") even though typecheck, tests
  and `--dry-run` pass. Shared constants live in `variants.ts`.
- `worker/tsconfig.json` has no DOM lib on purpose: lib.dom's `SubtleCrypto` lacks
  the runtime's `timingSafeEqual`.
- `git rev-parse --git-path hooks/post-commit` answers relative to the directory
  it ran in. Join it onto that directory, not the process cwd.
- `repo_count` is the GitHub owned-repository total read through the local `gh`
  CLI (public + private); the no-`gh` fallback is distinct git roots. The raw
  count of recorded working directories is never published.
- An SVG inside `<img>` receives no pointer events, and GitHub strips every
  element that could carry them — hence the split `?part=` card and
  `docs/hover-in-a-readme.md`.
- A schema change ships as a migration in `worker/migrations/` plus the matching
  change in `schema.sql`; `test/migration.test.ts` asserts the two agree. Apply
  the migration together with the Worker deploy that needs it.

## Repository rules

- `main` is protected: pull request, squash merge, required checks (`ci-ok`,
  `secrets`, `dependencies`, `verify`). No direct pushes, no force pushes.
- Every pull request carries an AI-use disclosure (`scpe` check): tick the box in
  the template or add an `Assisted-by:` trailer.
- Actions are pinned by commit SHA with the version in a comment; keep it that way.
- Never commit `worker/wrangler.jsonc`, `.dev.vars*`, `.env*`, `*.db`, `.wrangler/`
  or `docs/superpowers/`.
- Prefer existing tools and platform features over custom code, and keep the
  architecture above: no framework, no extra services, no second database.
