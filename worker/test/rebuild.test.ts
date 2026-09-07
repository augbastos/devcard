import { env, createExecutionContext, waitOnExecutionContext, createScheduledController } from "cloudflare:test";
import { beforeEach, describe, expect, it } from "vitest";
import worker from "../src/index";
import { resetDb } from "./helpers";

const DAY = 86400;

async function insertRaw(
  rows: { ts: number; language: string | null; lines: number; bytes?: number; type?: string; id?: number }[]
): Promise<void> {
  for (const [i, r] of rows.entries()) {
    await env.DB.prepare(
      "INSERT INTO events (ts, language, lines_added, lines_removed, bytes_added, event_type, client_event_id, source_id)" +
        " VALUES (?, ?, ?, 0, ?, ?, ?, 'rebuildtest')"
    )
      .bind(r.ts, r.language, r.lines, r.bytes ?? 0, r.type ?? "edit", r.id ?? i + 1)
      .run();
  }
}

async function runScheduled(): Promise<void> {
  const ctx = createExecutionContext();
  await worker.scheduled!(createScheduledController(), env, ctx);
  await waitOnExecutionContext(ctx);
}

async function rollups() {
  const [lang, type, totals, days] = await Promise.all([
    env.DB.prepare("SELECT language, lines FROM agg_language ORDER BY language").all(),
    env.DB.prepare("SELECT event_type, n FROM agg_event_type ORDER BY event_type").all(),
    env.DB.prepare("SELECT bytes, events, first_ts FROM agg_totals WHERE id = 1").first(),
    env.DB.prepare("SELECT day, lines FROM agg_day ORDER BY day").all(),
  ]);
  return { lang: lang.results, type: type.results, totals, days: days.results };
}

describe("nightly rollup rebuild", () => {
  beforeEach(async () => {
    await resetDb();
  });

  it("recomputes every rollup from the raw events", async () => {
    const now = Math.floor(Date.now() / 1000);
    await insertRaw([
      { ts: now - DAY, language: "Python", lines: 10, bytes: 100 },
      { ts: now - DAY, language: "Python", lines: 5, bytes: 50 },
      { ts: now, language: "Rust", lines: 7, bytes: 70 },
      { ts: now, language: null, lines: 0, type: "commit" },
    ]);

    // Rollups are empty: these rows were written straight to `events`, which is
    // exactly the drift the rebuild exists to repair.
    expect((await rollups()).lang).toEqual([]);

    await runScheduled();

    const after = await rollups();
    expect(after.lang).toEqual([
      { language: "Python", lines: 15 },
      { language: "Rust", lines: 7 },
    ]);
    expect(after.type).toEqual([
      { event_type: "commit", n: 1 },
      { event_type: "edit", n: 3 },
    ]);
    expect(after.totals).toMatchObject({ bytes: 220, events: 4, first_ts: now - DAY });
  });

  it("repairs a drifted rollup rather than adding to it", async () => {
    const now = Math.floor(Date.now() / 1000);
    await insertRaw([{ ts: now, language: "Python", lines: 10, bytes: 100 }]);
    await env.DB.prepare("INSERT INTO agg_language (language, lines) VALUES ('Python', 999)").run();
    await env.DB.prepare("UPDATE agg_totals SET events = 999, bytes = 999 WHERE id = 1").run();

    await runScheduled();

    const after = await rollups();
    expect(after.lang).toEqual([{ language: "Python", lines: 10 }]);
    expect(after.totals).toMatchObject({ bytes: 100, events: 1 });
  });

  it("is idempotent", async () => {
    const now = Math.floor(Date.now() / 1000);
    await insertRaw([
      { ts: now, language: "Python", lines: 10, bytes: 100 },
      { ts: now, language: "Rust", lines: 3, bytes: 30 },
    ]);
    await runScheduled();
    const first = await rollups();
    await runScheduled();
    expect(await rollups()).toEqual(first);
  });

  it("keeps agg_day flat instead of growing a row per day forever", async () => {
    const now = Math.floor(Date.now() / 1000);
    // One event a day for a year, plus a very old one.
    const rows = [];
    for (let d = 0; d < 365; d++) {
      rows.push({ ts: now - d * DAY, language: "Python", lines: 1, id: d + 1 });
    }
    await insertRaw(rows);
    await runScheduled();

    const days = (await rollups()).days as { day: string }[];
    // The window is 16 weeks of heatmap plus a fortnight of slack.
    expect(days.length).toBeLessThanOrEqual(16 * 7 + 14 + 1);
    expect(days.length).toBeGreaterThan(100);
  });

  it("counts a whole day's lines even when they arrive in many events", async () => {
    const now = Math.floor(Date.now() / 1000);
    // The rebuild buckets by 15 minutes to avoid returning one row per event;
    // the totals must still come out exact.
    const rows = [];
    for (let i = 0; i < 40; i++) {
      rows.push({ ts: now - i * 60, language: "Python", lines: 3, id: i + 1 });
    }
    await insertRaw(rows);
    await runScheduled();

    const days = (await rollups()).days as { day: string; lines: number }[];
    const total = days.reduce((sum, d) => sum + d.lines, 0);
    expect(total).toBe(120);
  });

  it("agrees with what incremental ingest produced", async () => {
    // The two paths must not disagree, or the nightly run would visibly move
    // the card's numbers every night.
    const now = Math.floor(Date.now() / 1000);
    const events = [
      { ts: now, language: "Python", lines_added: 12, lines_removed: 0, bytes_added: 120, event_type: "edit", id: 1 },
      { ts: now, language: "TypeScript", lines_added: 8, lines_removed: 0, bytes_added: 80, event_type: "edit", id: 2 },
      { ts: now, language: null, lines_added: 0, lines_removed: 0, bytes_added: 0, event_type: "commit", id: 3 },
    ];
    const res = await env.DB.prepare("SELECT 1").first();
    expect(res).not.toBeNull();

    const ingest = new Request("https://card.example/ingest", {
      method: "POST",
      headers: { "X-Devcard-Token": env.INGEST_TOKEN, "Content-Type": "application/json" },
      body: JSON.stringify({ source_id: "rebuildtest", events }),
    });
    const ctx = createExecutionContext();
    const response = await worker.fetch(ingest, env, ctx);
    await waitOnExecutionContext(ctx);
    expect(response.status).toBe(200);

    const incremental = await rollups();
    await runScheduled();
    expect(await rollups()).toEqual(incremental);
  });
});
