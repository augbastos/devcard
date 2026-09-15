#!/usr/bin/env python3
"""devcard installer — from a fresh clone to a live card.

    python install.py

Creates your Cloudflare D1 database and applies the schema, renders your
deployment config from the tracked template, deploys the Worker, issues an
ingest token (a Worker secret, plus one owner-only local copy for the hooks),
wires ONE capture hook — Claude Code live mode, or git mode for any tool that
commits — smoke-tests ingest, and prints your embed.

Requires Python 3.11+, Node 22+ (the floor Wrangler sets), npm, git and a free
Cloudflare account. All of them are checked before anything is created in
your Cloudflare account.

Safe to re-run. The database is found rather than duplicated, the config is
re-rendered from the template (which is how template changes reach an existing
deployment), the hook entry is updated in place, and the token is rotated: the
Worker secret first, the local copy only once that succeeded.
"""
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
WORKER_DIR = os.path.join(ROOT, "worker")
TEMPLATE_PATH = os.path.join(WORKER_DIR, "wrangler.example.jsonc")
CONFIG_PATH = os.path.join(WORKER_DIR, "wrangler.jsonc")
PACKAGE_JSON = os.path.join(WORKER_DIR, "package.json")
WRANGLER_JS = os.path.join(WORKER_DIR, "node_modules", "wrangler", "bin", "wrangler.js")
DEVCARD_HOME = os.path.normpath(os.path.expanduser("~/.claude/devcard"))
SETTINGS_PATH = os.path.normpath(os.path.expanduser("~/.claude/settings.json"))

# The oldest Python CI runs the suites on (a test holds the two together).
# 3.10 reaches end of life in October 2026.
MIN_PYTHON = (3, 11)
TOTAL_STEPS = 8

USERNAME_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}")
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
TIMEZONE_RE = re.compile(r"[A-Za-z][A-Za-z0-9_+\-]*(?:/[A-Za-z0-9_+\-]+){0,2}")


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


def min_node(package_json=None):
    """The Node major the Worker toolchain requires, read from `engines.node`.

    package.json is the one place that number lives: CI's matrix floor and this
    check both follow it, so raising it is a one-line change.
    """
    path = PACKAGE_JSON if package_json is None else package_json
    try:
        with open(path, encoding="utf-8") as f:
            engines = json.load(f)["engines"]["node"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        die(f"could not read engines.node from {path}: {exc}")
    match = re.search(r"\d+", engines)
    if not match:
        die(f"engines.node in {path} names no version: {engines!r}")
    return int(match.group(0))


def check_node_version(node, floor=None):
    floor = min_node() if floor is None else floor
    result = run([node, "--version"])
    if result.returncode != 0:
        die(f"could not run node — install Node {floor}+: https://nodejs.org")
    match = re.match(r"v(\d+)\.", result.stdout.strip())
    if not match:
        die(f"could not read the node version from {result.stdout.strip()!r}")
    if int(match.group(1)) < floor:
        die(f"node {match.group(1)} is too old — devcard needs Node {floor}+ (found {result.stdout.strip()})")
    return result.stdout.strip()


def substitute(text, pattern, replacement, what):
    """Replace exactly one occurrence, or fail loudly.

    A silent no-op here used to leave the Worker pointed at somebody else's
    database, and nothing downstream noticed until the card was empty.
    """
    updated, count = re.subn(pattern, lambda _m: replacement, text, count=1)
    if count != 1:
        die(f"could not set {what} in the Wrangler config — expected one match, found {count}")
    return updated


def render_config(template, database_id, username, timezone):
    """The deployment config: the tracked template with three values filled in.

    Values are validated before they are written, then JSON-quoted, so nothing
    a prompt or a CLI printed can break out of its string.
    """
    if not UUID_RE.fullmatch(database_id):
        die(f"not a D1 database id: {database_id!r}")
    if not USERNAME_RE.fullmatch(username):
        die(f"not a GitHub username: {username!r}")
    if not TIMEZONE_RE.fullmatch(timezone):
        die(f"not an IANA timezone: {timezone!r}")
    for key, value in (("database_id", database_id), ("GITHUB_USERNAME", username), ("TIMEZONE", timezone)):
        template = substitute(template, rf'"{key}"\s*:\s*"[^"]*"', f'"{key}": {json.dumps(value)}', key)
    return template


def detect_timezone(node):
    """The machine's IANA zone as Node's ICU reports it, or UTC.

    Asked of Node rather than Python because the Worker computes days with the
    same `Intl` machinery, and because Python on Windows has no IANA database.
    """
    result = run([node, "-e", "process.stdout.write(Intl.DateTimeFormat().resolvedOptions().timeZone || '')"])
    zone = result.stdout.strip() if result.returncode == 0 else ""
    return zone if TIMEZONE_RE.fullmatch(zone or "") else "UTC"


def prepare_private(path, windows=None):
    """Make `path` exist and be readable by its owner alone, keeping any content.

    POSIX: created 0600 inside a 0700 directory, and tightened if it already
    existed. Windows ignores mode bits, so inherited permissions are replaced
    with full control for the current user, using the system's own `icacls`.
    If that cannot be done the installer stops: a secret is never written into
    a file it could not protect.
    """
    windows = os.name == "nt" if windows is None else windows
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    if windows:
        open(path, "a", encoding="utf-8").close()
        if not restrict_to_owner_windows(path):
            die(f"could not restrict {path} to your account, so no token was written to it")
        return
    try:
        os.chmod(directory, 0o700)
    except OSError:
        pass
    os.close(os.open(path, os.O_WRONLY | os.O_CREAT, 0o600))
    os.chmod(path, 0o600)  # O_CREAT leaves an existing file's old mode alone


def write_private(path, content, windows=None):
    """Write a secret into a file only its owner can read (see prepare_private)."""
    prepare_private(path, windows)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def restrict_to_owner_windows(path):
    """Drop inherited ACEs and grant the current user full control. Returns ok."""
    user = os.environ.get("USERNAME", "")
    domain = os.environ.get("USERDOMAIN", "")
    account = f"{domain}\\{user}" if domain else user
    icacls = shutil.which("icacls")
    if not (user and icacls):
        print("  no icacls on PATH, or no USERNAME in the environment")
        return False
    result = run([icacls, path, "/inheritance:r", "/grant:r", f"{account}:F"])
    if result.returncode != 0:
        print(f"  icacls failed: {result.stdout.strip() or result.stderr.strip()}")
        return False
    return True


def write_atomic(path, text):
    """Replace a file in one step, so a crash cannot leave it half-written."""
    tmp = f"{path}.devcard-tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(tmp, path)


def register_claude_hook(settings_path, command):
    """Add devcard's PostToolUse entry, or repoint the one already there.

    Updating in place matters on a re-run from a different place — a moved
    clone, a new Python: leaving the old entry would keep calling a path that
    no longer exists, and the hook fails silently by design.
    """
    settings = {}
    if os.path.exists(settings_path):
        backup = settings_path + ".devcard-backup"
        # Keep the FIRST backup: on a re-run the current file already contains
        # devcard's entry, so overwriting would destroy the only copy of the
        # settings from before devcard ever touched them.
        if not os.path.exists(backup):
            shutil.copy2(settings_path, backup)
        with open(settings_path, encoding="utf-8") as f:
            settings = json.load(f)

    post = settings.setdefault("hooks", {}).setdefault("PostToolUse", [])
    ours = [hook for entry in post for hook in entry.get("hooks", []) if "devcard_capture" in str(hook.get("command", ""))]
    if ours:
        if all(hook.get("command") == command for hook in ours):
            return "unchanged"
        for hook in ours:
            hook["command"] = command
        status = "updated"
    else:
        post.append({
            "matcher": "Edit|Write|Bash",
            "hooks": [{"type": "command", "command": command, "timeout": 3000}],
        })
        status = "registered"
    os.makedirs(os.path.dirname(settings_path), exist_ok=True)
    write_atomic(settings_path, json.dumps(settings, indent=2) + "\n")
    return status


def smoke_test(worker_url, token, timeout=10):
    """POST an empty batch: proves the route, the token and the Worker's JSON path.

    No `repo_count` on purpose — ingest would publish it, and a re-run would
    reset the live card's repository count to zero until the next sync.
    """
    req = urllib.request.Request(
        f"{worker_url}/ingest",
        data=json.dumps({"events": []}).encode(),
        headers={"Content-Type": "application/json", "X-Devcard-Token": token, "User-Agent": "devcard-hook/1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300, f"HTTP {resp.status}"
    except Exception as exc:  # any failure is reported, never raised
        return False, str(exc)


def wrangler(node, *args, **kwargs):
    """The pinned Wrangler from worker/node_modules, run by Node directly.

    Not `npx wrangler`, which may fetch whatever is newest today, and not the
    `.cmd` shim npm installs on Windows, which would put a batch file between
    this script and its arguments.
    """
    return run([node, WRANGLER_JS, *args], cwd=WORKER_DIR, **kwargs)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv:
        print(__doc__)
        return 0 if argv[0] in ("-h", "--help") else 2

    print("devcard install — from clone to live card.\n")

    # 1. prerequisites -----------------------------------------------------
    # Everything is checked BEFORE anything is created, so a missing tool
    # cannot leave a half-provisioned account behind.
    step(1, "Checking prerequisites...")
    if sys.version_info < MIN_PYTHON:
        die(f"Python {'.'.join(map(str, MIN_PYTHON))}+ required (running {sys.version.split()[0]})")
    node = which_or_die("node", "install Node LTS: https://nodejs.org")
    npm = which_or_die("npm", "it ships with Node: https://nodejs.org")
    git = which_or_die("git", "install git: https://git-scm.com")
    node_version = check_node_version(node)
    if run([git, "--version"]).returncode != 0:
        die("git is on PATH but would not run")
    if not os.path.exists(TEMPLATE_PATH):
        die(f"{TEMPLATE_PATH} is missing — run this from a complete clone")
    print(f"  python {sys.version.split()[0]} · node {node_version} · npm · git — ok")

    # The lockfile pins the toolchain; `npm ci` installs exactly that tree.
    # worker/.npmrc disables dependency install scripts for it.
    print("  running npm ci in worker/ (pinned toolchain)...")
    if run([npm, "ci"], cwd=WORKER_DIR, capture=False).returncode != 0:
        die(f"npm ci failed in {WORKER_DIR}")
    if not os.path.exists(WRANGLER_JS):
        die(f"npm ci finished but {WRANGLER_JS} does not exist")

    # 2. identity + mode ---------------------------------------------------
    step(2, "Your card")
    username = ask("  GitHub username: ")
    if not USERNAME_RE.fullmatch(username):
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

    timezone = detect_timezone(node)

    # 3. cloudflare auth ---------------------------------------------------
    step(3, "Cloudflare login...")
    # `--json`, because plain `whoami` exits 0 when logged out — it only prints
    # a hint — so a return-code check never opened the login.
    if wrangler(node, "whoami", "--json").returncode != 0:
        print("  Opening wrangler login (browser)...")
        if wrangler(node, "login", capture=False).returncode != 0:
            die("wrangler login failed")
    print("  ok")

    # 4. D1 database + config ---------------------------------------------
    step(4, "Creating D1 database 'devcard'...")
    created = wrangler(node, "d1", "create", "devcard")
    db_id = None
    match = re.search(r'"?database_id"?\s*[=:]\s*"([0-9a-f-]{36})"', created.stdout)
    if match:
        db_id = match.group(1)
    elif "already exists" in (created.stdout + created.stderr):
        listing = wrangler(node, "d1", "list", "--json")
        try:
            for db in json.loads(listing.stdout):
                if db.get("name") == "devcard":
                    db_id = db.get("uuid") or db.get("database_id")
        except (ValueError, TypeError):
            pass
    if not db_id:
        die(f"couldn't create or find the D1 database:\n{created.stdout}\n{created.stderr}")
    print(f"  database_id: {db_id}")

    # Rendered, not edited: the template stays tracked and generic, and your
    # deployment's values live in the gitignored wrangler.jsonc.
    with open(TEMPLATE_PATH, encoding="utf-8") as f:
        config = render_config(f.read(), db_id, username, timezone)
    write_atomic(CONFIG_PATH, config)
    print(f"  worker/wrangler.jsonc rendered (gitignored) · timezone {timezone}")

    schema = wrangler(node, "d1", "execute", "devcard", "--remote", "--file=schema.sql")
    if schema.returncode != 0:
        die(f"schema apply failed:\n{schema.stderr}")
    print("  schema applied")

    # 5. deploy ------------------------------------------------------------
    # Before the secret, so the secret is attached to a Worker that exists.
    # Until step 6 finishes, a fresh Worker has no secret and ingest answers
    # 503: it fails closed.
    step(5, "Deploying the Worker...")
    deploy = wrangler(node, "deploy")
    m = re.search(r"https://[^\s]+\.workers\.dev", deploy.stdout)
    if not m:
        print(deploy.stdout[-1500:])
        die("deploy didn't print a workers.dev URL. If this is your first Worker, register your\n"
            "workers.dev subdomain in the Cloudflare dashboard (Compute > Workers), then re-run.")
    worker_url = m.group(0)
    print(f"  live: {worker_url}")

    # 6. token -------------------------------------------------------------
    step(6, "Issuing the ingest token...")
    token = secrets.token_hex(24)
    token_path = os.path.join(DEVCARD_HOME, "token")
    # Protect the file BEFORE rotating the secret: if that is impossible the
    # installer stops while the Worker still accepts the existing local token.
    prepare_private(token_path)
    put = wrangler(node, "secret", "put", "INGEST_TOKEN", input_text=token)
    if put.returncode != 0:
        # The old token, if there is one, is still the one the Worker knows.
        # Overwriting the local copy now would break a working install.
        die(f"secret put failed (your existing token was left untouched):\n{put.stderr}")
    write_private(token_path, token)
    print("  stored as a Worker secret and in ~/.claude/devcard/token (owner-only)")

    # Local config next to the token and the mode, never a source edit.
    os.makedirs(DEVCARD_HOME, exist_ok=True)
    with open(os.path.join(DEVCARD_HOME, "worker-url"), "w", encoding="utf-8") as f:
        f.write(f"{worker_url}/ingest\n")

    # 7. capture hook ------------------------------------------------------
    step(7, f"Installing capture hook ({mode} mode)...")
    with open(os.path.join(DEVCARD_HOME, "mode"), "w", encoding="utf-8") as f:
        f.write(mode)

    if mode == "claude":
        capture = os.path.join(ROOT, "hook", "devcard_capture.py").replace("\\", "/")
        python = sys.executable.replace("\\", "/")
        status = register_claude_hook(SETTINGS_PATH, f'"{python}" "{capture}"')
        print(f"  Claude Code hook {status} in {SETTINGS_PATH}")
        if status != "unchanged":
            print("  (first backup kept as settings.json.devcard-backup — restart Claude Code to activate)")
    else:
        print("  Point me at your code. I'll install a post-commit hook in every git repo found")
        print("  (appended safely — existing hooks like husky keep working).")
        folders = ask_folders()
        if folders:
            run([sys.executable, os.path.join(ROOT, "hook", "install_git_hook.py"), *folders], capture=False)
        else:
            print("  Skipped. Later: python hook/install_git_hook.py <folder>")

    # 8. smoke test --------------------------------------------------------
    step(8, "Smoke test...")
    ok, detail = smoke_test(worker_url, token)
    if ok:
        print("  ingest reachable and token accepted")
    else:
        print(f"  warning: smoke test failed ({detail}) — a new secret can take a few seconds; re-run if it persists")

    print("\n" + "=" * 62)
    print("  Your card is live:")
    print(f"    {worker_url}/svg?user={username}")
    print("\n  Embed it anywhere:")
    print(f'    <img src="{worker_url}/svg?user={username}" alt="devcard" />')
    print("=" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main())
