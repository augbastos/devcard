# devcard — a live, embeddable dev stats card powered by real AI-coding activity

[![ci](https://github.com/augbastos/devcard/actions/workflows/ci.yml/badge.svg)](https://github.com/augbastos/devcard/actions/workflows/ci.yml)
[![scpe](https://github.com/augbastos/devcard/actions/workflows/scpe.yml/badge.svg)](https://github.com/augbastos/devcard/actions/workflows/scpe.yml)
[![scpe-seal](https://github.com/augbastos/devcard/actions/workflows/scpe-seal.yml/badge.svg)](https://github.com/augbastos/devcard/actions/workflows/scpe-seal.yml)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![TypeScript](https://img.shields.io/badge/TypeScript-5.5-3178c6?logo=typescript&logoColor=white)
![Cloudflare Workers + D1](https://img.shields.io/badge/Cloudflare-Workers%20%2B%20D1-f38020?logo=cloudflare&logoColor=white)
![Python 3](https://img.shields.io/badge/Python-3-3776AB?logo=python&logoColor=white)

**A live, embeddable dev stats card — powered by your real AI-assisted coding activity, not your keystrokes.**

<p align="center">
  <img src="https://img.shields.io/badge/Claude_Code-live_per--edit-8957e5" alt="Claude Code" />
  <img src="https://img.shields.io/badge/Codex-per--commit-3fb950" alt="Codex" />
  <img src="https://img.shields.io/badge/Cursor-per--commit-3fb950" alt="Cursor" />
  <img src="https://img.shields.io/badge/aider_·_Windsurf_·_local_models-per--commit-3fb950" alt="aider, Windsurf, local models" />
  <img src="https://img.shields.io/badge/license-MIT-blue" alt="MIT" />
</p>

<!-- devcard:start -->
<p><img src="https://card.devcard.workers.dev/svg?user=augbastos&amp;layout=wide&amp;part=body" width="100%" align="top" alt="devcard — augbastos's live coding stats. Languages: Python 41.8%, Markdown 17.7%, TypeScript 14.6%, HTML 10.2%, JavaScript 5.0%, PowerShell 2.7%, JSON 2.6%, CSS 1.8%, SQL 1.6%, YAML 0.7%, Rust 0.6%, Go 0.3%, Shell 0.2%, C++ 0.1%, TOML 0.1%, C 0.1%, Java 0.0%, Ruby 0.0%"><img src="https://card.devcard.workers.dev/svg?user=augbastos&amp;layout=wide&amp;part=cap&amp;side=l" width="3.3333%" align="top" alt=""><img src="https://card.devcard.workers.dev/svg?user=augbastos&amp;layout=wide&amp;part=seg&amp;i=0" width="37.8448%" align="top" title="Python 41.8%" alt=""><img src="https://card.devcard.workers.dev/svg?user=augbastos&amp;layout=wide&amp;part=seg&amp;i=1" width="16.0259%" align="top" title="Markdown 17.7%" alt=""><img src="https://card.devcard.workers.dev/svg?user=augbastos&amp;layout=wide&amp;part=seg&amp;i=2" width="13.2338%" align="top" title="TypeScript 14.6%" alt=""><img src="https://card.devcard.workers.dev/svg?user=augbastos&amp;layout=wide&amp;part=seg&amp;i=3" width="9.2367%" align="top" title="HTML 10.2%" alt=""><img src="https://card.devcard.workers.dev/svg?user=augbastos&amp;layout=wide&amp;part=seg&amp;i=4" width="4.5563%" align="top" title="JavaScript 5.0%" alt=""><img src="https://card.devcard.workers.dev/svg?user=augbastos&amp;layout=wide&amp;part=seg&amp;i=5" width="2.5026%" align="top" title="PowerShell 2.7%" alt=""><img src="https://card.devcard.workers.dev/svg?user=augbastos&amp;layout=wide&amp;part=seg&amp;i=6" width="2.3911%" align="top" title="JSON 2.6%" alt=""><img src="https://card.devcard.workers.dev/svg?user=augbastos&amp;layout=wide&amp;part=seg&amp;i=7" width="1.6209%" align="top" title="CSS 1.8%" alt=""><img src="https://card.devcard.workers.dev/svg?user=augbastos&amp;layout=wide&amp;part=seg&amp;i=8" width="1.4206%" align="top" title="SQL 1.6%" alt=""><img src="https://card.devcard.workers.dev/svg?user=augbastos&amp;layout=wide&amp;part=seg&amp;i=9" width="0.6204%" align="top" title="YAML 0.7%" alt=""><img src="https://card.devcard.workers.dev/svg?user=augbastos&amp;layout=wide&amp;part=seg&amp;i=10" width="0.5468%" align="top" title="Rust 0.6%" alt=""><img src="https://card.devcard.workers.dev/svg?user=augbastos&amp;layout=wide&amp;part=seg&amp;i=11" width="0.4762%" align="top" title="Go 0.3%" alt=""><img src="https://card.devcard.workers.dev/svg?user=augbastos&amp;layout=wide&amp;part=seg&amp;i=12" width="0.4762%" align="top" title="Shell 0.2%" alt=""><img src="https://card.devcard.workers.dev/svg?user=augbastos&amp;layout=wide&amp;part=seg&amp;i=13" width="0.4762%" align="top" title="C++ 0.1%" alt=""><img src="https://card.devcard.workers.dev/svg?user=augbastos&amp;layout=wide&amp;part=seg&amp;i=14" width="0.4762%" align="top" title="TOML 0.1%" alt=""><img src="https://card.devcard.workers.dev/svg?user=augbastos&amp;layout=wide&amp;part=seg&amp;i=15" width="0.4762%" align="top" title="C 0.1%" alt=""><img src="https://card.devcard.workers.dev/svg?user=augbastos&amp;layout=wide&amp;part=seg&amp;i=16" width="0.4762%" align="top" title="Java 0.0%" alt=""><img src="https://card.devcard.workers.dev/svg?user=augbastos&amp;layout=wide&amp;part=seg&amp;i=17" width="0.4762%" align="top" title="Ruby 0.0%" alt=""><img src="https://card.devcard.workers.dev/svg?user=augbastos&amp;layout=wide&amp;part=cap&amp;side=r" width="3.3334%" align="top" alt=""></p>
<!-- devcard:end -->

<p align="center"><em>↑ A real, live card. Point at the bar and it names the language under the pointer.</em></p>

Tools like WakaTime measure how long your editor is focused. devcard measures something new: **the actual output of your AI coding sessions**. A tiny hook watches every edit Claude Code makes on your machine, and your card updates in near real time — languages, volume, commits, activity — wherever it's embedded.

## Why it's different

- **Live, not batch.** The card reflects your latest coding session within seconds, not "synced last night."
- **Measures agent output.** Built for the vibe-coding era: it captures what you *ship* with an AI agent, which keystroke timers can't see.
- **Private by architecture, not by promise.** Project names, file paths, and code content **never leave your machine**. The public backend only ever receives: language, line counts, event type, timestamp, and a repo *count* (your GitHub repository total — see [what it counts](#what-the-repo-count-actually-counts)). There is no column in the public database where a filename could even be stored.
- **Embeds anywhere.** It's just an SVG URL — paste it in your GitHub profile README, portfolio, blog, anywhere `<img>` works.
- **Speaks the viewer's language.** The card auto-localizes (en/pt/es) based on the visitor's browser. Force one with `?lang=pt`.
- **Auto dark/light.** Follows the viewer's system theme via `prefers-color-scheme`.
- **Sponsor button, automatically.** If your GitHub Sponsors page is active, a ♥ Sponsor pill appears on its own.

## How it works

```mermaid
flowchart LR
    subgraph M["your machine"]
        CC["Claude Code<br/>PostToolUse hook"] -->|"every Edit / Write / Bash"| DB[("local SQLite<br/>full detail, offline-first")]
        GT["git post-commit hook<br/>(Codex, Cursor, aider, hand-typed…)"] -->|"git diff --numstat"| DB
        DB -->|"throttled, detached"| SY["devcard_sync.py"]
    end
    SY -->|"POST /ingest<br/>anonymized batches, token-gated"| W["Cloudflare Worker + D1"]
    E["your embed<br/>README · site · anywhere"] -->|"GET /svg"| W
    W -->|"rendered SVG<br/>cached 60s"| E
```

1. A global Claude Code `PostToolUse` hook fires on every `Edit`/`Write`/`Bash` call — pure Python stdlib, zero token cost, runs in milliseconds, and **never blocks your session** (all errors are swallowed and logged locally).
2. Events land in a local SQLite database first (source of truth — works offline, syncs later).
3. Anonymized batches sync to a Cloudflare Worker + D1 (free tier is plenty).
4. The Worker renders your SVG card on demand, cached 60s.

## Deploy your own — one command

You need: Python 3.9+, Node 18+, npm, git, and a free [Cloudflare account](https://dash.cloudflare.com/sign-up). The wizard checks all of them before it creates anything.

```bash
git clone https://github.com/augbastos/devcard && cd devcard && python setup.py
```

The wizard does everything: creates your D1 database, applies the schema, generates and stores your ingest token, deploys your Worker, installs the capture hook, runs an end-to-end smoke test, and prints your ready-to-paste embed snippet. Two questions, ~2 minutes.

## Works with your agent

Pick **one** capture mode per machine (both together would double-count the same lines):

| Your tool | Mode | Granularity | How |
|---|---|---|---|
| **Claude Code** | `claude` | Live, per-edit — card moves while you code | Native `PostToolUse` hook (installed by `setup.py`) |
| **OpenAI Codex** | `git` | Per-commit, real diff stats | git `post-commit` hook |
| **Cursor** | `git` | Per-commit, real diff stats | git `post-commit` hook |
| **aider / Windsurf / Cline** | `git` | Per-commit, real diff stats | git `post-commit` hook |
| **Local models** (Ollama, LM Studio, llama.cpp + anything) | `git` | Per-commit, real diff stats | git `post-commit` hook |
| **Hand-typed code** | `git` | Per-commit, real diff stats | git `post-commit` hook |

The `git` mode hooks **git itself, not the agent** — that's why the compatibility list is "anything that commits", with zero per-tool integration code to maintain. It reads each commit's real `git diff --numstat` (lines and bytes per language), so the numbers are actual diff stats, not estimates.

Install it into any repos you want tracked:

```bash
python hook/install_git_hook.py "C:/path/to/your projects"    # a repo, or a folder of repos
python hook/install_git_hook.py --uninstall "C:/path/to/your projects"
```

Each path is one argument, so spaces are fine. A path may be a repository or a
folder containing repositories (scanned one level deep, plus the folder
itself).

Where the hook goes is asked of git (`git rev-parse --git-path hooks/post-commit`)
rather than assumed to be `.git/hooks/`, which means it also works for:

- repos that set **`core.hooksPath`**;
- **worktrees and submodules**, where `.git` is a file, not a directory (a repo
  and its worktrees share one hooks directory, so it installs once);
- **husky** — its runnable hooks live in `.husky/_`, which husky regenerates and
  gitignores, so the line goes to `.husky/post-commit` where it survives the
  next `npm install`.

An existing hook is appended to, never overwritten, and installing twice is a
no-op. If the existing `post-commit` is **not** a shell script (a Python or Ruby
hook, say), the installer refuses to touch it and prints the line to add by
hand — appending `sh` to a Python file would have broken the hook that was
already there. `--uninstall` removes only devcard's line, and deletes the file
only if devcard was all it contained.

New agent hits the market tomorrow? If it commits to git, your card already supports it.

<details>
<summary><strong>Manual setup</strong> (if you prefer to see every step)</summary>

### 1. Clone and create your backend

```bash
git clone https://github.com/augbastos/devcard
cd devcard/worker
npm install
npx wrangler login
npx wrangler d1 create devcard        # copy the database_id it prints
```

Edit `worker/wrangler.toml`: paste **your** `database_id` and set `GITHUB_USERNAME` to your GitHub login.

```bash
npx wrangler d1 execute devcard --remote --file=schema.sql
npx wrangler deploy                    # note your URL: card.<your-subdomain>.workers.dev
```

### 2. Create your ingest token

```bash
python -c "import secrets; print(secrets.token_hex(24))"
npx wrangler secret put INGEST_TOKEN   # paste the token when prompted
```

Set the same token as an environment variable so the hook can use it:

```bash
# Windows
setx DEVCARD_INGEST_TOKEN "<your-token>"
# macOS/Linux — add to your shell profile
export DEVCARD_INGEST_TOKEN="<your-token>"
```

### 3. Point the hook at your Worker

Write your Worker's ingest URL to `~/.claude/devcard/worker-url`:

```bash
# Windows (PowerShell)
"https://<your-worker-url>/ingest" | Set-Content $HOME/.claude/devcard/worker-url
# macOS/Linux
echo "https://<your-worker-url>/ingest" > ~/.claude/devcard/worker-url
```

`DEVCARD_WORKER_URL` overrides the file if you prefer an environment variable.
This used to be an edit to `WORKER_INGEST_URL` in `hook/devcard_lib.py`; it was
moved out of tracked source so that `git clone && python setup.py` does not
leave your personal endpoint sitting in a source file, ready to be committed or
to conflict on the next `git pull`.

### 4. Register the hook in Claude Code

Add to `~/.claude/settings.json` (adjust both paths to your machine):

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write|Bash",
        "hooks": [
          {
            "type": "command",
            "command": "python /path/to/devcard/hook/devcard_capture.py",
            "timeout": 3000
          }
        ]
      }
    ]
  }
}
```

Restart Claude Code, write some code, and open `https://<your-worker-url>/svg?user=<you>`. That's your card.

</details>

### Embed it

```html
<img src="https://<your-worker-url>/svg?user=<you>" alt="devcard" />
```

For your GitHub profile: create a repo named exactly like your username, and paste that line into its README.

## Layouts & themes

Mix and match with query params — every combination is a valid embed:

```html
<img src="https://<your-worker-url>/svg?user=<you>&layout=banner&theme=terminal" alt="devcard" />
```

**Layouts** (`?layout=`):

| Value | Size | What you get |
|---|---|---|
| `full` (default) | 480×tall | Everything: avatar, streak flame, language bar + legend, 16-week contribution heatmap, pinned repos, stats, badges |
| `wide` | 840×~430 | The same content laid out across a README's full column width — legend in three columns, larger heatmap, pinned repos and badges beside it rather than below |
| `banner` | 480×72 | One-line strip: avatar, @user, lines, streak, mini language bar — for forum sigs and tight READMEs |
| `half` | 480×152 | Header + lines + language bar + stats row |
| `vertical` | 280×~290 | Narrow column for site/blog sidebars |

`?langs=all` names every language in the legend instead of collapsing the tail
into one `other` row. It works on `full` and `wide`, and is for opening the card
directly — an embedded card is better off with the grouped legend, see
[the language bar](#the-language-bar-and-its-long-tail).

**Themes** (`?theme=`): `default` (follows the viewer's light/dark system theme) · `dark` · `light` · `gentle` (soft rosé/lilac) · `cyberpunk` (neon noir) · `terminal` (green-phosphor CRT).

The heatmap paints real per-day output (intensity relative to your own p90, so one huge day doesn't flatten the rest), the flame lights up at a 7+ day streak, and the footer shows "updated Xmin ago" — a live card that can prove it's live. Day boundaries use the `TIMEZONE` var in `wrangler.toml`.

### The language bar, and its long tail

The bar draws every language to exact proportion, which on a real account means
a tail thinner than a pixel — measured on this card: Shell 0.65px, C++ 0.55px,
Java 0.05px, Ruby 0.00px. Nothing is dropped or padded, so the picture stays
honest, and the legend below collapses the tail into one `other` row rather than
listing rows of 0.0%.

To make those slivers identifiable, an invisible hover layer sits over the bar.
Every language gets a target at least 3px wide — paid for out of the segments
that have pixels to spare, so the targets tile the bar exactly and never
overlap — and pointing at one shows its name and share.

That hover works wherever the SVG is a **document**: open the card's URL
directly, or embed it somewhere you control the markup with
`<object data="…" type="image/svg+xml">`. A GitHub README is neither, and gets
there another way — see below.

### Hover inside a GitHub README

The card above is hoverable on GitHub. Getting there meant giving up the idea
that a card is one image.

GitHub renders an embed through an `<img>`, and browsers put SVG-in-`<img>` in
secure static mode: no pointer event reaches the document, so the SVG's own
hover layer is unreachable. Every element that could carry the interaction
instead is removed by GitHub's HTML sanitizer — measured against GitHub's own
markdown renderer, not assumed:

| | in a README |
|---|---|
| `<object>`, `<embed>`, `<iframe>` | stripped |
| inline `<svg>`, `<style>` | stripped |
| `<map>` / `<area>` (image map) | stripped |
| `usemap` on `<img>` | kept, but its `<map>` is gone, so it does nothing |
| `title` on `<img>` | **kept** — and it is a real tooltip |
| `<details>` / `<summary>` | **kept**, including images inside |

A `title` names a whole image, so one image can only ever have one tooltip. The
way out is for the bar to stop being part of the same image as the rest of the
card: `?part=` serves the card as a body plus one slice per language, tiled into
a row, each slice carrying its own `title`. Point at Ruby's sliver and it says
Ruby.

Three measurements on a rendered README fixed the geometry:

- Adjacent `<img>` tags with **no whitespace between them** tile with a gap of
  exactly 0, and percentage widths span the column exactly. A newline between
  two tags becomes a space, and a space becomes a visible seam — which is why
  the generated block is one long line.
- `align="left"` stacks rows with no vertical gap, but GitHub's CSS gives
  `img[align=left]` a `padding-right: 20px`, which blows a horizontal row apart.
  `align="top"` stacks with no gap and adds no padding, so every piece uses it.
- A paragraph always reserves a 24px line box, so a row of short images leaves
  ~12px of slack **after** it. That is why the bar is the card's last row: the
  slack falls below the card, where nothing shows it. Anywhere else it would
  open a gap inside the card on a narrow column.

The bar is drawn with a 4px floor per language, paid for out of the segments
that have pixels to spare. Without it eight languages here sit under a pixel and
three under a tenth of one — a bar that draws them honestly draws them
invisible, and nothing can point at 0.03px. The percentage in each tooltip is
the true share; only the pixels move.

**Using it.** Ask the Worker for the block and paste it between two markers:

```bash
curl https://<your-worker-url>/embed?user=<you>
```

```html
<!-- devcard:start -->
…the block…
<!-- devcard:end -->
```

The widths and the tooltip text are HTML attributes, so they live in your README
and cannot follow your data on their own. `.github/workflows/devcard-readme.yml`
regenerates them weekly with `scripts/refresh_readme.py`; every slice's pixels
are fetched live on each view, so between runs the colours are current and only
the proportions drift. If the card is unreachable, the script leaves the last
good block alone rather than emptying it.

A plain single-image embed still works everywhere and needs none of this — it
just cannot hover.

## Badges, certifications, awards

Manual, self-declared entries rendered as pills with icons (star = badge, seal = certification, trophy = award):

```bash
cd worker
npx wrangler d1 execute devcard --remote --command \
  "INSERT INTO profile_entries (kind, label, detail, created_at) VALUES ('certification', 'AWS Cloud Practitioner', NULL, strftime('%s','now'))"
```

`kind` is one of `badge` | `certification` | `award`.

## Pinned repos

Highlight up to 3 repos on your card — each renders as a linked box with live star count:

```bash
npx wrangler d1 execute devcard --remote --command \
  "INSERT INTO pinned_repos (repo, note, position, created_at) VALUES ('wavr', 'privacy-first home presence', 1, strftime('%s','now'))"
```

`repo` must be a public repo under your GitHub account. `note` is an optional one-liner. Lowest `position` renders first.

## Customize it (please do)

MIT licensed — fork it and make it yours. No framework, no build step for the card itself — just plain SVG template strings:

- **Colors/themes**: token sets (light + optional dark) in `worker/src/themes.ts` — a new theme is a handful of hex values
- **Layout**: `worker/src/render.ts` (`full`) and `worker/src/render-layouts.ts` (`banner`/`half`/`vertical`)
- **Languages**: detection via the `EXT_LANGUAGE` map in `hook/devcard_lib.py`, colors via `LANGUAGE_COLORS` in `worker/src/svg-utils.ts`
- **Strings/locales**: add a language to `STRINGS` in `worker/src/index.ts` in ~1 line

## Privacy model

| Data | Local SQLite | Public D1/card |
|---|---|---|
| Language, lines added/removed | ✅ | ✅ |
| Event type, timestamp | ✅ | ✅ |
| Repo **count** (a number) | ✅ | ✅ |
| Random installation id (`source_id`) | ✅ | ✅ (stored, never rendered) |
| Project names / paths | ✅ (never leaves) | ❌ no column exists |
| File names, code content | ❌ never stored | ❌ |
| Hostname, username, MAC address | ❌ never read | ❌ |

The sync payload is built from a SQL projection that physically excludes project identifiers, and the public schema has nowhere to put them. Ingest is token-gated and idempotent. The whole request body is three keys — `events`, `repo_count`, `source_id` — and the test suite asserts that on the serialized bytes, not on a comment.

### What the repo count actually counts

It is the number of repositories you **own on GitHub** — public plus private — read locally through the `gh` CLI (already authenticated on your machine) and shipped as a single integer. No GitHub token ever goes near the Worker, and the number matches what the card's `N repos →` link resolves to.

If `gh` isn't installed or the call fails, the card falls back to counting the distinct **git repository roots** you've worked in, resolved from the working directories the hook recorded. Those directories stay local; only the total is published.

The raw count of working directories is deliberately never published. A cwd is not a repo: agent scratchpads, `node_modules`, and eleven subfolders of one project would each register as "a repo" and inflate the number several-fold.

## Security model

The card is designed so it can't be turned against its owner:

- **No inbound surface on your machine.** The hook opens no ports and listens to nothing — it only makes outbound HTTPS calls to *your* Worker. There is nothing on your computer for an attacker to connect to.
- **Ingest is locked down.** `POST /ingest` requires a secret token, enforces strict schema validation (types, ranges, event-type whitelist), caps batch size (100 events) and body size (256 KB), and skips anything malformed instead of erroring.
- **The public endpoint is read-only aggregate data.** `GET /svg` runs fixed, parameterized SQL over anonymous aggregates. The `user` parameter is only ever *compared* against your configured username — never used in a query or a fetch.
- **Rendering is injection-safe.** Every dynamic string (badge labels, repo names, notes) is XML-escaped before entering the SVG; the SVG contains no scripts.
- **Query parameters cannot reach an inherited property.** `?theme=`, `?lang=` and `?layout=` are resolved with own-property lookups, so `?theme=constructor` falls back to the default instead of resolving `Object.prototype.constructor` (which used to 500 the card).
- **Secrets never touch git.** The token lives in Wrangler's secret store + your env; `.dev.vars` is gitignored, and on macOS/Linux the local token file is written `0600`.

## Tests and CI

```bash
python -m unittest discover -s hook -p "test_*.py"   # hook + git integration
cd worker && npm ci && npm run typecheck && npm test  # Worker, workerd + local D1
```

The Worker suite runs inside workerd against a real local D1 through
[`@cloudflare/vitest-pool-workers`](https://developers.cloudflare.com/workers/testing/vitest-integration/),
so ingest, the unique index, the cache key and the rollup rebuild are exercised
by the same engine production uses. No Cloudflare account, secret or network
access is involved; github.com is stubbed at the outbound boundary.

The Python suite builds throwaway git repositories and runs real `git` against
them — the merge and hook-installation behaviour it pins is behaviour of git,
which a mock would only have agreed with.

[`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs both on every pull
request and on `master`, with the hook suite on Python 3.9, 3.11 and 3.13. The
`scpe` workflows next to it check that a pull request discloses AI use; they say
nothing about whether the code works.

## Counting rules

Two capture modes, counting different things on purpose.

**`git` mode** reads `git diff --numstat` per commit, so a line is a real net change.
Commits count invocations that produce a commit; `--amend` is excluded, because it
rewrites one already counted.

**`claude` mode** counts written output — an edit counts the region it replaced, a
write counts the file. That is why the card says *lines written* rather than *lines of
code*: it measures what a session produced, not the size of a codebase.

### "code edits" is a claude-mode number

The two modes do not produce a comparable *count of actions*. In `claude` mode
one row is one agent tool call. In `git` mode one row is a per-commit,
per-language aggregate — two commits touching Python and TypeScript make four
rows, which is not "four edits" in any sense a reader would assume.

So the card does not print one. Git-mode rows are stored under their own event
type (`diff`), and the **`code edits` stat only appears on a card that has agent
edits to report**; a git-captured card shows commits alone. Lines, bytes,
languages, the heatmap and the streak are computed identically in both modes and
are shown in both.

### Merge commits

A merge commit **counts as one commit and contributes no lines.**

`git diff HEAD~1 HEAD` on a merge reports every line the merged branch brought
in — lines already counted when each of those commits was made. Counting them
again inflated the card by the whole size of every branch ever merged. This is
also what `git diff-tree --cc` says: a clean merge introduces no content of its
own.

Related cases, for completeness:

| Case | Counted as |
|---|---|
| Ordinary commit | its own diff against its parent |
| Repository's first commit | its whole tree |
| Merge commit (2+ parents) | one commit, zero lines |
| Fast-forward merge | nothing — git creates no commit, so no hook runs |
| Conflict resolution merge | one commit, zero lines |

Two known limits, stated rather than hidden. A merge that resolves conflicts by
hand can introduce genuinely new lines; those are not counted either, so that
case under-reports by a few lines instead of over-reporting by a branch. And a
**squash merge** produces an ordinary single-parent commit that is
indistinguishable from hand-written work — it is counted in full, so if the
squashed branch's own commits were also captured on this machine, those lines
are counted twice.

Most merges never reach the hook at all: git runs `post-merge`, not
`post-commit`, when it creates the merge commit itself. The ones that do arrive
are `--no-commit` merges and conflict resolutions, which end in an explicit
`git commit`.

### Event identity, and using two machines

Each event carries the local SQLite rowid that produced it, and ingest ignores a
row it has already stored — that is what makes a retried batch after a lost
response count once instead of twice.

A rowid alone is not a global identity, though: every install's sequence starts
at 1. So each installation also generates a random, opaque `source_id` (16 bytes
of `secrets.token_hex`, cached in `~/.claude/devcard/source-id`), and identity is
the pair. That means:

- **two machines can share one backend** — machine B's event 1 is no longer
  mistaken for machine A's and silently dropped;
- **deleting `~/.claude/devcard/events.db` is safe** — the restarted rowid
  sequence continues in the same namespace instead of colliding with history;
- retries stay idempotent, in `events` and in the rollups the card renders from.

The `source_id` is random and carries no hostname, username, MAC address or
path. It is never rendered on the card. Existing deployments upgrade with
[`worker/migrations/0001_event_source_id.sql`](worker/migrations/0001_event_source_id.sql);
rows and hooks that predate it keep their previous behaviour under a `legacy`
namespace, and nothing is deleted or renumbered.

**The namespace belongs to the event, not to the installation.** Each local row
records the namespace it was queued under, and a batch may mix them. That is
what makes upgrading safe: a hook that synced an event before it had an id — and
never got the response back — re-sends that event as `legacy`, matching the row
already in D1, while events captured after the upgrade go out under the new id
in the same request. Without that, upgrading would have counted the whole
un-acknowledged backlog twice.

If an installation id cannot be created or read, the hook **sends nothing** and
keeps the events for a later attempt, logging once locally. It deliberately does
not fall back to `legacy`: that would look like success while quietly merging
this machine's rowids with every other unidentified installation's. Capture is
never blocked — events are still recorded, they simply wait.

Ingest enforces plausibility server-side: events with impossible line counts,
timestamps outside a sane window, or unknown types are rejected. The card's
"tracking since" line shows how long the account has actually been measured.

## Known limitations

- **Squash merges can double-count** in `git` mode if the squashed branch's own
  commits were captured on the same machine — a squash commit is
  indistinguishable from hand-written work. See [Counting rules](#counting-rules).
- **The two capture modes are exclusive per machine.** Running both would count
  the same lines twice; `~/.claude/devcard/mode` is what keeps the git hook quiet
  on a Claude Code machine.
- **`worker/wrangler.toml` is edited by `setup.py`** with your `database_id` and
  GitHub username. It is your fork's deployment config and is meant to be
  committed there — but it does mean `git status` is not clean after setup.
- **Raw events are never deleted.** Deliberate, and measured — see
  [`docs/retention.md`](docs/retention.md).
- **Links inside the card do not click** when it is embedded via `<img>`. A
  browser limitation, shared by every stats card.

## Roadmap

- Signed batches for tamper-evident sync
- More locales and community themes — a theme is about 20 lines of tokens in `worker/src/themes.ts`, PRs welcome
- Multi-user hosted mode

---

Built by [Augusto Bastos](https://github.com/augbastos) · MIT
