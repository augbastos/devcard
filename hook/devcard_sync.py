#!/usr/bin/env python3
"""Background sync for devcard — drains unsynced events to the Worker.

Spawned detached by devcard_capture.py (never blocks a Claude Code session).
Safe to run concurrently: mark_synced only flips rows this process sent, and
the Worker ingest is idempotent — UNIQUE(source_id, client_event_id) plus
INSERT OR IGNORE, with each row carrying the namespace it was queued under.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import devcard_lib as lib


def drain():
    try:
        conn = lib.init_db()
        try:
            # Resolving the installation id, stamping unstamped rows and
            # draining all live in sync_pending, so the git hook cannot get
            # that ordering subtly different.
            lib.sync_pending(conn, max_batches=40, timeout=10)
        finally:
            conn.close()
    except Exception as exc:
        lib.log_error(f"sync failed: {exc}")


def main(sleep=time.sleep, clock=time.time):
    """Drain now, and once more when the capture throttle window closes.

    The capture hook spawns this at most once per window. An edit captured
    after this run's first drain but inside the window spawns nothing — so
    without the second drain, the last edits of a session sat unsynced until
    the next session's first tool call, however far away that was. The second
    pass covers exactly that gap: any capture after it finds the window closed
    and spawns a fresh syncer.
    """
    started = clock()
    drain()
    sleep(max(0.0, lib.SYNC_THROTTLE_SECONDS - (clock() - started)) + 1)
    drain()


if __name__ == "__main__":
    main()
    sys.exit(0)
