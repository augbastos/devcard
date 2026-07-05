#!/usr/bin/env python3
"""devcard one-command setup.

    python setup.py

Walks you from a fresh clone to a live card: creates your Cloudflare D1
database, applies the schema, generates and stores your ingest token,
deploys the Worker, wires the capture hook (Claude Code live mode OR
universal git mode for Codex/local models/anything), and prints your
embed snippet. Requires: Python 3, Node 18+, git, a free Cloudflare account.
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
LIB_PATH = os.path.join(ROOT, "hook", "devcard_lib.py")
DEVCARD_HOME = os.path.normpath(os.path.expanduser("~/.claude/devcard"))
SETTINGS_PATH = os.path.normpath(os.path.expanduser("~/.claude/settings.json"))
NPX = shutil.which("npx") or "npx"


def run(cmd, cwd=None, capture=True, input_text=None):
    return subprocess.run(
        cmd, cwd=cwd, capture_output=capture, text=True, input=input_text, shell=False
    )


def die(msg):
    print(f"\n  ERROR: {msg}")
    sys.exit(1)


def step(n, msg):
    print(f"\n[{n}/8] {msg}")


def main():
    print("devcard setup — from clone to live card.\n")

    # 1. prerequisites -----------------------------------------------------
    step(1, "Checking prerequisites (node, git)...")
    if run([NPX, "--version"]).returncode != 0:
        die("npx not found — install Node 18+ first: https://nodejs.org")
    if run(["git", "--version"]).returncode != 0:
        die("git not found")
    print("  ok")

    # 2. identity + mode ---------------------------------------------------
    step(2, "Your card")
    username = input("  GitHub username: ").strip()
    if not re.fullmatch(r"[A-Za-z0-9-]{1,39}", username):
        die("that doesn't look like a GitHub username")

    print("\n  Capture mode (pick ONE — both together would double-count):")
    print("    1) claude — live per-edit capture via Claude Code hook")
    print("    2) git    — per-commit capture, works with Codex, local models, anything")
    mode = {"1": "claude", "2": "git"}.get(input("  Mode [1/2]: ").strip())
    if not mode:
        die("pick 1 or 2")

    # 3. cloudflare auth ---------------------------------------------------
    step(3, "Cloudflare login...")
    if run([NPX, "wrangler", "whoami"], cwd=WORKER_DIR).returncode != 0:
        print("  Opening wrangler login (browser)...")
        if run([NPX, "wrangler", "login"], cwd=WORKER_DIR, capture=False).returncode != 0:
            die("wrangler login failed")
    print("  ok")

    # 4. D1 database -------------------------------------------------------
    step(4, "Creating D1 database 'devcard'...")
    created = run([NPX, "wrangler", "d1", "create", "devcard"], cwd=WORKER_DIR)
    db_id = None
    match = re.search(r'"?database_id"?\s*[=:]\s*"([0-9a-f-]{36})"', created.stdout)
    if match:
        db_id = match.group(1)
    elif "already exists" in (created.stdout + created.stderr):
        listing = run([NPX, "wrangler", "d1", "list", "--json"], cwd=WORKER_DIR)
        try:
            for db in json.loads(listing.stdout):
                if db.get("name") == "devcard":
                    db_id = db.get("uuid") or db.get("database_id")
        except (ValueError, TypeError):
            pass
    if not db_id:
        die(f"couldn't create or find the D1 database:\n{created.stdout}\n{created.stderr}")
    print(f"  database_id: {db_id}")

    toml_path = os.path.join(WORKER_DIR, "wrangler.toml")
    with open(toml_path, encoding="utf-8") as f:
        toml = f.read()
    toml = re.sub(r'database_id\s*=\s*"[^"]*"', f'database_id = "{db_id}"', toml)
    toml = re.sub(r'GITHUB_USERNAME\s*=\s*"[^"]*"', f'GITHUB_USERNAME = "{username}"', toml)
    with open(toml_path, "w", encoding="utf-8") as f:
        f.write(toml)

    schema = run([NPX, "wrangler", "d1", "execute", "devcard", "--remote", "--file=schema.sql"], cwd=WORKER_DIR)
    if schema.returncode != 0:
        die(f"schema apply failed:\n{schema.stderr}")
    print("  schema applied")

    # 5. token -------------------------------------------------------------
    step(5, "Generating ingest token...")
    token = secrets.token_hex(24)
    put = run([NPX, "wrangler", "secret", "put", "INGEST_TOKEN"], cwd=WORKER_DIR, input_text=token)
    if put.returncode != 0:
        die(f"secret put failed:\n{put.stderr}")
    with open(os.path.join(WORKER_DIR, ".dev.vars"), "w", encoding="utf-8") as f:
        f.write(f"INGEST_TOKEN={token}")
    os.makedirs(DEVCARD_HOME, exist_ok=True)
    with open(os.path.join(DEVCARD_HOME, "token"), "w", encoding="utf-8") as f:
        f.write(token)
    print("  stored (wrangler secret + ~/.claude/devcard/token — hooks read the file directly)")

    # 6. deploy ------------------------------------------------------------
    step(6, "Deploying the Worker...")
    deploy = run([NPX, "wrangler", "deploy"], cwd=WORKER_DIR)
    m = re.search(r"https://[^\s]+\.workers\.dev", deploy.stdout)
    if not m:
        print(deploy.stdout[-1500:])
        die("deploy didn't print a workers.dev URL. If this is your first Worker, register your\n"
            "workers.dev subdomain in the Cloudflare dashboard (Compute > Workers), then re-run setup.")
    worker_url = m.group(0)
    print(f"  live: {worker_url}")

    with open(LIB_PATH, encoding="utf-8") as f:
        lib_src = f.read()
    lib_src = re.sub(r'WORKER_INGEST_URL = "[^"]*"', f'WORKER_INGEST_URL = "{worker_url}/ingest"', lib_src)
    with open(LIB_PATH, "w", encoding="utf-8") as f:
        f.write(lib_src)

    # 7. capture hook ------------------------------------------------------
    step(7, f"Installing capture hook ({mode} mode)...")
    os.makedirs(DEVCARD_HOME, exist_ok=True)
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
            shutil.copy2(SETTINGS_PATH, SETTINGS_PATH + ".devcard-backup")
            with open(SETTINGS_PATH, encoding="utf-8") as f:
                settings = json.load(f)
        hooks = settings.setdefault("hooks", {})
        post = hooks.setdefault("PostToolUse", [])
        if not any("devcard_capture" in json.dumps(h) for h in post):
            post.append(entry)
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
        print(f"  Claude Code hook registered in {SETTINGS_PATH}")
        print("  (backup saved as settings.json.devcard-backup — restart Claude Code to activate)")
    else:
        print("  Point me at your code. I'll install a post-commit hook in every git repo found")
        print("  (appended safely — existing hooks like husky keep working).")
        paths = input("  Folder(s) with your repos (space-separated): ").strip()
        if paths:
            installer = os.path.join(ROOT, "hook", "install_git_hook.py")
            run([sys.executable, installer, *paths.split()], capture=False)
        else:
            print("  Skipped. Later: python hook/install_git_hook.py <folder>")

    # 8. done --------------------------------------------------------------
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
        print("  pipeline verified end to end")

    print("\n" + "=" * 62)
    print("  Your card is live:")
    print(f"    {worker_url}/svg?user={username}")
    print("\n  Embed it anywhere:")
    print(f'    <img src="{worker_url}/svg?user={username}" alt="devcard" />')
    print("=" * 62)


if __name__ == "__main__":
    main()
