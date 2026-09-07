-- ---------------------------------------------------------------------------
-- Events.
--
-- `client_event_id` is the local SQLite rowid the hook assigned. It is what
-- makes ingest idempotent: a batch the hook re-sends after a lost response
-- hits the unique index and is ignored instead of counted twice.
--
-- A rowid alone is NOT a global identity, though. Every install's sequence
-- starts at 1, so a second machine's event 1 looked exactly like the first
-- machine's event 1 and was silently dropped — and deleting the local
-- events.db restarted the sequence, which made a fresh install's first
-- thousand events collide with history. `source_id` fixes that: a random,
-- opaque per-install id (see `source_id()` in hook/devcard_lib.py) that carries
-- no hostname, username or path. Identity is the pair.
--
-- 'legacy' is the default so that rows written before this column existed, and
-- hooks that predate it, keep exactly their previous dedupe behaviour.
--
-- The namespace belongs to the EVENT, not to the request. An event may carry
-- its own `source_id`, overriding the batch's, and a single batch may mix them.
-- That is what an upgrading hook needs: a backlog queued before it had an id
-- was sent (and possibly stored) as `legacy`, so it has to go back as `legacy`
-- even though the same batch also carries events captured afterwards under the
-- installation's real id. Re-sending that backlog under the new id would look
-- like different events and count the same work twice.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL,
  language TEXT,
  lines_added INTEGER NOT NULL DEFAULT 0,
  lines_removed INTEGER NOT NULL DEFAULT 0,
  bytes_added INTEGER NOT NULL DEFAULT 0,
  event_type TEXT NOT NULL,
  client_event_id INTEGER,
  source_id TEXT NOT NULL DEFAULT 'legacy'
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_events_source_client
  ON events(source_id, client_event_id);

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
