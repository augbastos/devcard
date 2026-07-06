#!/usr/bin/env python3
"""Background sync for devcard — drains unsynced events to the Worker.

Spawned detached by devcard_capture.py (never blocks a Claude Code session).
Safe to run concurrently: mark_synced only flips rows this process sent, and
the Worker ingest is idempotent (client_event_id UNIQUE + INSERT OR IGNORE).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import devcard_lib as lib


def main():
    try:
        conn = lib.init_db()
        try:
            for _ in range(40):  # up to 2000 events per run
                unsynced = lib.get_unsynced_events(conn, limit=50)
                if not unsynced:
                    break
                ok = lib.send_to_worker(unsynced, lib.repo_count(conn), timeout=10)
                if not ok:
                    break  # network down — next capture spawns a new attempt
                lib.mark_synced(conn, [e["id"] for e in unsynced])
        finally:
            conn.close()
    except Exception as exc:
        lib.log_error(f"sync failed: {exc}")


if __name__ == "__main__":
    main()
    sys.exit(0)
