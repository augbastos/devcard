#!/usr/bin/env python3
"""devcard one-command setup.

    python setup.py

Walks you from a fresh clone to a live card: creates your Cloudflare D1
database, applies the schema, generates and stores your ingest token,
deploys the Worker, wires the capture hook (Claude Code live mode OR
universal git mode for Codex/local models/anything), and prints your
embed snippet.

Requires: Python 3.9+, Node 18+, npm, git, a free Cloudflare account.

Safe to re-run: every step checks what is already there before changing it,
and nothing destructive happens before the prerequisites have been verified.
"""
import json
import os
import re
import secrets
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
WORKER_DIR = os.path.join(ROOT, "worker")
DEVCARD_HOME = os.path.normpath(os.path.expanduser("~/.claude/devcard"))
SETTINGS_PATH = os.path.normpath(os.path.expanduser("~/.claude/settings.json"))

# 3.9 is the floor because it is the oldest version CI actually runs the suite
# on. Claiming more than that would be a guess.
MIN_PYTHON = (3, 9)
MIN_NODE = 18
TOTAL_STEPS = 8


def run(cmd, cwd=None, capture=True, input_text=None):
    """Run a command as an argv list — never through a shell.

    `shell=False` is the reason a path containing a space, an ampersand or a
    quote is just a string here rather than something the shell reinterprets.
    """
    try:
        return subprocess.run(
            cmd, cwd=cwd, capture_output=capture, text=True, input=input_text,
            shell=False, errors="replace",
        )
    except OSError as exc:
        return subprocess.CompletedProcess(cmd, 127, "", str(exc))


def die(msg):
    print(f"\n  ERROR: {msg}")
    sys.exit(1)


def step(n, msg):
    print(f"\n[{n}/{TOTAL_STEPS}] {msg}")


def ask(prompt):
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        die("cancelled")


def ask_folders():
    """Collect folders one per line.

    Splitting a single answer on whitespace broke every path with a space in
    it — `C:\\My Projects\\api` became two nonexistent folders — and quoting
    rules differ per shell. One line each has no parsing at all.
    """
    print("  Enter one folder per line (blank line when done):")
    folders = []
    while True:
        line = ask("    > ")
        if not line:
            return folders
        path = os.path.expanduser(line.strip('"').strip("'"))
        if os.path.isdir(path):
            folders.append(path)
        else:
            print(f"    not a folder: {path}")


def which_or_die(name, hint):
    found = shutil.which(name)
    if not found:
        die(f"{name} not found on PATH — {hint}")
    return found


def check_node_version(node):
    result = run([node, "--version"])
    if result.returncode != 0:
        die("could not run node — install Node 18+: https://nodejs.org")
    match = re.match(r"v(\d+)\.", result.stdout.strip())
    if not match:
        die(f"could not read the node version from {result.stdout.strip()!r}")
    major = int(match.group(1))
    if major < MIN_NODE:
        die(f"node {major} is too old — devcard needs Node {MIN_NODE}+ (found {result.stdout.strip()})")
    return result.stdout.strip()


def substitute(text, pattern, replacement, what):
    """Replace exactly one occurrence, or fail loudly.

    A silent no-op here used to leave the worker pointed at somebody else's
    database, and nothing downstream noticed until the card was empty.
    """
    updated, count = re.subn(pattern, lambda _m: replacement, text, count=1)
    if count != 1:
        die(f"could not set {what} in wrangler.toml — expected one match, found {count}")
    return updated


def write_private(path, content):
    """Write a secret to disk with owner-only permissions where that means
    something. On Windows the file's ACL is what protects it; POSIX modes are
    ignored there, so setting them would only be theatre."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    if os.name != "nt":
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass


def main():
    print("devcard setup — from clone to live card.\n")

    # 1. prerequisites -----------------------------------------------------
    # Everything is checked BEFORE anything is created, so a missing tool
    # cannot leave a half-provisioned account behind.
    step(1, "Checking prerequisites...")
    if sys.version_info < MIN_PYTHON:
        die(f"Python {'.'.join(map(str, MIN_PYTHON))}+ required (running {sys.version.split()[0]})")
    node = which_or_die("node", "install Node 18+: https://nodejs.org")
    npm = which_or_die("npm", "it ships with Node: https://nodejs.org")
    npx = which_or_die("npx", "it ships with Node: https://nodejs.org")
    git = which_or_die("git", "install git: https://git-scm.com")
    node_version = check_node_version(node)
    if run([git, "--version"]).returncode != 0:
        die("git is on PATH but would not run")
    print(f"  python {sys.version.split()[0]} · node {node_version} · npm · git — ok")

    # Install the pinned dependency tree before anything calls wrangler. Left
    # to itself, `npx wrangler` fetches whatever version is newest today,
    # which is how two people running the same setup got two different CLIs.
    lock = os.path.join(WORKER_DIR, "package-lock.json")
    installer = [npm, "ci"] if os.path.exists(lock) else [npm, "install"]
    print(f"  running {' '.join(installer)} in worker/ (pinned toolchain)...")
    deps = run(installer, cwd=WORKER_DIR, capture=False)
    if deps.returncode != 0:
        die(f"{' '.join(installer)} failed in {WORKER_DIR}")

    # 2. identity + mode ---------------------------------------------------
    step(2, "Your card")
    username = ask("  GitHub username: ")
    if not re.fullmatch(r"[A-Za-z0-9-]{1,39}", username):
        die("that doesn't look like a GitHub username")

    print("\n  Capture mode (pick ONE — both together would double-count):")
    print("    1) claude — live per-edit capture via Claude Code hook")
    print("    2) git    — per-commit capture, works with Codex, local models, anything")
    mode = {"1": "claude", "2": "git"}.get(ask("  Mode [1/2]: "))
    if not mode:
        die("pick 1 or 2")

    if mode == "claude" and os.path.exists(SETTINGS_PATH):
        # Parsed now, not at step 7: discovering that settings.json is corrupt
        # after the database and the Worker exist is a worse place to stop.
        try:
            with open(SETTINGS_PATH, encoding="utf-8") as f:
                json.load(f)
        except (OSError, ValueError) as exc:
            die(f"{SETTINGS_PATH} is not readable JSON ({exc}) — fix it first, nothing was changed")

    # 3. cloudflare auth ---------------------------------------------------
    step(3, "Cloudflare login...")
    if run([npx, "wrangler", "whoami"], cwd=WORKER_DIR).returncode != 0:
        print("  Opening wrangler login (browser)...")
        if run([npx, "wrangler", "login"], cwd=WORKER_DIR, capture=False).returncode != 0:
            die("wrangler login failed")
    print("  ok")

    # 4. D1 database -------------------------------------------------------
    step(4, "Creating D1 database 'devcard'...")
    created = run([npx, "wrangler", "d1", "create", "devcard"], cwd=WORKER_DIR)
    db_id = None
    match = re.search(r'"?database_id"?\s*[=:]\s*"([0-9a-f-]{36})"', created.stdout)
    if match:
        db_id = match.group(1)
    elif "already exists" in (created.stdout + created.stderr):
        listing = run([npx, "wrangler", "d1", "list", "--json"], cwd=WORKER_DIR)
        try:
            for db in json.loads(listing.stdout):
                if db.get("name") == "devcard":
                    db_id = db.get("uuid") or db.get("database_id")
        except (ValueError, TypeError):
            pass
    if not db_id:
        die(f"couldn't create or find the D1 database:\n{created.stdout}\n{created.stderr}")
    print(f"  database_id: {db_id}")

    # wrangler.toml is your fork's deployment config — the database it talks to
    # and the account it renders for. It is tracked on purpose, and this edit is
    # meant to be committed in your fork. (The hook's worker URL is NOT written
    # into source; it goes to ~/.claude/devcard/worker-url in step 6.)
    toml_path = os.path.join(WORKER_DIR, "wrangler.toml")
    try:
        with open(toml_path, encoding="utf-8") as f:
            toml = f.read()
    except OSError as exc:
        die(f"could not read {toml_path}: {exc}")
    toml = substitute(toml, r'database_id\s*=\s*"[^"]*"', f'database_id = "{db_id}"', "database_id")
    toml = substitute(
        toml, r'GITHUB_USERNAME\s*=\s*"[^"]*"', f'GITHUB_USERNAME = "{username}"', "GITHUB_USERNAME"
    )
    with open(toml_path, "w", encoding="utf-8") as f:
        f.write(toml)
    print("  wrangler.toml updated (your fork's deployment config — commit it)")

    schema = run(
        [npx, "wrangler", "d1", "execute", "devcard", "--remote", "--file=schema.sql"], cwd=WORKER_DIR
    )
    if schema.returncode != 0:
        die(f"schema apply failed:\n{schema.stderr}")
    print("  schema applied")

    # 5. token -------------------------------------------------------------
    step(5, "Generating ingest token...")
    token_path = os.path.join(DEVCARD_HOME, "token")
    token = secrets.token_hex(24)
    put = run([npx, "wrangler", "secret", "put", "INGEST_TOKEN"], cwd=WORKER_DIR, input_text=token)
    if put.returncode != 0:
        # The old token, if there is one, is still the one the Worker knows.
        # Overwriting the local copy now would break a working install.
        die(f"secret put failed (your existing token was left untouched):\n{put.stderr}")
    write_private(os.path.join(WORKER_DIR, ".dev.vars"), f"INGEST_TOKEN={token}\n")
    write_private(token_path, token)
    print("  stored (wrangler secret + ~/.claude/devcard/token — hooks read the file directly)")

    # 6. deploy ------------------------------------------------------------
    step(6, "Deploying the Worker...")
    deploy = run([npx, "wrangler", "deploy"], cwd=WORKER_DIR)
    m = re.search(r"https://[^\s]+\.workers\.dev", deploy.stdout)
    if not m:
        print(deploy.stdout[-1500:])
        die("deploy didn't print a workers.dev URL. If this is your first Worker, register your\n"
            "workers.dev subdomain in the Cloudflare dashboard (Compute > Workers), then re-run setup.")
    worker_url = m.group(0)
    print(f"  live: {worker_url}")

    # Local config, not a source edit: `git status` after a clone + setup stays
    # clean apart from wrangler.toml.
    os.makedirs(DEVCARD_HOME, exist_ok=True)
    with open(os.path.join(DEVCARD_HOME, "worker-url"), "w", encoding="utf-8") as f:
        f.write(f"{worker_url}/ingest\n")
    print("  hook pointed at it via ~/.claude/devcard/worker-url")

    # 7. capture hook ------------------------------------------------------
    step(7, f"Installing capture hook ({mode} mode)...")
    with open(os.path.join(DEVCARD_HOME, "mode"), "w", encoding="utf-8") as f:
        f.write(mode)

    if mode == "claude":
        capture = os.path.join(ROOT, "hook", "devcard_capture.py").replace("\\", "/")
        python = sys.executable.replace("\\", "/")
        entry = {
            "matcher": "Edit|Write|Bash",
            "hooks": [{"type": "command", "command": f'"{python}" "{capture}"', "timeout": 3000}],
        }
        settings = {}
        if os.path.exists(SETTINGS_PATH):
            backup = SETTINGS_PATH + ".devcard-backup"
            # Keep the FIRST backup: on a re-run the current file already
            # contains devcard's entry, so overwriting would destroy the only
            # copy of the settings from before devcard ever touched them.
            if not os.path.exists(backup):
                shutil.copy2(SETTINGS_PATH, backup)
            with open(SETTINGS_PATH, encoding="utf-8") as f:
                settings = json.load(f)
        hooks = settings.setdefault("hooks", {})
        post = hooks.setdefault("PostToolUse", [])
        if any("devcard_capture" in json.dumps(h) for h in post):
            print("  Claude Code hook was already registered — left as it is")
        else:
            post.append(entry)
            with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
                json.dump(settings, f, indent=2)
            print(f"  Claude Code hook registered in {SETTINGS_PATH}")
            print("  (backup saved as settings.json.devcard-backup — restart Claude Code to activate)")
    else:
        print("  Point me at your code. I'll install a post-commit hook in every git repo found")
        print("  (appended safely — existing hooks like husky keep working).")
        folders = ask_folders()
        if folders:
            installer_script = os.path.join(ROOT, "hook", "install_git_hook.py")
            run([sys.executable, installer_script, *folders], capture=False)
        else:
            print("  Skipped. Later: python hook/install_git_hook.py <folder>")

    # 8. smoke test --------------------------------------------------------
    step(8, "Smoke test...")
    import urllib.request

    req = urllib.request.Request(
        f"{worker_url}/ingest",
        data=json.dumps({"events": [], "repo_count": 0}).encode(),
        headers={"Content-Type": "application/json", "X-Devcard-Token": token, "User-Agent": "devcard-hook/1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            ok = 200 <= resp.status < 300
    except Exception as exc:
        ok = False
        print(f"  warning: smoke test failed ({exc}) — check the steps above")
    if ok:
        print("  ingest reachable and token accepted")

    print("\n" + "=" * 62)
    print("  Your card is live:")
    print(f"    {worker_url}/svg?user={username}")
    print("\n  Embed it anywhere:")
    print(f'    <img src="{worker_url}/svg?user={username}" alt="devcard" />')
    print("=" * 62)


if __name__ == "__main__":
    main()
