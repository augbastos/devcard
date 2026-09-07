#!/usr/bin/env python3
"""Background sync for devcard — drains unsynced events to the Worker.

Spawned detached by devcard_capture.py (never blocks a Claude Code session).
Safe to run concurrently: mark_synced only flips rows this process sent, and
the Worker ingest is idempotent — UNIQUE(source_id, client_event_id) plus
INSERT OR IGNORE, with each row carrying the namespace it was queued under.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import devcard_lib as lib


def main():
    try:
        conn = lib.init_db()
        try:
            # Up to 2000 events per run. Resolving the installation id,
            # stamping unstamped rows and draining all live in sync_pending, so
            # the git hook cannot get that ordering subtly different.
            lib.sync_pending(conn, max_batches=40, timeout=10)
        finally:
            conn.close()
    except Exception as exc:
        lib.log_error(f"sync failed: {exc}")


if __name__ == "__main__":
    main()
    sys.exit(0)
