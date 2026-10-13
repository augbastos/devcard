#!/usr/bin/env python3
"""Register devcard's capture hook in Claude Code's settings.json.

Used by both installers: `devcard init` (the serverless card) and install.py
(the legacy Worker). Kept beside the hook so a pipx install carries it.
"""
import json
import os
import shutil


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
