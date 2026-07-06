#!/usr/bin/env python3
"""Claude Code PostToolUse hook entrypoint for devcard. Never raises, always exits 0.

Fast path only: parse + local SQLite insert (~100ms). Network sync runs in a
DETACHED background process (devcard_sync.py) so a tool call never waits on the
network — a synchronous POST here was adding ~1s to every Edit/Write/Bash.
"""
import json
import os
import sys
import time
# subprocess is imported lazily in maybe_spawn_sync — the throttled path only.

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import devcard_lib as lib

SYNC_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "devcard_sync.py")
SYNC_MARKER = os.path.normpath(os.path.expanduser("~/.claude/devcard/last-sync-spawn"))
SYNC_THROTTLE_SECONDS = 20


def maybe_spawn_sync():
    """Spawn the background syncer at most once per throttle window."""
    now = time.time()
    try:
        if now - os.stat(SYNC_MARKER).st_mtime < SYNC_THROTTLE_SECONDS:
            return
    except OSError:
        pass
    try:
        import subprocess

        os.makedirs(os.path.dirname(SYNC_MARKER), exist_ok=True)
        with open(SYNC_MARKER, "w") as f:
            f.write(str(int(now)))
        flags = 0
        if os.name == "nt":
            flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        subprocess.Popen(
            [sys.executable, "-S", SYNC_SCRIPT],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=flags,
        )
    except Exception as exc:
        lib.log_error(f"sync spawn failed: {exc}")


def main():
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw else {}
    except Exception as exc:
        lib.log_error(f"failed to parse hook payload: {exc}")
        return

    try:
        event = lib.parse_event(payload)
        if event is None:
            return
        conn = lib.init_db()
        try:
            lib.insert_event(conn, event)
        finally:
            conn.close()
        maybe_spawn_sync()
    except Exception as exc:
        lib.log_error(f"hook failed: {exc}")


if __name__ == "__main__":
    main()
    sys.exit(0)
