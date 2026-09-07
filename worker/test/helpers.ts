import { env } from "cloudflare:test";
import schemaSql from "../schema.sql?raw";
import { cacheKeyFor, LAYOUTS, STRINGS } from "../src/variants";
import { THEMES } from "../src/themes";

// D1's `exec()` splits on newlines, so it cannot run the pretty-printed
// schema.sql the README tells people to apply. Rather than keep a second,
// single-line copy of the schema (which would drift), tests parse the real
// file: strip `--` comments, split on statement terminators, run the rest.
// A test asserts the parse produced the tables the card actually reads.
export function splitStatements(sql: string): string[] {
  return sql
    .split("\n")
    .map((line) => (line.trimStart().startsWith("--") ? "" : line))
    .join("\n")
    .split(";")
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
}

export async function applySchema(db: D1Database, sql: string = schemaSql): Promise<void> {
  for (const statement of splitStatements(sql)) {
    await db.prepare(statement).run();
  }
}

// The edge cache survives D1 resets, so a test that seeds new rows and then
// renders would otherwise be served a card built before its own setup ran.
// The variant space is small and enumerable by construction — that is the
// point of the synthetic cache key — so purging it exactly is cheap.
export async function purgeCardCache(): Promise<void> {
  const cache = await caches.open("default");
  const url = new URL("https://card.example/svg");
  for (const lang of Object.keys(STRINGS)) {
    for (const theme of Object.keys(THEMES)) {
      for (const layout of LAYOUTS) {
        await cache.delete(cacheKeyFor(url, lang, theme, layout));
      }
    }
  }
}

/** Fresh, empty schema and a cold cache for one test. Call in `beforeEach`. */
export async function resetDb(): Promise<void> {
  await purgeCardCache();
  const tables = await env.DB.prepare(
    "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '_cf_%'"
  ).all();
  for (const row of (tables.results as { name: string }[]) ?? []) {
    await env.DB.prepare(`DROP TABLE IF EXISTS "${row.name}"`).run();
  }
  await applySchema(env.DB);
}

// Taken from the binding, never hardcoded: a developer running the suite with a
// real .dev.vars present must not have that token typed into a test file, and
// no assertion ever compares against its value.
export const TOKEN = env.INGEST_TOKEN;
export const WRONG_TOKEN = "definitely-not-the-ingest-token";

export interface WireEvent {
  id?: number;
  ts: number;
  language: string | null;
  lines_added: number;
  lines_removed: number;
  bytes_added?: number;
  event_type: string;
}

export function ev(overrides: Partial<WireEvent> = {}): WireEvent {
  return {
    ts: 1750000000,
    language: "Python",
    lines_added: 10,
    lines_removed: 0,
    bytes_added: 100,
    event_type: "edit",
    ...overrides,
  };
}

export function ingestRequest(body: unknown, token: string = TOKEN, raw?: string): Request {
  return new Request("https://card.example/ingest", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Devcard-Token": token },
    body: raw ?? JSON.stringify(body),
  });
}

export function svgRequest(query = "", headers: Record<string, string> = {}): Request {
  return new Request(`https://card.example/svg${query}`, { headers });
}
