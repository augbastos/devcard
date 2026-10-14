# devcard — notes for coding agents

An embeddable SVG card built from real coding activity. A local Python hook
captures events into SQLite. The `devcard` package folds them into per-machine
aggregates, renders the card on the machine, and commits it to the orphan branch
`devcard-data` of a public repository the user owns. Public repository, MIT.

```
Claude Code PostToolUse hook ─┐                                   ┌─ machines/<source_id>.json (this machine only)
                              ├─> local SQLite ─> devcard publish ┤  + every other machine's file, merged
git post-commit hook ─────────┘   (offline-first)  (≤ 1 per 15 min) └─> card.svg, card-dark.svg ─> one commit on devcard-data
```

The **legacy** path — syncer ─> `POST /ingest` ─> Cloudflare Worker ─> D1 ─>
rollups ─> `GET /svg` — still works and still serves the maintainer's card. It
stays in `worker/` until that card is migrated; do not delete it, and do not
break it. A machine with both a Worker URL and `config.json` feeds both.

This file holds what stays true. What changed and when belongs in `CHANGELOG.md`,
commits and pull requests — not here.

## Where things are

| Path | What |
|---|---|
| `hook/devcard_lib.py` | Local schema, event parsing, identity (`source_id`), sync. The core of the client. |
| `hook/devcard_capture.py` | Claude Code hook entrypoint. Hot path: parse, insert, maybe spawn the syncer. |
| `hook/devcard_sync.py` | Detached syncer: drains, then drains once more when the throttle window closes. |
| `hook/devcard_git_hook.py`, `hook/install_git_hook.py` | git mode: per-commit capture, and its installer. |
| `hook/install_claude_hook.py` | Registers the capture hook in Claude Code's settings.json. Shared by both installers. |
| `devcard/data.py` | Per-machine aggregate from the local SQLite, merge across machines, heatmap/streak. |
| `devcard/render.py`, `svg.py`, `themes.py`, `strings.py`, `jsfmt.py` | Pure Python port of the Worker's renderers. |
| `hook/devcard_activity.py` | Per-agent attribution helpers and active-time estimate from event gaps. |
| `hook/devcard_usage.py` | Tokens and API-equivalent cost from local Claude Code / Codex logs; price table in `devcard/prices.json`. |
| `devcard/serve.py`, `devcard/dashboard/` | `devcard serve`: read-only local dashboard on 127.0.0.1. |
| `devcard/publish.py` | `render`/`publish`: git plumbing in a private bare repo, debounce, lease, avatar cache. |
| `devcard/cli.py`, `config.py` | `devcard init/render/publish/status`; `~/.claude/devcard/config.json`. |
| `pyproject.toml` | `pipx install git+https://github.com/augbastos/devcard`. Ships `devcard/` plus the hook modules as top-level modules. |
| `tests/` | The package's suite; `tests/golden/` holds the reference SVGs and the events behind them. |
| `install.py` | Legacy end-to-end installer (Cloudflare provisioning, config render, token, hook). |
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
python -m unittest discover -s tests -t .             # devcard package (golden SVGs, publish, init)
pipx run ruff==0.16.7 check .                         # lint (rules in ruff.toml)
python -m devcard --help                              # the CLI from a checkout

cd worker
npm ci                 # locked toolchain; .npmrc disables dependency install scripts
npm run typecheck      # src and test
npm test               # Vitest inside workerd, against a local D1 — no account needed
npx wrangler deploy --dry-run --config wrangler.example.jsonc --outdir /tmp/bundle
npm run dev            # needs worker/wrangler.jsonc (python install.py, or copy the template)
npm run deploy         # the maintainer's call, never an agent's side effect
```

Version floors live in two places: `MIN_PYTHON` in `install.py` and
`engines.node` in `worker/package.json`. Tests fail if CI's matrix, the README,
`ruff.toml`'s target version, `devcard/cli.py` or `pyproject.toml` disagree.

## Invariants — never break these

- **No project name, path, file name or code content reaches D1, the card or the
  `devcard-data` branch.** The sync payload and a machine file are both SQL
  projections without `project_key`, and D1 has no column that could hold one.
  Tests assert this on the serialized bytes. Any new field must keep it true.
- **The Python renderer matches the golden SVGs.** `tests/golden/` is rendered by
  the Worker (`worker/test/golden.test.ts`) and checked by `tests/test_golden.py`.
  Change both renderers together, or regenerate on purpose — never edit a golden
  file by hand.
- **A machine writes only its own `machines/<source_id>.json`.** Others' files are
  carried over byte for byte; the push is a `--force-with-lease` against the
  commit that was read. Counts are summed across machines; `repo_count` is the
  maximum, never the sum.
- **Publishing never uses the user's git identity or global config**, and never
  creates repositories, gists or any branch but `devcard-data`.
- **`INGEST_TOKEN` is never printed, logged, committed or put in a URL or body.**
  It is a Worker secret, plus one owner-only local copy (`~/.claude/devcard/token`)
  or `DEVCARD_INGEST_TOKEN`. Read it into a variable; never echo it.
- **Ingest fails closed.** No secret configured → 503. Wrong token → 401, compared
  with `crypto.subtle.timingSafeEqual`, never `===`.
- **Event identity is `(source_id, client_event_id)`**, never the rowid alone.
  `source_id` is random (`secrets.token_hex`) — never derived from hostname,
  username, MAC or a path. It namespaces the rowids of one `events.db`, so a
  newly created database retires it; keeping it would put restarted rowids on
  keys D1 already holds, and ingest would discard them as duplicates.
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
  `~/.claude/devcard/errors.log`; missing-config failures are throttled to one
  line an hour.

## Rules for tests

- **A test must never touch `~/.claude/devcard/`.** Redirect `DB_PATH`,
  `ERROR_LOG_PATH`, `SOURCE_ID_PATH`, `GITHUB_CACHE_PATH`, `CONFIG_PATH` (and for
  the package, `devcard.config.HOME` — `tests/helpers.Home` does all of it), and set
  `WORKER_INGEST_URL`/`INGEST_TOKEN` to stand-ins. Paths are read from the module
  at call time for exactly this reason — do not turn them back into default
  arguments, which bind at import and make patching a no-op.
- git behaviour is tested against real temporary repositories, not mocks.
- The Worker suite runs against real workerd and D1. Bindings are fixed in
  `vitest.config.mts`; a local `.dev.vars` must not change what a test sees.
- Outbound requests are answered by `outboundService` in `vitest.config.mts`;
  anything unmocked returns 599 rather than reaching the network.
- Publishing is tested against temporary local bare repositories only. Package
  tests stub the GitHub API repo count and the avatar download; a subprocess test
  strips `GH_*`/`GITHUB_*` tokens from its environment.

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
- Opening the hook database when it does not exist yet retires `source_id`
  (`init_db`). Read the machine id only after the database is open, or the first
  publish names a file that the next publish abandons.
- git exports `GIT_DIR`, `GIT_INDEX_FILE` and friends to hooks. A publish started
  from the post-commit hook inherits them, so `publish._Repo` strips them
  (`REPO_ENV_VARS`) — otherwise its commands land in the user's project.
- The hooks run as `python -S <dir>/<hook>.py`: no site-packages, only the
  script's directory on `sys.path`. That is why pyproject installs the hook
  modules next to the `devcard` package, and why `lib.auto_publish` falls back
  to the parent directory in a checkout.
- An SVG inside `<img>` receives no pointer events, and GitHub strips every
  element that could carry them — hence the split `?part=` card and
  `docs/hover-in-a-readme.md`.
- A schema change ships as a migration in `worker/migrations/` plus the matching
  change in `schema.sql`; `test/migration.test.ts` asserts the two agree. Apply
  the migration together with the Worker deploy that needs it.

## Repository rules

- `main` is protected: pull request, squash merge, required checks (`ci-ok`,
  `secrets`, `dependencies`). No direct pushes, no force pushes.
- Every pull request carries an AI-use disclosure: tick a box in the template or add
  an `Assisted-by:` trailer.
- Actions are pinned by commit SHA with the version in a comment; keep it that way.
- Never commit `worker/wrangler.jsonc`, `.dev.vars*`, `.env*`, `*.db`, `.wrangler/`
  or `docs/superpowers/`.
- Prefer existing tools and platform features over custom code, and keep the
  architecture above: no framework, no extra services, no second database.
