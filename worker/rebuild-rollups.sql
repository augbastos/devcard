-- Rebuild the rollup tables from `events`.
--
-- The card renders from rollups (see the rollup section of schema.sql) that
-- ingest maintains incrementally. Incremental means they can drift: a deploy
-- that lands between a schema change and the code that feeds it, a manual
-- INSERT into `events`, or a bug. Nothing self-heals, so this file is the way
-- back to a known-good state. It is safe to run at any time and is idempotent.
--
--   npx wrangler d1 execute devcard --remote --file rebuild-rollups.sql
--
-- TIMEZONE: `agg_day` keys the heatmap by calendar day in the timezone the
-- worker is configured with, and SQLite has no timezone database — so the
-- offset below is a literal you must set yourself. '+0 hours' is correct for
-- TIMEZONE="UTC". For a zone with daylight saving, a single offset is only
-- exact if the whole dataset sits inside one DST period; otherwise events
-- within an hour of midnight can land on the neighbouring day until the next
-- ingest corrects that day. The worker itself always uses Intl and is exact.
--
-- The last statement must report four zeros. Anything else means a write
-- landed mid-rebuild — just run the file again.

DELETE FROM agg_language;
DELETE FROM agg_event_type;
DELETE FROM agg_day;

INSERT INTO agg_language (language, lines)
  SELECT language, SUM(lines_added) FROM events
  WHERE language IS NOT NULL GROUP BY language;

INSERT INTO agg_event_type (event_type, n)
  SELECT event_type, COUNT(*) FROM events GROUP BY event_type;

INSERT INTO agg_day (day, lines)
  SELECT date(ts, 'unixepoch', '+0 hours'), SUM(lines_added) FROM events GROUP BY 1;

UPDATE agg_totals SET
  bytes    = (SELECT COALESCE(SUM(bytes_added), 0) FROM events),
  events   = (SELECT COUNT(*) FROM events),
  first_ts = (SELECT MIN(ts) FROM events)
  WHERE id = 1;

SELECT
  (SELECT COUNT(*) FROM events)
    - (SELECT events FROM agg_totals WHERE id = 1)                       AS drift_events,
  (SELECT SUM(lines_added) FROM events WHERE language IS NOT NULL)
    - (SELECT SUM(lines) FROM agg_language)                              AS drift_lines,
  (SELECT SUM(bytes_added) FROM events)
    - (SELECT bytes FROM agg_totals WHERE id = 1)                        AS drift_bytes,
  (SELECT SUM(lines_added) FROM events)
    - (SELECT SUM(lines) FROM agg_day)                                   AS drift_day;
