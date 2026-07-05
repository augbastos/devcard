#!/usr/bin/env python3
"""devcard git post-commit hook — agent-agnostic capture.

Runs after every `git commit` in a repo where it's installed. Reads the real
diff stats of the commit (git numstat) and records one event per language
plus one commit event, into the same local SQLite + sync pipeline the
Claude Code hook uses. Works with any coding agent (Codex, local models,
Cursor, plain typing) because it hooks git itself, not the agent.

Never blocks or fails a commit: every error is swallowed and logged.
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import devcard_lib as lib

MODE_PATH = os.path.normpath(os.path.expanduser("~/.claude/devcard/mode"))


def capture_mode():
    try:
        with open(MODE_PATH, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return None


def numstat_for_head(repo_dir):
    """Return list of (added, removed, path) for HEAD's diff. Handles the first commit."""
    base = ["git", "-C", repo_dir]
    has_parent = (
        subprocess.run(base + ["rev-parse", "--verify", "-q", "HEAD~1"], capture_output=True).returncode == 0
    )
    if has_parent:
        cmd = base + ["diff", "--numstat", "HEAD~1", "HEAD"]
    else:
        cmd = base + ["diff-tree", "--numstat", "--root", "--no-commit-id", "HEAD"]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    rows = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        added, removed, path = parts
        if added == "-" or removed == "-":
            continue  # binary file
        rows.append((int(added), int(removed), path))
    return rows


def added_bytes_per_language(repo_dir, has_parent):
    """Sum the byte length of added lines in HEAD's diff, grouped by language."""
    base = ["git", "-C", repo_dir]
    if has_parent:
        cmd = base + ["diff", "--unified=0", "HEAD~1", "HEAD"]
    else:
        cmd = base + ["diff-tree", "-p", "--unified=0", "--root", "--no-commit-id", "HEAD"]
    out = subprocess.run(cmd, capture_output=True, text=True, errors="replace").stdout
    per_lang = {}
    current_lang = None
    for line in out.splitlines():
        if line.startswith("+++ b/"):
            current_lang = lib.language_for_path(line[6:])
        elif line.startswith("+") and not line.startswith("+++") and current_lang:
            per_lang[current_lang] = per_lang.get(current_lang, 0) + len(line[1:].encode("utf-8"))
    return per_lang


def main():
    try:
        # A machine in "claude" mode captures edits live; recording the commit
        # diff too would double-count the same lines.
        if capture_mode() == "claude":
            return

        repo_dir = os.getcwd()
        top = subprocess.run(
            ["git", "-C", repo_dir, "rev-parse", "--show-toplevel"], capture_output=True, text=True
        )
        if top.returncode != 0:
            return
        project_key = top.stdout.strip()

        import time

        now = int(time.time())
        per_language = {}
        for added, removed, path in numstat_for_head(project_key):
            language = lib.language_for_path(path)
            if not language:
                continue
            la, lr = per_language.get(language, (0, 0))
            per_language[language] = (la + added, lr + removed)

        has_parent = (
            subprocess.run(
                ["git", "-C", project_key, "rev-parse", "--verify", "-q", "HEAD~1"], capture_output=True
            ).returncode == 0
        )
        lang_bytes = added_bytes_per_language(project_key, has_parent)

        conn = lib.init_db()
        try:
            for language, (la, lr) in per_language.items():
                lib.insert_event(conn, {
                    "ts": now, "language": language, "lines_added": la,
                    "lines_removed": lr, "bytes_added": lang_bytes.get(language, 0),
                    "event_type": "edit", "project_key": project_key,
                })
            lib.insert_event(conn, {
                "ts": now, "language": None, "lines_added": 0,
                "lines_removed": 0, "bytes_added": 0,
                "event_type": "commit", "project_key": project_key,
            })
            unsynced = lib.get_unsynced_events(conn, limit=50)
            if unsynced:
                ok = lib.send_to_worker(unsynced, lib.repo_count(conn))
                if ok:
                    lib.mark_synced(conn, [e["id"] for e in unsynced])
        finally:
            conn.close()
    except Exception as exc:
        lib.log_error(f"git hook failed: {exc}")


if __name__ == "__main__":
    main()
    sys.exit(0)
