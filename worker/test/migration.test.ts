import { env } from "cloudflare:test";
import { beforeEach, describe, expect, it } from "vitest";
import { applySchema, splitStatements } from "./helpers";
import migration0001 from "../migrations/0001_event_source_id.sql?raw";

// The exact shape of `events` before 0001 — a historical fact, so it is pinned
// here rather than read from a file that will keep changing.
const PRE_MIGRATION_EVENTS = `
CREATE TABLE events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL,
  language TEXT,
  lines_added INTEGER NOT NULL DEFAULT 0,
  lines_removed INTEGER NOT NULL DEFAULT 0,
  bytes_added INTEGER NOT NULL DEFAULT 0,
  event_type TEXT NOT NULL,
  client_event_id INTEGER
);
CREATE UNIQUE INDEX idx_events_client_id ON events(client_event_id);
`;

async function dropEverything(): Promise<void> {
  const tables = await env.DB.prepare(
    "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '_cf_%'"
  ).all();
  for (const row of (tables.results as { name: string }[]) ?? []) {
    await env.DB.prepare(`DROP TABLE IF EXISTS "${row.name}"`).run();
  }
}

async function run(sql: string): Promise<void> {
  for (const statement of splitStatements(sql)) {
    await env.DB.prepare(statement).run();
  }
}

async function columns(): Promise<{ name: string; type: string; notnull: number; dflt_value: unknown }[]> {
  const res = await env.DB.prepare("PRAGMA table_info(events)").all();
  return (res.results as Record<string, unknown>[]).map((c) => ({
    name: String(c.name),
    type: String(c.type),
    notnull: Number(c.notnull),
    dflt_value: c.dflt_value ?? null,
  }));
}

async function uniqueIndexes(): Promise<string[]> {
  const res = await env.DB.prepare(
    "SELECT name, sql FROM sqlite_master WHERE type = 'index' AND tbl_name = 'events' AND sql IS NOT NULL ORDER BY name"
  ).all();
  return (res.results as { name: string; sql: string }[]).map((r) => r.sql.replace(/\s+/g, " ").trim());
}

describe("migration 0001 — event source id", () => {
  beforeEach(async () => {
    await dropEverything();
  });

  it("upgrades an old database to exactly the shape schema.sql creates", async () => {
    await run(PRE_MIGRATION_EVENTS);
    await run(migration0001);
    const migratedColumns = await columns();
    const migratedIndexes = await uniqueIndexes();

    await dropEverything();
    await applySchema(env.DB);
    const freshColumns = await columns();
    const freshIndexes = await uniqueIndexes();

    // If these ever diverge, one of two install paths is producing a database
    // the other's code was never tested against.
    expect(migratedColumns).toEqual(freshColumns);
    expect(migratedIndexes).toEqual(freshIndexes);
  });

  it("loses no events and rewrites no ids", async () => {
    await run(PRE_MIGRATION_EVENTS);
    for (const id of [1, 2, 3]) {
      await env.DB.prepare(
        "INSERT INTO events (ts, language, lines_added, lines_removed, bytes_added, event_type, client_event_id)" +
          " VALUES (1750000000, 'Python', 10, 0, 100, 'edit', ?)"
      )
        .bind(id)
        .run();
    }

    await run(migration0001);

    const after = await env.DB.prepare(
      "SELECT client_event_id, source_id, lines_added FROM events ORDER BY client_event_id"
    ).all();
    expect(after.results).toEqual([
      { client_event_id: 1, source_id: "legacy", lines_added: 10 },
      { client_event_id: 2, source_id: "legacy", lines_added: 10 },
      { client_event_id: 3, source_id: "legacy", lines_added: 10 },
    ]);
  });

  it("is safe to run twice", async () => {
    await run(PRE_MIGRATION_EVENTS);
    await run(migration0001);
    // ALTER TABLE ADD COLUMN has no IF NOT EXISTS in SQLite, so a re-run fails
    // on that one statement — the operator's cue that it already ran. What must
    // not happen is data loss or a half-applied index, so assert the end state
    // survives the attempt.
    await expect(run(migration0001)).rejects.toThrow();
    expect((await uniqueIndexes()).join()).toContain("idx_events_source_client");
    expect((await columns()).map((c) => c.name)).toContain("source_id");
  });

  it("keeps the old index from surviving alongside the new one", async () => {
    // Leaving idx_events_client_id in place would keep enforcing the exact
    // global-uniqueness bug the migration exists to remove.
    await run(PRE_MIGRATION_EVENTS);
    await run(migration0001);
    const names = await env.DB.prepare(
      "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'events'"
    ).all();
    const list = (names.results as { name: string }[]).map((r) => r.name);
    expect(list).not.toContain("idx_events_client_id");
    expect(list).toContain("idx_events_source_client");
  });
});

describe("schema.sql", () => {
  beforeEach(async () => {
    await dropEverything();
    await applySchema(env.DB);
  });

  it("creates every table the card reads from", async () => {
    const res = await env.DB.prepare(
      "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '_cf_%' ORDER BY name"
    ).all();
    expect((res.results as { name: string }[]).map((r) => r.name)).toEqual([
      "agg_day",
      "agg_event_type",
      "agg_language",
      "agg_totals",
      "events",
      "pinned_repos",
      "profile_entries",
      "stats_snapshot",
    ]);
  });

  it("seeds the singleton rows the render path assumes exist", async () => {
    expect(await env.DB.prepare("SELECT id FROM stats_snapshot WHERE id = 1").first()).not.toBeNull();
    expect(await env.DB.prepare("SELECT id FROM agg_totals WHERE id = 1").first()).not.toBeNull();
  });

  it("is idempotent", async () => {
    await applySchema(env.DB);
    const res = await env.DB.prepare("SELECT COUNT(*) AS n FROM stats_snapshot").first();
    expect((res as { n: number }).n).toBe(1);
  });
});
