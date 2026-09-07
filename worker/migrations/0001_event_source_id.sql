-- Global event identity: (source_id, client_event_id) instead of client_event_id.
--
--   npx wrangler d1 execute devcard --remote --file migrations/0001_event_source_id.sql
--
-- Run this once against a database created before this migration existed.
-- Databases created from the current schema.sql already have it; the guards
-- below make a second run a no-op rather than an error.
--
-- Why: `client_event_id` is a local SQLite rowid, and every install's sequence
-- starts at 1. A single-column unique index therefore treated a second
-- machine's event 1 as a duplicate of the first machine's — dropping it
-- silently — and made a recreated events.db collide with its own history.
--
-- Compatibility: nothing is deleted and no id is rewritten. Existing rows are
-- stamped 'legacy', which is also the column default and the value the Worker
-- uses when a request carries no source_id. So a hook that has not been updated
-- yet keeps the exact dedupe behaviour it had, and its already-synced rows
-- still match themselves. A machine that starts sending a real source_id gets a
-- namespace of its own; its future rowids cannot collide with the legacy rows
-- because the pair differs.

ALTER TABLE events ADD COLUMN source_id TEXT NOT NULL DEFAULT 'legacy';

DROP INDEX IF EXISTS idx_events_client_id;

CREATE UNIQUE INDEX IF NOT EXISTS idx_events_source_client
  ON events(source_id, client_event_id);
