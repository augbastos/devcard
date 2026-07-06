"""Shared helpers for the devcard Claude Code hook."""
import json
import os
import sqlite3
import time
# urllib.request is imported lazily inside send_to_worker — it costs ~150ms to
# import and the hot capture path (hook per tool call) never needs it.

DB_PATH = os.path.normpath(os.path.expanduser("~/.claude/devcard/events.db"))
ERROR_LOG_PATH = os.path.normpath(os.path.expanduser("~/.claude/devcard/errors.log"))
TOKEN_PATH = os.path.normpath(os.path.expanduser("~/.claude/devcard/token"))
WORKER_INGEST_URL = "https://card.devcard.workers.dev/ingest"


def _load_token():
    """Env var wins; else the token file. The file means every hook process
    finds the token regardless of when its parent session started."""
    env = os.environ.get("DEVCARD_INGEST_TOKEN", "")
    if env:
        return env
    try:
        with open(TOKEN_PATH, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


INGEST_TOKEN = _load_token()

EXT_LANGUAGE = {
    ".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript", ".html": "HTML", ".htm": "HTML",
    ".css": "CSS", ".scss": "SCSS", ".rs": "Rust", ".ps1": "PowerShell", ".psm1": "PowerShell",
    ".sql": "SQL", ".md": "Markdown", ".mdx": "Markdown", ".json": "JSON",
    ".yml": "YAML", ".yaml": "YAML", ".toml": "TOML", ".sh": "Shell", ".bash": "Shell",
    ".go": "Go", ".java": "Java", ".c": "C", ".h": "C", ".cpp": "C++", ".hpp": "C++",
    ".rb": "Ruby", ".php": "PHP",
}


def language_for_path(path):
    """Return the language name for a file path, or None if unrecognized."""
    _, ext = os.path.splitext(path.lower())
    return EXT_LANGUAGE.get(ext)


def count_lines(text):
    """Count lines in a text blob. Empty string counts as 0 lines."""
    if not text:
        return 0
    return text.count("\n") + 1


def parse_event(payload):
    """Turn a raw Claude Code hook payload into a normalized event dict, or None."""
    tool_name = payload.get("tool_name")
    tool_input = payload.get("tool_input") or {}
    cwd = payload.get("cwd") or ""
    now = int(time.time())

    if tool_name == "Write":
        file_path = tool_input.get("file_path", "")
        language = language_for_path(file_path)
        if not language:
            return None
        content = tool_input.get("content", "")
        return {
            "ts": now, "language": language, "lines_added": count_lines(content),
            "lines_removed": 0, "bytes_added": len(content.encode("utf-8", errors="replace")),
            "event_type": "write", "project_key": cwd,
        }

    if tool_name == "Edit":
        file_path = tool_input.get("file_path", "")
        language = language_for_path(file_path)
        if not language:
            return None
        old_string = tool_input.get("old_string", "")
        new_string = tool_input.get("new_string", "")
        return {
            "ts": now, "language": language, "lines_added": count_lines(new_string),
            "lines_removed": count_lines(old_string), "bytes_added": len(new_string.encode("utf-8", errors="replace")),
            "event_type": "edit", "project_key": cwd,
        }

    if tool_name == "Bash":
        command = tool_input.get("command", "")
        if "git commit" in command:
            return {
                "ts": now, "language": None, "lines_added": 0,
                "lines_removed": 0, "bytes_added": 0,
                "event_type": "commit", "project_key": cwd,
            }
        return None

    return None


def init_db(db_path=DB_PATH):
    """Open (creating if needed) the local SQLite db and ensure its schema exists."""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            language TEXT,
            lines_added INTEGER NOT NULL DEFAULT 0,
            lines_removed INTEGER NOT NULL DEFAULT 0,
            bytes_added INTEGER NOT NULL DEFAULT 0,
            event_type TEXT NOT NULL,
            project_key TEXT NOT NULL,
            synced INTEGER NOT NULL DEFAULT 0
        )
    """)
    try:
        conn.execute("ALTER TABLE events ADD COLUMN bytes_added INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # column already exists (fresh dbs get it from CREATE TABLE)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS known_repos (
            project_key TEXT PRIMARY KEY,
            first_seen INTEGER NOT NULL
        )
    """)
    conn.commit()
    return conn


def insert_event(conn, event):
    """Insert a normalized event and record its project in known_repos. Returns the new row id."""
    cur = conn.execute(
        "INSERT INTO events (ts, language, lines_added, lines_removed, bytes_added, event_type, project_key) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (event["ts"], event["language"], event["lines_added"], event["lines_removed"],
         event.get("bytes_added", 0), event["event_type"], event["project_key"]),
    )
    conn.execute(
        "INSERT OR IGNORE INTO known_repos (project_key, first_seen) VALUES (?, ?)",
        (event["project_key"], event["ts"]),
    )
    conn.commit()
    return cur.lastrowid


def repo_count(conn):
    """Return the number of distinct local projects ever seen."""
    row = conn.execute("SELECT COUNT(*) FROM known_repos").fetchone()
    return row[0]


def get_unsynced_events(conn, limit=50):
    """Return up to `limit` events not yet marked synced, oldest first."""
    rows = conn.execute(
        "SELECT id, ts, language, lines_added, lines_removed, bytes_added, event_type "
        "FROM events WHERE synced = 0 ORDER BY id ASC LIMIT ?",
        (limit,),
    ).fetchall()
    return [
        {"id": r[0], "ts": r[1], "language": r[2], "lines_added": r[3],
         "lines_removed": r[4], "bytes_added": r[5], "event_type": r[6]}
        for r in rows
    ]


def mark_synced(conn, event_ids):
    """Mark the given event ids as synced."""
    if not event_ids:
        return
    conn.executemany("UPDATE events SET synced = 1 WHERE id = ?", [(i,) for i in event_ids])
    conn.commit()


def log_error(message, path=ERROR_LOG_PATH):
    """Append an error message to the local error log. Never raises."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
    except Exception:
        pass


def send_to_worker(events, repo_count_value, url=WORKER_INGEST_URL, token=None, timeout=1.5):
    """POST a batch of events plus the current repo count to the Worker. Returns True on success."""
    import urllib.request

    token = token if token is not None else INGEST_TOKEN
    body = json.dumps({"events": events, "repo_count": repo_count_value}).encode("utf-8", errors="replace")
    req = urllib.request.Request(
        url, data=body,
        headers={
            "Content-Type": "application/json",
            "X-Devcard-Token": token,
            "User-Agent": "devcard-hook/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except Exception as exc:
        log_error(f"send_to_worker failed: {exc}")
        return False
