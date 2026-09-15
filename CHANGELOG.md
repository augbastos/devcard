# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims
to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

What "public API" means for devcard, since it is not a library:

- the `GET /svg` query parameters and the shape of the card;
- the `POST /ingest` request body;
- the D1 schema;
- the local files under `~/.claude/devcard/`;
- the CLI surface of `install.py` and `hook/install_git_hook.py`;
- the deployment config template, `worker/wrangler.example.jsonc`.

## [Unreleased]

### Breaking

- **`setup.py` is now `install.py`.** It never was a setuptools script, and the
  name made Python tooling treat it as one. Same wizard, same steps.
- **Deployment config moved out of git.** `worker/wrangler.toml`, which carried
  one deployment's database id, username and timezone, is replaced by a tracked
  template, `worker/wrangler.example.jsonc`, that `install.py` renders into the
  gitignored `worker/wrangler.jsonc`. For an existing deployment, re-run
  `python install.py` and delete the old `wrangler.toml` — see
  [upgrading](docs/manual-setup.md#upgrading-an-existing-deployment).
- **Supported versions: Python 3.11+ and Node 22+.** Node 18 and 20 and Python
  3.9 are past end of life, and Wrangler itself requires Node 22. Each floor is
  defined once (`install.py`, `worker/package.json`), and tests keep CI, the
  README and Ruff's target version in step with it.
- **The hook has no default Worker URL.** It used to fall back to the
  maintainer's own Worker, so a hook installed without the installer sent its
  token and activity there. Unconfigured, it now captures locally and sends
  nothing.

### Security

- Ingest answers `503` when the Worker has no `INGEST_TOKEN` secret, instead of
  depending on how an absent value compares.
- The token comparison uses the runtime's `crypto.subtle.timingSafeEqual`, in the
  length-safe pattern Cloudflare documents, instead of a hand-written loop.
- A JSON body that is valid but not an object (`null`, `[]`, `42`) is a `400`; it
  used to throw, which surfaced as a `500`.
- SVG responses carry `Content-Security-Policy: default-src 'none'` (plus inline
  style and `data:` images) and `X-Content-Type-Options: nosniff`, so a card
  opened as a document can neither run script nor load anything.
- The local token file is owner-only on every platform: created `0600` rather
  than written and then `chmod`-ed, and on Windows with inherited permissions
  removed. The installer no longer writes a second copy of the production token
  into `worker/.dev.vars`.
- Workflows: every Action pinned to a commit SHA (including the SCPE gate, which
  was on a movable tag), `persist-credentials: false` everywhere, timeouts and
  concurrency limits, no pull-request data interpolated into shell, and the
  artifact the trusted `scpe-seal` job reads is validated before use.
- New `security` workflow: Gitleaks over the full history, dependency review on
  pull requests, and CodeQL for TypeScript, Python and the workflows. Dependabot
  version updates for npm and Actions, with a seven-day cooldown.
- npm dependency install scripts are disabled for the Worker toolchain.

### Added

- **A `wide` layout** (`?layout=wide`, 840×~430) that lays the card across a
  README's full column instead of using half of it: legend in three columns,
  larger heatmap, pinned repos and badges beside it rather than below. Type
  sizes are the ones `full` uses — this is a different layout, not the same one
  scaled up.
- **A hover layer over the language bar.** The bar's tail is genuinely
  sub-pixel on a real account (Java 0.05px, Ruby 0.00px), so an invisible layer
  gives every language a target of at least 3px, taken from the segments that
  have pixels to spare so the targets tile the bar exactly and never overlap.
  Pointing at one names it and shows its share. It works wherever the SVG is a
  document — the card's URL opened directly, or an `<object>` embed.
- **An `other` row in the legend**, collapsing the languages past the sixth so
  the legend stays short. The bar itself still draws every language.
- **`?langs=all`**, which names every language in the legend instead of
  collapsing the tail. Useful when the card's URL is opened directly.
- **`?part=` — the card served in pieces, so a GitHub README can hover one
  language.** A README embeds through an `<img>`, where browsers deliver no
  pointer events into the SVG, and GitHub's sanitizer removes `<object>`,
  `<iframe>`, inline `<svg>`, `<style>` and `<map>`/`<area>`. A `title` on an
  `<img>` does survive, but names a whole image — so the bar stops being part of
  the same image as the rest of the card: a body, two end caps and one slice per
  language, tiled into a row with a `title` each. The bar is the card's last row
  because a paragraph's 24px line box would otherwise leave a gap inside the
  card. Slices are floored at 4px, paid for out of the segments with pixels to
  spare; the percentage in each tooltip is still the true share.
- **`GET /embed`**, which returns that block ready to paste, and
  `scripts/refresh_readme.py` with a weekly workflow to regenerate it — the
  widths and tooltip text are HTML attributes, so they live in the README and
  cannot follow the data on their own.

- **Global event identity.** Every installation generates a random, opaque
  `source_id`; D1 dedupes on `(source_id, client_event_id)` instead of the local
  rowid alone. Two machines can now share one backend.
- **Per-event namespaces.** The local `events` table stores a `source_id` per
  row, stamped at insert and never changed, and the wire format lets an event
  override the batch's. A batch can therefore mix a backlog queued before the
  installation had an id with events captured after it.
- **A local failure log throttle** (`_log_throttled`), so a missing Worker URL
  or installation id, which repeats on every sync, writes one line an hour
  instead of thousands.
- **`worker/migrations/0001_event_source_id.sql`** to upgrade an existing D1
  database.
  Nothing is deleted or renumbered; pre-existing rows and hooks that predate the
  field keep their previous behaviour under a `legacy` namespace.
- **Product CI** (`.github/workflows/ci.yml`): the hook and installer suites on
  Ubuntu and Windows (Python 3.11 and 3.14), Ruff, and the Worker's typecheck,
  test suite and a dry-run bundle (Node 22 and 24), on every pull request and
  push to `main`. One aggregate check, `ci-ok`, is what the branch ruleset
  requires, so changing the matrix never strands a required check.
- **Worker test suite** running inside workerd against a real local D1 via
  `@cloudflare/vitest-plugin` — ingest auth and validation, body and batch caps,
  event identity, cache keys, rendering, XML escaping, response headers,
  timezone handling and the nightly rollup rebuild.
- **Installer tests** that run `install.py` end to end against a fake
  Node/npm/Wrangler: every check before any change, the Worker secret before its
  local copy, and a second run that converges instead of duplicating.
- **git integration tests** against real temporary repositories: merge, octopus,
  fast-forward, squash, first commit, `core.hooksPath`, worktrees, existing
  hooks, husky, and paths with spaces.
- `--uninstall` for `hook/install_git_hook.py`.
- `~/.claude/devcard/worker-url` (and `DEVCARD_WORKER_URL`) as the hook's
  endpoint configuration.
- `docs/retention.md` — the capacity reasoning behind leaving raw events in
  place, and the queries to measure your own installation.

### Fixed

- **Deleting `events.db` silently dropped every new event.** The installation
  id survived the deletion while the row ids restarted at 1, so each new event
  arrived on a key D1 already held: `INSERT OR IGNORE` discarded it, the hook
  saw a 2xx and marked it synced, and the card stopped counting until the new
  ids passed the old maximum. A new database now retires the old id.
- **The AI-use disclosure check never blocked a merge.** The SCPE Action exits 0
  at level 1 so its results reach the commenting job, which left the required
  `verify` check green without a disclosure. `verify` now fails in that case
  (Dependabot excepted); `scpe-seal` still posts the explanation.
- **The last edits of a session could wait for the next session.** The capture
  hook starts the syncer at most once per 20 seconds, so an edit made inside that
  window started nothing and stayed local until the next tool call — possibly
  the next day. The syncer now drains once more when the window closes.
- **git mode drained one 50-event batch per commit.** Nothing else sends in git
  mode, so a backlog built up offline trailed behind for as many commits as it
  had batches. A commit now drains up to 2,000 events, in the background.
- **The installer never opened the Cloudflare login.** `wrangler whoami` exits 0
  when logged out, so checking its exit code always passed; it now uses
  `whoami --json`, which fails.
- **Re-running the installer reset the card's repository count to zero** until
  the next sync: its smoke test sent `repo_count: 0`, which ingest publishes. The
  smoke test sends no count now.
- **Re-running the installer from a moved clone** left Claude Code calling the old
  hook path, which fails silently by design. The existing entry is updated in
  place.

- **`?theme=constructor` returned a 500.** `THEMES[name]` resolved inherited
  `Object.prototype` members; the theme lookup is now an own-property check.
  Same class of bug in `?lang=`, which painted `undefined` across the card.
- **Language-specific cards could be served to the wrong visitor.** The edge
  cache was keyed on the raw request URL while the language came from
  `Accept-Language`, so whoever asked first froze that language into the entry.
  The key is now the resolved `(lang, theme, layout)` variant, which also stops
  the cache fragmenting on header and query-string noise.
- **Merge commits double-counted.** `git diff HEAD~1 HEAD` on a merge reports
  every line the merged branch brought in — lines already counted per commit. A
  merge now records one commit and no lines.
- **The git hook installed to the wrong place.** It assumed `.git/hooks/`,
  which is wrong for `core.hooksPath`, worktrees and submodules; it now asks
  `git rev-parse --git-path`. It also refuses to append shell to a non-shell
  hook instead of corrupting it, and redirects husky installs out of the
  regenerated `.husky/_` folder.
- **The installer split folder input on whitespace,** so any path containing a
  space was silently discarded. Folders are now entered one per line.
- **Deleted files donated their added bytes to the next file** in the git
  hook's patch parser.
- **Heatmap month labels overlapped into "MayJun"** when two months started in
  consecutive weeks. A label is now skipped if it would land within three weeks
  of the previous one.
- Local `devcard_lib` paths are resolved from the module at call time rather
  than captured as default arguments — patching them in a test used to do
  nothing, so a test run could write into the real `events.db`.
- **Upgrading duplicated an un-acknowledged backlog.** An event synced by an
  older hook was stored as `legacy/<rowid>`; if the response was lost the local
  row stayed unsynced, and the upgraded hook re-sent it under the installation's
  new id — a different key, so the Worker stored it a second time. Each local
  row now records the namespace it was queued under and is re-sent under that.
- **A failure to persist the installation id fell back to `legacy`,** silently
  undoing multi-machine identity for that installation. The hook now sends
  nothing, keeps the events, logs once and retries; capture is unaffected.
- The suite read the developer's real `~/.claude/devcard/source-id`, so its
  results depended on whether that file happened to exist — passing locally and
  failing on a CI runner. Every hook test module now redirects the devcard paths
  to a throwaway directory.

### Changed

- **`@cloudflare/vitest-pool-workers` is replaced by `@cloudflare/vitest-plugin`**,
  Cloudflare's successor, migrated with the official codemod. Together with
  Wrangler 4.132 this resolves the `sharp` advisory (GHSA-rgj7-g3m4-5g8c) that
  the old dependency tree held in place; `npm audit` reports nothing.
  TypeScript 7, current workers-types, compatibility date 2026-09-15.
- **The weekly README refresh opens a pull request** instead of pushing to
  `main`, which the branch ruleset rightly rejects. It updates one open pull
  request rather than stacking new ones, and does nothing when the block has not
  changed.
- The nightly rebuild scans `events` four times instead of six: bytes, count
  and first timestamp come from one pass.
- `docs/retention.md` no longer publishes one installation's exact activity
  figures; it gives rounded capacity bounds and a way to measure your own.
- `CLAUDE.md` holds only durable guidance for coding agents; dated state moved
  out.

- **The README was cut from 524 lines to under 150.** The reference material it had
  accumulated — counting rules, the privacy and security model, the GitHub
  hover measurements, the manual setup steps — moved to `docs/` under their own
  headings, linked from a short index. Nothing was dropped.
- **`code edits` is now a claude-mode-only stat.** Git-mode rows are stored
  under a new `diff` event type instead of sharing `edit`, because one is an
  agent tool call and the other a per-commit, per-language aggregate. A
  git-captured card shows commits alone rather than an impressive but
  meaningless number. Lines, languages, heatmap and streak are unchanged in
  both modes.
- The installer verifies Python, Node, npm and git before it creates anything,
  runs `npm ci`, and calls the locked Wrangler directly rather than whatever
  `npx` fetches today.
- The installer no longer rewrites `WORKER_INGEST_URL` in `hook/devcard_lib.py`;
  the endpoint is local config.
- `~/.claude/settings.json` keeps its *first* backup instead of being
  re-backed-up over on a second run, and is validated before any provisioning
  starts.
- A partial index on unsynced events keeps the local sync query off a full
  table scan.
