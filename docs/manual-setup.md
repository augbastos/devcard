# Manual setup

`python install.py` does all of this for you. These are the same steps by hand,
for when you want to see each one. Most of the installer's wall time is `npm ci`
and the first Cloudflare deploy.

## 1. Clone, install the toolchain, create your database

```bash
git clone https://github.com/augbastos/devcard
cd devcard/worker
npm ci                                 # the locked toolchain; install scripts are disabled in .npmrc
npx wrangler login
npx wrangler d1 create devcard         # note the database_id it prints
```

## 2. Write your deployment config

The repository tracks a template, `worker/wrangler.example.jsonc`, and ignores
`worker/wrangler.jsonc`. Your deployment's values go in the ignored file, so they
are never committed and `git pull` never conflicts with them:

```bash
cp wrangler.example.jsonc wrangler.jsonc
```

In `wrangler.jsonc`, replace three values:

| Key | Value |
|---|---|
| `database_id` | the id `wrangler d1 create` printed |
| `GITHUB_USERNAME` | your GitHub login — the card only renders for this name |
| `TIMEZONE` | an IANA zone such as `Europe/Lisbon`; it decides where a day starts on the heatmap |

Wrangler reads `wrangler.jsonc` from the `worker/` directory automatically.
When the template changes upstream, re-run `python install.py` or carry the
change across by hand.

```bash
npx wrangler d1 execute devcard --remote --file=schema.sql
npx wrangler deploy                    # note your URL: card.<your-subdomain>.workers.dev
```

## 3. Create your ingest token

```bash
python -c "import secrets; print(secrets.token_hex(24))"
npx wrangler secret put INGEST_TOKEN   # paste the token when prompted
```

Until this secret exists, `POST /ingest` answers `503` to everyone.

Give the hook the same token in one of two ways:

- **A file only your account can read** (what the installer does):
  `~/.claude/devcard/token`, containing the token and nothing else. On
  macOS/Linux, `chmod 600` it. On Windows, remove inherited permissions so only
  your account has access:
  ```powershell
  icacls "$HOME\.claude\devcard\token" /inheritance:r /grant:r "${env:USERDOMAIN}\${env:USERNAME}:F"
  ```
- **An environment variable**, `DEVCARD_INGEST_TOKEN`, which takes precedence
  over the file. It has to be visible to the process that runs Claude Code or
  git.

[Why a file and not the OS keychain →](privacy-and-security.md#where-the-token-lives)

## 4. Point the hook at your Worker

```bash
# macOS/Linux
echo "https://<your-worker-url>/ingest" > ~/.claude/devcard/worker-url
```

```powershell
# Windows
"https://<your-worker-url>/ingest" | Set-Content $HOME/.claude/devcard/worker-url
```

`DEVCARD_WORKER_URL` overrides the file. There is no default: an unconfigured
hook captures events locally and sends nothing.

## 5. Register the hook in Claude Code

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

And record the capture mode, so the git hook stays quiet on this machine:

```bash
echo claude > ~/.claude/devcard/mode
```

Restart Claude Code, write some code, and open
`https://<your-worker-url>/svg?user=<you>`. That's your card.

## Installing the git hook

For every tool other than Claude Code, capture comes from a git `post-commit`
hook. Write `git` to `~/.claude/devcard/mode`, then:

```bash
python hook/install_git_hook.py "C:/path/to/your projects"    # a repo, or a folder of repos
python hook/install_git_hook.py --uninstall "C:/path/to/your projects"
```

Each path is one argument, so spaces are fine. A path may be a repository or a
folder containing repositories (scanned one level deep, plus the folder itself).

Where the hook goes is asked of git
(`git rev-parse --git-path hooks/post-commit`) rather than assumed to be
`.git/hooks/`, which means it also works for:

- repos that set **`core.hooksPath`**;
- **worktrees and submodules**, where `.git` is a file, not a directory (a repo
  and its worktrees share one hooks directory, so it installs once);
- **husky** — its runnable hooks live in `.husky/_`, which husky regenerates and
  gitignores, so the line goes to `.husky/post-commit` where it survives the
  next `npm install`.

An existing hook is appended to, never overwritten, and installing twice is a
no-op. If the existing `post-commit` is **not** a shell script (a Python or Ruby
hook, say), the installer refuses to touch it and prints the line to add by hand
— appending `sh` to a Python file would have broken the hook that was already
there. `--uninstall` removes only devcard's line, and deletes the file only if
devcard was all it contained.

The hook line runs in the background, so a commit never waits on the network.

## Adding a second machine

Two machines can share one Worker. Do not run `install.py` on the second one: it
rotates the ingest token, and the first machine would then be refused on every
sync. Instead, on the second machine:

1. clone the repository;
2. copy `token` and `worker-url` from the first machine's `~/.claude/devcard/`,
   keeping the token file [owner-only](#3-create-your-ingest-token);
3. write that machine's capture mode to `~/.claude/devcard/mode`, and install
   its hook as in [step 5](#5-register-the-hook-in-claude-code) or
   [git mode](#installing-the-git-hook).

Each machine generates its own installation id on its first sync, so their
events never collide.

## Upgrading an existing deployment

Deployments set up before the template existed kept their values in a tracked
`worker/wrangler.toml`. Re-run `python install.py`: it finds the existing
database by name, renders `wrangler.jsonc`, redeploys and rotates the token.
Then delete `worker/wrangler.toml`: Wrangler takes the first of `wrangler.json`,
`wrangler.jsonc` and `wrangler.toml` it finds and ignores the rest without a
word, so a stale file only misleads whoever edits it next. Delete
`worker/.dev.vars` too if an earlier installer left the production token there.

If the D1 database predates event identity, apply the migration with the deploy:

```bash
npx wrangler d1 execute devcard --remote --file migrations/0001_event_source_id.sql
```
