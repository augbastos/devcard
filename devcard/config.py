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

CONSENT_CATEGORIES = {
    "languages": "Language bar and percentages (line counts only with totals consent).",
    "activity": "Daily heatmap, lines per day, streak and last update time.",
    "totals": "Lines/bytes written, first event timestamp (tracking start) and event counts/types.",
    "repo_count": "Number of public repositories owned on GitHub.",
    "agents": "Per-agent totals and estimated active minutes, including daily agent buckets.",
    "usage": "Daily token totals and API-equivalent cost estimates by agent/model family.",
    "repo_count_private": "Include private repositories in the repository count.",
}
NO_CONSENT = dict.fromkeys(CONSENT_CATEGORIES, False)
FULL_CONSENT = dict.fromkeys(CONSENT_CATEGORIES, True)


def consents(cfg):
    """Only literal true authorizes a category; missing/malformed values deny."""
    saved = cfg.get("consent") if isinstance(cfg, dict) else None
    saved = saved if isinstance(saved, dict) else {}
    return {key: saved.get(key) is True for key in CONSENT_CATEGORIES}


def has_consent(cfg):
    return any(value for key, value in consents(cfg).items() if key != "repo_count_private")

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
    "readme_hover": False,  # daily README language tooltips; also requires languages consent
    "card": {"show_agents": False, "show_usage": False},
    "badges": [],        # [{"kind": "badge|certification|award", "label": "..."}]
    "pins": [],          # [{"repo": "name", "note": "..."}]
    "consent": NO_CONSENT,
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
    cfg = {**DEFAULTS, **{k: v for k, v in saved.items() if k in DEFAULTS}}
    cfg["consent"] = consents(saved)
    return cfg


def save(cfg):
    os.makedirs(os.path.dirname(lib.CONFIG_PATH), exist_ok=True)
    tmp = lib.CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump({**{k: cfg.get(k, v) for k, v in DEFAULTS.items()}, "consent": consents(cfg)}, f, indent=2)
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
