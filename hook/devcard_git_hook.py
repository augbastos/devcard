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


def _git(repo_dir, *args, check=False):
    return subprocess.run(
        ["git", "-C", repo_dir, *args], capture_output=True, text=True, errors="replace", check=check
    )


def head_parents(repo_dir):
    """Parent commit ids of HEAD, or None if HEAD cannot be resolved.

    `[]` means HEAD is the repository's first commit; two or more entries mean
    it is a merge.
    """
    out = _git(repo_dir, "rev-list", "--parents", "-n", "1", "HEAD")
    if out.returncode != 0:
        return None
    parts = out.stdout.split()
    return parts[1:] if parts else None


def _diff_args(parents):
    """git arguments producing HEAD's diff against its (single) parent.

    A merge is never routed here — see `main`.
    """
    if parents:
        return ["diff", parents[0], "HEAD"]
    # First commit in the repo: nothing to diff against, so diff the tree
    # against the empty tree.
    return ["diff-tree", "--root", "--no-commit-id", "HEAD"]


def numstat_for_head(repo_dir, parents):
    """Return list of (added, removed, path) for HEAD's diff."""
    out = _git(repo_dir, *_diff_args(parents), "--numstat", check=True).stdout
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


def added_bytes_per_language(repo_dir, parents):
    """Sum the byte length of added lines in HEAD's diff, grouped by language."""
    args = _diff_args(parents)
    if args[0] == "diff-tree":
        args = ["diff-tree", "-p", "--root", "--no-commit-id", "HEAD"]
    out = _git(repo_dir, *args, "--unified=0").stdout
    per_lang = {}
    current_lang = None
    for line in out.splitlines():
        if line.startswith("diff --git "):
            # New file section. Resetting matters: a deletion's header is
            # `+++ /dev/null`, which does not match below, so the previous
            # file's language would otherwise keep collecting the next one's
            # added bytes.
            current_lang = None
        elif line.startswith("+++ b/"):
            current_lang = lib.language_for_path(line[6:])
        elif line.startswith("+++"):
            current_lang = None
        elif line.startswith("+") and current_lang:
            per_lang[current_lang] = per_lang.get(current_lang, 0) + len(line[1:].encode("utf-8"))
    return per_lang


def collect(repo_dir, parents):
    """Per-language (added, removed) lines and added bytes for HEAD.

    Merge commits contribute a commit and nothing else, so this returns empty
    maps for them.

    `git diff <first-parent> HEAD` on a merge reports every line the merged
    branch brought in — lines this hook already recorded when each of those
    commits was made. Counting them again inflated the card by the whole size
    of every branch ever merged. `git diff-tree --cc` on a clean merge is
    empty, which is the same statement: a merge introduces no content of its
    own. A merge that resolves conflicts by hand can introduce genuinely new
    lines; those are not counted either, which under-reports by a few lines
    rather than over-reporting by a whole branch. See "Counting rules" in the
    README.

    (Most merges never reach this hook: git runs `post-merge`, not
    `post-commit`, when it creates the merge commit itself. The ones that do
    arrive here are `--no-commit` merges and conflict resolutions, which the
    user finishes with an explicit `git commit`.)
    """
    if parents is None or len(parents) >= 2:
        return {}, {}

    per_language = {}
    for added, removed, path in numstat_for_head(repo_dir, parents):
        language = lib.language_for_path(path)
        if not language:
            continue
        la, lr = per_language.get(language, (0, 0))
        per_language[language] = (la + added, lr + removed)
    return per_language, added_bytes_per_language(repo_dir, parents)


def main():
    try:
        # A machine in "claude" mode captures edits live; recording the commit
        # diff too would double-count the same lines.
        if capture_mode() == "claude":
            return

        top = _git(os.getcwd(), "rev-parse", "--show-toplevel")
        if top.returncode != 0:
            return
        project_key = top.stdout.strip()

        parents = head_parents(project_key)
        if parents is None:
            return

        import time

        now = int(time.time())
        per_language, lang_bytes = collect(project_key, parents)

        conn = lib.init_db()
        try:
            for language, (la, lr) in per_language.items():
                lib.insert_event(conn, {
                    # `diff`, not `edit`: this row is a per-commit, per-language
                    # aggregate, not one agent edit. Sharing the `edit` type
                    # made "code edits" mean two different things depending on
                    # which capture mode wrote the row.
                    "ts": now, "language": language, "lines_added": la,
                    "lines_removed": lr, "bytes_added": lang_bytes.get(language, 0),
                    "event_type": "diff", "project_key": project_key,
                })
            lib.insert_event(conn, {
                "ts": now, "language": None, "lines_added": 0,
                "lines_removed": 0, "bytes_added": 0,
                "event_type": "commit", "project_key": project_key,
            })
            # One batch: a post-commit hook must not sit on the network. A
            # backlog drains through devcard_sync.py.
            lib.sync_pending(conn, max_batches=1, timeout=1.5)
        finally:
            conn.close()
    except Exception as exc:
        lib.log_error(f"git hook failed: {exc}")


if __name__ == "__main__":
    main()
    sys.exit(0)
