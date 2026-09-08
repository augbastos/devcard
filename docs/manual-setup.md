# Manual setup

`python setup.py` does all of this for you. These are the same steps by hand,
for when you want to see each one. Most of the wizard's wall time is `npm ci`
and the first Cloudflare deploy.

## 1. Clone and create your backend

```bash
git clone https://github.com/augbastos/devcard
cd devcard/worker
npm install
npx wrangler login
npx wrangler d1 create devcard        # copy the database_id it prints
```

Edit `worker/wrangler.toml`: paste **your** `database_id` and set
`GITHUB_USERNAME` to your GitHub login.

```bash
npx wrangler d1 execute devcard --remote --file=schema.sql
npx wrangler deploy                    # note your URL: card.<your-subdomain>.workers.dev
```

## 2. Create your ingest token

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

## 3. Point the hook at your Worker

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

## 4. Register the hook in Claude Code

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

Restart Claude Code, write some code, and open
`https://<your-worker-url>/svg?user=<you>`. That's your card.

## Installing the git hook

For every mode other than Claude Code, capture comes from a git `post-commit`
hook:

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
