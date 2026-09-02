CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL,
  language TEXT,
  lines_added INTEGER NOT NULL DEFAULT 0,
  lines_removed INTEGER NOT NULL DEFAULT 0,
  bytes_added INTEGER NOT NULL DEFAULT 0,
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

CREATE TABLE IF NOT EXISTS pinned_repos (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  repo TEXT NOT NULL UNIQUE,
  note TEXT,
  position INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL
);

-- ---------------------------------------------------------------------------
-- Rollups.
--
-- The card is rendered far more often than it is written to, and every render
-- used to aggregate the whole `events` table: four full scans plus the heatmap
-- range, so the rows read per render grew with every edit ever recorded. At
-- ~18k events that was ~75k rows for one image, which exhausts D1's daily read
-- allowance in well under a hundred renders.
--
-- These tables move that work to ingest, which happens a few times a session
-- instead of once per viewer. The render path now reads a fixed handful of
-- rows: one per language, one per event type, one per day in the heat window.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS agg_language (
  language TEXT PRIMARY KEY,
  lines    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS agg_event_type (
  event_type TEXT PRIMARY KEY,
  n          INTEGER NOT NULL DEFAULT 0
);

-- `day` is the calendar day in the worker's configured TIMEZONE, so it is
-- computed in the worker at ingest rather than by a SQL trigger: SQLite's date
-- functions only know UTC, and the heatmap has always been drawn in local days.
CREATE TABLE IF NOT EXISTS agg_day (
  day   TEXT PRIMARY KEY,
  lines INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS agg_totals (
  id       INTEGER PRIMARY KEY CHECK (id = 1),
  bytes    INTEGER NOT NULL DEFAULT 0,
  events   INTEGER NOT NULL DEFAULT 0,
  first_ts INTEGER
);

INSERT OR IGNORE INTO agg_totals (id, bytes, events, first_ts) VALUES (1, 0, 0, NULL);
