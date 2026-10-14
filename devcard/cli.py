"""devcard — the command line.

    devcard init                         set up capture and the repository to publish to
    devcard render [--out DIR]           write this machine's card.svg and card-dark.svg
    devcard publish [--repo owner/name]  publish to the repo's `devcard-data` branch
    devcard status                       what is configured, and the README embed
"""
import argparse
import os
import shutil
import subprocess
import sys
import time

from . import __version__, config
from ._hook import hook_script, lib
from .publish import MIN_INTERVAL, PublishError, publish, render_local
from .render import LAYOUTS
from .strings import STRINGS
from .themes import THEMES

# The oldest Python the suites run on. install.py, pyproject.toml, CI and the
# README carry the same number; tests/test_cli.py holds them together.
MIN_PYTHON = (3, 11)

SETTINGS_PATH = os.path.normpath(os.path.expanduser("~/.claude/settings.json"))
MODE_PATH = os.path.normpath(os.path.expanduser("~/.claude/devcard/mode"))


def _run(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(cmd, 127, "", str(exc))


def _ask(prompt):
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        raise SystemExit(1) from None


class Init:
    """`devcard init`. Interactive by default; every question also has a flag."""

    def __init__(self, args, ask=_ask, run=_run, out=print):
        self.args, self.ask, self.run, self.out = args, ask, run, out

    def die(self, message):
        self.out(f"\n  ERROR: {message}")
        raise SystemExit(1)

    def checks(self):
        self.out("[1/5] Checking prerequisites...")
        if sys.version_info < MIN_PYTHON:
            self.die(f"Python {'.'.join(map(str, MIN_PYTHON))}+ required (running {sys.version.split()[0]})")
        if not shutil.which("git") or self.run(["git", "--version"]).returncode != 0:
            self.die("git not found on PATH — install git: https://git-scm.com")
        gh = shutil.which("gh")
        gh_ok = bool(gh) and self.run([gh, "auth", "status"]).returncode == 0
        self.out(f"  python {sys.version.split()[0]} · git · gh {'logged in' if gh_ok else 'NOT logged in'}")
        if not gh_ok and not self.args.remote:
            self.out("  publishing over HTTPS uses gh's login: run `gh auth login` (or pass --remote with a")
            self.out("  git URL your own credentials can push to, e.g. an SSH URL)")
        return gh if gh_ok else None

    def identity(self, gh, cfg):
        self.out("\n[2/5] Your card")
        user = self.args.user or cfg.get("github_user")
        if not user and gh:
            result = self.run([gh, "api", "user", "--jq", ".login"])
            user = result.stdout.strip() if result.returncode == 0 else ""
        if not self.args.user and not self.args.yes:
            user = self.ask(f"  GitHub username [{user}]: ") or user
        if not user or not config.USERNAME_RE.match(user):
            self.die(f"not a GitHub username: {user!r}")

        repo = self.args.repo or cfg.get("repo") or f"{user}/{user}"
        if not self.args.repo and not self.args.yes:
            self.out("  The card is committed to an orphan branch `devcard-data` of a PUBLIC repository")
            self.out("  you own. Your profile repository (owner/owner) is the usual choice.")
            repo = self.ask(f"  Repository (owner/name) [{repo}]: ") or repo
        if not config.REPO_RE.match(repo):
            self.die(f"not owner/name: {repo!r}")
        if gh:
            view = self.run([gh, "repo", "view", repo, "--json", "visibility", "--jq", ".visibility"])
            if view.returncode != 0 and not self.args.remote:
                self.die(f"{repo} was not found. Create it first (devcard never creates repositories), e.g.\n"
                         f"    gh repo create {repo} --public")
            if view.returncode == 0 and view.stdout.strip().upper() != "PUBLIC":
                self.out(f"  warning: {repo} is not public — raw.githubusercontent.com will not serve the card")
                self.out("  to anyone but you, so it will show as a broken image in other people's browsers.")
        return user, repo

    def capture(self):
        self.out("\n[3/5] Capture hook")
        mode = self.args.mode
        if not mode:
            current = ""
            try:
                with open(MODE_PATH, encoding="utf-8") as f:
                    current = f.read().strip()
            except OSError:
                pass
            self.out("  Pick ONE mode per machine — both together would count the same lines twice:")
            self.out("    1) claude — live, per edit, through a Claude Code hook")
            self.out("    2) git    — per commit, real diff stats; any tool that commits")
            default = {"claude": "1", "git": "2"}.get(current, "1")
            answer = default if self.args.yes else (self.ask(f"  Mode [1/2, default {default}]: ") or default)
            mode = {"1": "claude", "2": "git", "claude": "claude", "git": "git"}.get(answer)
        if mode not in ("claude", "git"):
            self.die("pick 1 (claude) or 2 (git)")

        if mode == "claude":
            # Beside devcard_lib, wherever _hook found it (site-packages or hook/).
            from install_claude_hook import register_claude_hook

            python = sys.executable.replace("\\", "/")
            capture = hook_script("devcard_capture.py").replace("\\", "/")
            try:
                status = register_claude_hook(SETTINGS_PATH, f'"{python}" "{capture}"')
            except (OSError, ValueError) as exc:
                self.die(f"could not update {SETTINGS_PATH}: {exc}")
            self.out(f"  Claude Code hook {status} in {SETTINGS_PATH}")
            if status != "unchanged":
                self.out("  (restart Claude Code to activate it)")
        else:
            import install_git_hook

            # Git hooks already no-op in Claude mode. Remove the Claude entry
            # here, so changing to git mode cannot leave both capturers active.
            if os.path.exists(SETTINGS_PATH):
                import json
                from install_claude_hook import write_atomic

                try:
                    with open(SETTINGS_PATH, encoding="utf-8") as f:
                        settings = json.load(f)
                    post = settings.get("hooks", {}).get("PostToolUse", [])
                    kept = []
                    for entry in post:
                        hooks = [h for h in entry.get("hooks", [])
                                 if "devcard_capture" not in str(h.get("command", ""))]
                        if hooks or not entry.get("hooks"):
                            kept.append({**entry, "hooks": hooks})
                    if kept != post:
                        settings["hooks"]["PostToolUse"] = kept
                        write_atomic(SETTINGS_PATH, json.dumps(settings, indent=2) + "\n")
                        self.out("  Claude Code capture hook removed (restart Claude Code to activate it)")
                except (OSError, ValueError, AttributeError, TypeError) as exc:
                    self.die(f"could not update {SETTINGS_PATH}: {exc}")

            folders = list(self.args.git_folder or [])
            if not folders and not self.args.yes:
                self.out("  Folders to look for git repositories in (one per line, blank to finish):")
                while True:
                    line = self.ask("    > ")
                    if not line:
                        break
                    folders.append(os.path.expanduser(line.strip('"').strip("'")))
            if folders:
                install_git_hook.main(folders)
            else:
                self.out("  No folders given. Later: devcard init --mode git --git-folder <folder>")
        os.makedirs(os.path.dirname(MODE_PATH), exist_ok=True)
        with open(MODE_PATH, "w", encoding="utf-8") as f:
            f.write(mode)
        return mode

    def main(self):
        cfg = config.load() or dict(config.DEFAULTS)
        gh = self.checks()
        user, repo = self.identity(gh, cfg)
        mode = self.capture()

        self.out("\n[4/5] Saving settings")
        cfg.update({"github_user": user, "repo": repo})
        for key in ("layout", "theme", "lang", "remote"):
            value = getattr(self.args, key, None)
            if value:
                cfg[key] = value
        config.save(cfg)
        self.out(f"  {lib.CONFIG_PATH}")
        if lib.WORKER_INGEST_URL:
            self.out("  note: this machine also syncs to a devcard Worker (legacy). It keeps doing so;")
            self.out("  remove ~/.claude/devcard/worker-url once the Worker card is retired.")

        self.out("\n[5/5] Publishing")
        publish_now = self.args.yes or (self.ask("  Publish the card now? [Y/n]: ").lower() not in ("n", "no"))
        if publish_now:
            try:
                status = publish(cfg, force=True)
                self.out(f"  {status}: {config.raw_url(repo, 'card.svg')}")
            except PublishError as exc:
                self.out(f"  not published yet: {exc}")
                self.out("  fix that, then run `devcard publish --force`")
        self.out("\n" + "=" * 66)
        self.out(f"  Capture: {mode} mode. The card republishes itself at most every")
        self.out(f"  {MIN_INTERVAL // 60} minutes while you work; GitHub's image cache adds a few more.")
        self.out("\n  Paste this into your README:\n")
        self.out(config.embed_html(repo))
        self.out("=" * 66)
        return 0


def _effective_config(args):
    cfg = config.load() or dict(config.DEFAULTS)
    for key in ("repo", "remote", "layout", "theme", "lang"):
        value = getattr(args, key, None)
        if value:
            cfg[key] = value
    if getattr(args, "user", None):
        cfg["github_user"] = args.user
    if not cfg.get("github_user") and cfg.get("repo"):
        cfg["github_user"] = cfg["repo"].split("/", 1)[0]
    return cfg


def cmd_render(args):
    cfg = _effective_config(args)
    if not cfg.get("github_user"):
        print("devcard render: no GitHub username — run `devcard init` or pass --user")
        return 1
    for path in render_local(cfg, args.out):
        print(path)
    print("(this machine only — `devcard publish` renders every machine's numbers together)")
    return 0


def cmd_publish(args):
    if args.when_due:
        from .publish import when_due

        when_due()
        return 0
    cfg = _effective_config(args)
    if cfg.get("repo") and not config.REPO_RE.match(cfg["repo"]):
        print(f"devcard publish: not owner/name: {cfg['repo']!r}")
        return 1
    try:
        status = publish(cfg, force=args.force)
    except PublishError as exc:
        print(f"devcard publish: {exc}")
        return 1
    if status == "skipped":
        print(f"skipped: published less than {MIN_INTERVAL // 60} minutes ago (--force to publish anyway)")
    elif status == "unchanged":
        print("unchanged: the branch already holds this card")
    else:
        print(f"published: {config.raw_url(cfg['repo'], 'card.svg')}")
    return 0


def cmd_status(_args):
    cfg = config.load()
    if not cfg:
        print("not configured — run `devcard init`")
        return 1
    state = {}
    try:
        import json

        with open(config.state_path(), encoding="utf-8") as f:
            state = json.load(f)
    except (OSError, ValueError):
        pass
    last = state.get("last_push")
    print(f"user     {cfg['github_user']}")
    print(f"repo     {cfg['repo']} (branch devcard-data)")
    print(f"card     {cfg['layout']} · {cfg['theme']} · {cfg['lang']}")
    print(f"machine  {lib.read_source_id() or '(no id yet)'}")
    print(f"pushed   {time.strftime('%Y-%m-%d %H:%M', time.localtime(last)) if last else 'never'}")
    print()
    print(config.embed_html(cfg["repo"]))
    return 0


def build_parser():
    parser = argparse.ArgumentParser(prog="devcard", description="A coding-activity card, published from your machine.")
    parser.add_argument("--version", action="version", version=f"devcard {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def card_options(p):
        p.add_argument("--layout", choices=LAYOUTS)
        p.add_argument("--theme", choices=sorted(THEMES))
        p.add_argument("--lang", choices=sorted(STRINGS))

    p = sub.add_parser("init", help="set up capture and the repository to publish to")
    p.add_argument("--user", help="GitHub username")
    p.add_argument("--repo", help="owner/name of the public repository to publish to")
    p.add_argument("--remote", help="git URL to push to instead of https://github.com/<repo>.git")
    p.add_argument("--mode", choices=("claude", "git"), help="capture mode for this machine")
    p.add_argument("--git-folder", action="append", help="(git mode) a repo or folder of repos; repeatable")
    p.add_argument("--yes", "-y", action="store_true", help="accept defaults and publish without asking")
    card_options(p)
    p.set_defaults(func=lambda a: Init(a).main())

    p = sub.add_parser("render", help="write this machine's card to a folder")
    p.add_argument("--out", default=".", help="output folder (default: current directory)")
    p.add_argument("--user", help="GitHub username, if `devcard init` has not run")
    card_options(p)
    p.set_defaults(func=cmd_render)

    p = sub.add_parser("publish", help="commit the card to the repository's devcard-data branch")
    p.add_argument("--repo", help="owner/name (default: the one `devcard init` saved)")
    p.add_argument("--remote", help="git URL to push to instead of https://github.com/<repo>.git")
    p.add_argument("--force", action="store_true", help=f"publish even if the last one was under {MIN_INTERVAL // 60} min ago")
    p.add_argument("--when-due", action="store_true", help=argparse.SUPPRESS)  # the hooks' trailing publish
    card_options(p)
    p.set_defaults(func=cmd_publish)

    p = sub.add_parser("status", help="show the configuration and the README embed")
    p.set_defaults(func=cmd_status)

    from .serve import DEFAULT_PORT, cmd_serve

    p = sub.add_parser("serve", help="open a read-only dashboard on localhost")
    p.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"local port (default: {DEFAULT_PORT})")
    p.set_defaults(func=cmd_serve)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
