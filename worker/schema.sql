CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL,
  language TEXT,
  lines_added INTEGER NOT NULL DEFAULT 0,
  lines_removed INTEGER NOT NULL DEFAULT 0,
  event_type TEXT NOT NULL,
  client_event_id INTEGER
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_events_client_id ON events(client_event_id);

CREATE TABLE IF NOT EXISTS stats_snapshot (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  repo_count INTEGER NOT NULL DEFAULT 0,
  updated_at INTEGER NOT NULL
);

INSERT OR IGNORE INTO stats_snapshot (id, repo_count, updated_at) VALUES (1, 0, 0);

CREATE TABLE IF NOT EXISTS profile_entries (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,
  label TEXT NOT NULL,
  detail TEXT,
  created_at INTEGER NOT NULL
);
