# devcard

**A live, embeddable dev stats card — powered by your real AI-assisted coding activity, not your keystrokes.**

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

## Deploy your own

You need: Python 3, Node 18+, a free [Cloudflare account](https://dash.cloudflare.com/sign-up), and [Claude Code](https://claude.com/claude-code).

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

### 5. Embed it

```html
<img src="https://<your-worker-url>/svg?user=<you>" alt="devcard" />
```

For your GitHub profile: create a repo named exactly like your username, and paste that line into its README.

## Badges, certifications, awards

Manual, self-declared entries rendered as pills with icons (star = badge, seal = certification, trophy = award):

```bash
cd worker
npx wrangler d1 execute devcard --remote --command \
  "INSERT INTO profile_entries (kind, label, detail, created_at) VALUES ('certification', 'AWS Cloud Practitioner', NULL, strftime('%s','now'))"
```

`kind` is one of `badge` | `certification` | `award`.

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

## Known limits (v1)

- Single-user per deployment (your card, your Worker).
- Line counts for edits are approximate (counts edited regions, not a semantic diff).
- Inside `<img>`, SVG links aren't clickable (browser limitation — same as every stats card). Open the card URL directly for clickable repos/Sponsor.
- Levels/XP system exists in the data model but is intentionally not rendered yet — it needs anti-inflation tuning before it's fair across users.

## Roadmap

- Levels & XP (balanced + abuse-resistant), streak mechanics
- More locales, themes, layout variants
- Multi-user hosted mode, profile comparison
- Support for more AI coding agents

---

Built by [Augusto Bastos](https://github.com/augbastos) · MIT
