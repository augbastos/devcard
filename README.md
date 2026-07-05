# devcard

**A live, embeddable dev stats card — powered by your real AI-assisted coding activity, not your keystrokes.**

<p align="center">
  <img src="https://img.shields.io/badge/Claude_Code-live_per--edit-8957e5" alt="Claude Code" />
  <img src="https://img.shields.io/badge/Codex-per--commit-3fb950" alt="Codex" />
  <img src="https://img.shields.io/badge/Cursor-per--commit-3fb950" alt="Cursor" />
  <img src="https://img.shields.io/badge/aider_·_Windsurf_·_local_models-per--commit-3fb950" alt="aider, Windsurf, local models" />
  <img src="https://img.shields.io/badge/license-MIT-blue" alt="MIT" />
</p>

<p align="center">
  <img src="https://card.devcard.workers.dev/svg?user=augbastos" alt="devcard — live example" />
</p>

<p align="center"><em>↑ This is a real, live card. It updates within seconds of its owner writing code.</em></p>

Tools like WakaTime measure how long your editor is focused. devcard measures something new: **the actual output of your AI coding sessions**. A tiny hook watches every edit Claude Code makes on your machine, and your card updates in near real time — languages, volume, commits, activity — wherever it's embedded.

## Why it's different

- **Live, not batch.** The card reflects your latest coding session within seconds, not "synced last night."
- **Measures agent output.** Built for the vibe-coding era: it captures what you *ship* with an AI agent, which keystroke timers can't see.
- **Private by architecture, not by promise.** Project names, file paths, and code content **never leave your machine**. The public backend only ever receives: language, line counts, event type, timestamp, and a repo *count*. There is no column in the public database where a filename could even be stored.
- **Embeds anywhere.** It's just an SVG URL — paste it in your GitHub profile README, portfolio, blog, anywhere `<img>` works.
- **Speaks the viewer's language.** The card auto-localizes (en/pt/es) based on the visitor's browser. Force one with `?lang=pt`.
- **Auto dark/light.** Follows the viewer's system theme via `prefers-color-scheme`.
- **Sponsor button, automatically.** If your GitHub Sponsors page is active, a ♥ Sponsor pill appears on its own.

## How it works

```
Claude Code session                     your Cloudflare account            anywhere
┌───────────────────┐  every edit   ┌───────────────┐   ┌────────┐   ┌──────────────────┐
│ PostToolUse hook  ├──────────────▶│ local SQLite  │   │ Worker │◀──│ <img src=…/svg>  │
│ (Python, stdlib)  │               │ (full detail) │   │  + D1  │   │  README / site   │
└───────────────────┘               └───────┬───────┘   └────────┘   └──────────────────┘
                                            │ anonymized batches ▲
                                            └────────────────────┘
```

1. A global Claude Code `PostToolUse` hook fires on every `Edit`/`Write`/`Bash` call — pure Python stdlib, zero token cost, runs in milliseconds, and **never blocks your session** (all errors are swallowed and logged locally).
2. Events land in a local SQLite database first (source of truth — works offline, syncs later).
3. Anonymized batches sync to a Cloudflare Worker + D1 (free tier is plenty).
4. The Worker renders your SVG card on demand, cached 60s.

## Deploy your own — one command

You need: Python 3, Node 18+, git, and a free [Cloudflare account](https://dash.cloudflare.com/sign-up).

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

Install it into any repos you want tracked (appends safely to existing hooks like husky — nothing gets overwritten):

```bash
python hook/install_git_hook.py C:/path/to/your/projects
```

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

In `hook/devcard_lib.py`, set `WORKER_INGEST_URL` to `https://<your-worker-url>/ingest`.

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
| `banner` | 480×72 | One-line strip: avatar, @user, lines, streak, mini language bar — for forum sigs and tight READMEs |
| `half` | 480×152 | Header + lines + language bar + stats row |
| `vertical` | 280×~290 | Narrow column for site/blog sidebars |

**Themes** (`?theme=`): `default` (follows the viewer's light/dark system theme) · `dark` · `light` · `gentle` (soft rosé/lilac) · `cyberpunk` (neon noir) · `terminal` (green-phosphor CRT).

The heatmap paints real per-day output (intensity relative to your own p90, so one huge day doesn't flatten the rest), the flame lights up at a 7+ day streak, and the footer shows "updated Xmin ago" — a live card that can prove it's live. Day boundaries use the `TIMEZONE` var in `wrangler.toml`.

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

MIT licensed — fork it and make it yours. Everything visual lives in one function (`renderCard` in `worker/src/index.ts`):

- **Colors/themes**: one `<style>` block with light + dark palettes
- **Layout**: plain SVG template strings, no framework
- **Languages**: `EXT_LANGUAGE` map in `hook/devcard_lib.py`, colors in `LANGUAGE_COLORS`
- **Strings/locales**: add a language to `STRINGS` in ~1 line

## Privacy model

| Data | Local SQLite | Public D1/card |
|---|---|---|
| Language, lines added/removed | ✅ | ✅ |
| Event type, timestamp | ✅ | ✅ |
| Repo **count** (a number) | ✅ | ✅ |
| Project names / paths | ✅ (never leaves) | ❌ no column exists |
| File names, code content | ❌ never stored | ❌ |

The sync payload is built from a SQL projection that physically excludes project identifiers, and the public schema has nowhere to put them. Ingest is token-gated and idempotent.

## Security model

The card is designed so it can't be turned against its owner:

- **No inbound surface on your machine.** The hook opens no ports and listens to nothing — it only makes outbound HTTPS calls to *your* Worker. There is nothing on your computer for an attacker to connect to.
- **Ingest is locked down.** `POST /ingest` requires a secret token, enforces strict schema validation (types, ranges, event-type whitelist), caps batch size (100 events) and body size (256 KB), and skips anything malformed instead of erroring.
- **The public endpoint is read-only aggregate data.** `GET /svg` runs fixed, parameterized SQL over anonymous aggregates. The `user` parameter is only ever *compared* against your configured username — never used in a query or a fetch.
- **Rendering is injection-safe.** Every dynamic string (badge labels, repo names, notes) is XML-escaped before entering the SVG; the SVG contains no scripts.
- **Secrets never touch git.** The token lives in Wrangler's secret store + your env; `.dev.vars` is gitignored.

## Data honesty

Full disclosure: like every self-hosted stats card, the data is **self-reported** from the owner's machine — absolute proof is impossible without a trusted third party. What devcard does about it:

- **Plausibility enforcement at ingest**: single events claiming absurd line counts, timestamps outside a sane window, or unknown event types are rejected server-side. Gross inflation requires sustained, visible effort rather than one fake request.
- **Provenance on the card**: the "tracking since <date> · N events" line shows how long and how much has actually been measured — a fresh account claiming huge numbers is visibly suspicious.
- **Roadmap**: device-key signed batches (tamper-evidence for the sync channel) and public per-day aggregate endpoints so anyone can inspect a card's history for anomalies.

This is also why the levels/XP system isn't rendered yet — gamified numbers deserve stronger guarantees before they're comparable between people.

## Known limits (v1)

- Single-user per deployment (your card, your Worker).
- Line counts for edits are approximate (counts edited regions, not a semantic diff).
- Inside `<img>`, SVG links aren't clickable (browser limitation — same as every stats card). Open the card URL directly for clickable repos/Sponsor.
- Levels/XP system exists in the data model but is intentionally not rendered yet — it needs anti-inflation tuning before it's fair across users.

## Roadmap

- Levels & XP (balanced + abuse-resistant)
- More locales and community themes (PRs welcome — a theme is ~20 lines of tokens in `worker/src/themes.ts`)
- Multi-user hosted mode, profile comparison
- Device-key signed batches (tamper-evident sync)

---

Built by [Augusto Bastos](https://github.com/augbastos) · MIT
