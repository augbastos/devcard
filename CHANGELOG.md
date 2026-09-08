# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims
to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

What "public API" means for devcard, since it is not a library:

- the `GET /svg` query parameters and the shape of the card;
- the `POST /ingest` request body;
- the D1 schema;
- the local files under `~/.claude/devcard/`;
- the CLI surface of `setup.py` and `hook/install_git_hook.py`.

## [Unreleased]

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
  rowid alone. Two machines can now share one backend, and deleting the local
  `events.db` no longer collides with already-synced history.
- **Per-event namespaces.** The local `events` table stores a `source_id` per
  row, stamped at insert and never changed, and the wire format lets an event
  override the batch's. A batch can therefore mix a backlog queued before the
  installation had an id with events captured after it.
- **A local failure log throttle** (`_log_throttled`), so a persistent failure
  that repeats every ~20 seconds writes one line an hour instead of thousands.
- **`worker/migrations/0001_event_source_id.sql`** to upgrade an existing D1
  database.
  Nothing is deleted or renumbered; pre-existing rows and hooks that predate the
  field keep their previous behaviour under a `legacy` namespace.
- **Product CI** (`.github/workflows/ci.yml`): the hook suite on Python 3.9,
  3.11 and 3.13, plus the Worker's typecheck and test suite on every pull
  request and push to `master`.
- **Worker test suite** running inside workerd against a real local D1 via
  `@cloudflare/vitest-pool-workers` — ingest auth and validation, body and batch
  caps, event identity, cache keys, rendering, XML escaping, timezone handling
  and the nightly rollup rebuild.
- **git integration tests** against real temporary repositories: merge, octopus,
  fast-forward, squash, first commit, `core.hooksPath`, worktrees, existing
  hooks, husky, and paths with spaces.
- `--uninstall` for `hook/install_git_hook.py`.
- `~/.claude/devcard/worker-url` (and `DEVCARD_WORKER_URL`) as the hook's
  endpoint configuration.
- `docs/retention.md` — the measurements behind leaving raw events in place.

### Fixed

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
- **`setup.py` split folder input on whitespace,** so any path containing a
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

- **The README is 216 lines instead of 524.** The reference material it had
  accumulated — counting rules, the privacy and security model, the GitHub
  hover measurements, the manual setup steps — moved to `docs/` under their own
  headings, linked from a short index. Nothing was dropped.
- **`code edits` is now a claude-mode-only stat.** Git-mode rows are stored
  under a new `diff` event type instead of sharing `edit`, because one is an
  agent tool call and the other a per-commit, per-language aggregate. A
  git-captured card shows commits alone rather than an impressive but
  meaningless number. Lines, languages, heatmap and streak are unchanged in
  both modes.
- `setup.py` verifies Python, Node (>= 18), npm and git versions before it
  creates anything, and runs `npm ci` so wrangler comes from the lockfile
  rather than whatever `npx` fetches today.
- `setup.py` no longer rewrites `WORKER_INGEST_URL` in `hook/devcard_lib.py`.
- The local token file is written `0600` on macOS/Linux.
- `~/.claude/settings.json` keeps its *first* backup instead of being
  re-backed-up over on a second run, and is validated before any provisioning
  starts.
- A partial index on unsynced events keeps the local sync query off a full
  table scan.
