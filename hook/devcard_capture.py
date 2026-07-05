#!/usr/bin/env python3
"""Claude Code PostToolUse hook entrypoint for devcard. Never raises, always exits 0."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import devcard_lib as lib


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
            unsynced = lib.get_unsynced_events(conn, limit=50)
            if unsynced:
                ok = lib.send_to_worker(unsynced, lib.repo_count(conn))
                if ok:
                    lib.mark_synced(conn, [e["id"] for e in unsynced])
        finally:
            conn.close()
    except Exception as exc:
        lib.log_error(f"hook failed: {exc}")


if __name__ == "__main__":
    main()
    sys.exit(0)
