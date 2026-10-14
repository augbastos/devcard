"""Connect the offline usage scanner to local readers, without capture side effects."""
from datetime import timezone
import json
import os
from pathlib import Path
import sqlite3
from zoneinfo import ZoneInfo

from ._hook import lib, usage


def default_roots():
    codex = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    return (("claude", Path.home() / ".claude" / "projects"),
            ("codex", codex / "sessions"), ("codex", codex / "archived_sessions"))


def scan_local(cfg, conn=None, db_path=None):
    """Scan incrementally; failures log structural diagnostics and never stop a reader.

    Serving an installation without a database does not create one or rotate
    its identity. Publishing passes its already-initialized connection.
    """
    if cfg.get("usage", True) is False:
        return
    owned = conn is None
    try:
        if owned:
            path = Path(lib.DB_PATH if db_path is None else db_path).resolve()
            if not path.is_file():
                return
            conn = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=2)
        # Usage's persistent buckets need a stable zone. Without an explicit
        # IANA zone use UTC, rather than today's system-local fixed UTC offset.
        zone = ZoneInfo(cfg["timezone"]) if cfg.get("timezone") else timezone.utc
        for agent, root in default_roots():
            try:
                paths = usage.discover_usage_paths(root, agent=agent)
                report = usage.scan_usage(paths, conn, agent=agent, tz=zone)
                if report.diagnostics:
                    lib.log_error("usage scan: " + ", ".join(
                        f"{code}={count}" for code, count in sorted(report.diagnostics.items())))
            except Exception as exc:
                # Exceptions may contain source paths or transcript contents.
                lib.log_error(f"usage scan failed ({type(exc).__name__})")
    except Exception as exc:
        lib.log_error(f"usage scan failed ({type(exc).__name__})")
    finally:
        if owned and conn is not None:
            conn.close()


def public_rows(conn):
    """Only M4's validated export allowlist can leave SQLite."""
    if conn is None or not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='usage_aggregates'"
    ).fetchone():
        return []
    return json.loads(usage.export_usage(usage.read_usage(conn)))
