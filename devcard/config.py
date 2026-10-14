"""Local settings for the serverless card. Nothing here is secret, and none of it leaves the machine.

`config.json` lives next to the hook's database (~/.claude/devcard/) because
the hooks read it too: its presence is what tells them to publish instead of
syncing to a Worker. Paths are read from the modules at call time so tests can
redirect them — see the rules for tests in CLAUDE.md.
"""
import json
import os
import re

from ._hook import lib

HOME = os.path.normpath(os.path.expanduser("~/.claude/devcard"))

REPO_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$")
USERNAME_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$")

DEFAULTS = {
    "github_user": "",
    "repo": "",          # owner/name of the public repository the card is published to
    "remote": "",        # optional git URL override (SSH, a mirror); default is GitHub over HTTPS
    "layout": "full",
    "theme": "default",
    "lang": "en",
    "timezone": "",      # IANA zone for day boundaries; empty means this machine's local time
    "avatar": True,      # embed the GitHub avatar (fetched from github.com, cached a day)
    "usage": True,       # incremental, offline transcript scan before reading local data
    "card": {"show_agents": False, "show_usage": False},
    "badges": [],        # [{"kind": "badge|certification|award", "label": "..."}]
    "pins": [],          # [{"repo": "name", "note": "..."}]
}


def publish_dir():
    return os.path.join(HOME, "publish")


def state_path():
    return os.path.join(HOME, "publish-state.json")


def avatar_cache_path():
    return os.path.join(HOME, "avatar.json")


def lock_path():
    return os.path.join(HOME, "publish.lock")


def pending_path():
    return os.path.join(HOME, "publish-pending")


def load():
    """The saved config merged over the defaults, or None when there is none."""
    try:
        with open(lib.CONFIG_PATH, encoding="utf-8") as f:
            saved = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(saved, dict):
        return None
    return {**DEFAULTS, **{k: v for k, v in saved.items() if k in DEFAULTS}}


def save(cfg):
    os.makedirs(os.path.dirname(lib.CONFIG_PATH), exist_ok=True)
    tmp = lib.CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump({k: cfg.get(k, v) for k, v in DEFAULTS.items()}, f, indent=2)
        f.write("\n")
    os.replace(tmp, lib.CONFIG_PATH)


def remote_url(cfg):
    return cfg.get("remote") or f"https://github.com/{cfg['repo']}.git"


def raw_url(repo, name):
    return f"https://raw.githubusercontent.com/{repo}/devcard-data/{name}"


def embed_html(repo, alt="devcard"):
    """The README snippet: GitHub picks the file matching the viewer's theme."""
    return (
        "<picture>\n"
        f'  <source media="(prefers-color-scheme: dark)" srcset="{raw_url(repo, "card-dark.svg")}">\n'
        f'  <img alt="{alt}" src="{raw_url(repo, "card.svg")}">\n'
        "</picture>"
    )
