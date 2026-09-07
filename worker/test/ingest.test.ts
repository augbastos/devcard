import { SELF, env } from "cloudflare:test";
import { beforeEach, describe, expect, it } from "vitest";
import { resetDb, ev, ingestRequest } from "./helpers";

async function post(body: unknown): Promise<{ status: number; json: Record<string, number> }> {
  const res = await SELF.fetch(ingestRequest(body));
  const status = res.status;
  const json = status === 200 ? ((await res.json()) as Record<string, number>) : {};
  return { status, json };
}

async function count(sql: string): Promise<number> {
  const row = await env.DB.prepare(sql).first();
  return Number(Object.values(row as Record<string, unknown>)[0] ?? 0);
}

const rows = () => count("SELECT COUNT(*) AS n FROM events");
const rolledLines = () => count("SELECT COALESCE(SUM(lines), 0) AS n FROM agg_language");
const rolledEvents = () => count("SELECT events AS n FROM agg_totals WHERE id = 1");

describe("event identity", () => {
  beforeEach(async () => {
    await resetDb();
  });

  it("counts the same event once when the same batch is sent twice", async () => {
    const batch = {
      source_id: "machine-a",
      events: [ev({ id: 1, lines_added: 10 }), ev({ id: 2, lines_added: 20 })],
    };

    const first = await post(batch);
    expect(first.json).toMatchObject({ inserted: 2, duplicates: 0 });

    // The retry a hook makes when the response to the first attempt was lost.
    const second = await post(batch);
    expect(second.json).toMatchObject({ inserted: 0, duplicates: 2 });

    expect(await rows()).toBe(2);
    // The rollups are what the card renders from, so idempotency has to hold
    // there too — not just in `events`.
    expect(await rolledLines()).toBe(30);
    expect(await rolledEvents()).toBe(2);
  });

  it("counts machine A event 1 and machine B event 1 as two different events", async () => {
    // The regression: a local rowid is not a global identity. Both installs
    // start their sequence at 1, and B's work used to vanish silently.
    await post({ source_id: "machine-a", events: [ev({ id: 1, lines_added: 10 })] });
    const b = await post({ source_id: "machine-b", events: [ev({ id: 1, lines_added: 25 })] });

    expect(b.json).toMatchObject({ inserted: 1, duplicates: 0 });
    expect(await rows()).toBe(2);
    expect(await rolledLines()).toBe(35);
  });

  it("keeps two machines independent across a whole overlapping sequence", async () => {
    const seq = (source: string, lines: number) =>
      post({
        source_id: source,
        events: [1, 2, 3, 4, 5].map((id) => ev({ id, lines_added: lines })),
      });

    expect((await seq("machine-a", 1)).json).toMatchObject({ inserted: 5 });
    expect((await seq("machine-b", 2)).json).toMatchObject({ inserted: 5 });
    expect(await rows()).toBe(10);
    expect(await rolledLines()).toBe(15);
  });

  it("does not collide when a recreated local database restarts its ids", async () => {
    // Deleting ~/.claude/devcard/events.db restarts AUTOINCREMENT at 1. Under
    // the old single-column index, the first N events after that were dropped
    // as duplicates of the pre-wipe history.
    await post({ source_id: "install-one", events: [ev({ id: 1 }), ev({ id: 2 }), ev({ id: 3 })] });

    // Fresh install, fresh source id, ids start over.
    const after = await post({
      source_id: "install-two",
      events: [ev({ id: 1 }), ev({ id: 2 })],
    });

    expect(after.json).toMatchObject({ inserted: 2, duplicates: 0 });
    expect(await rows()).toBe(5);
  });

  describe("backwards compatibility", () => {
    it("treats a payload with no source_id as the legacy namespace", async () => {
      const first = await post({ events: [ev({ id: 1 })] });
      const retry = await post({ events: [ev({ id: 1 })] });

      expect(first.json).toMatchObject({ inserted: 1 });
      expect(retry.json).toMatchObject({ inserted: 0, duplicates: 1 });

      const row = await env.DB.prepare("SELECT source_id FROM events").first();
      expect((row as { source_id: string }).source_id).toBe("legacy");
    });

    it("lets an updated hook coexist with the rows it already synced as legacy", async () => {
      // Exactly the upgrade path: rows already in D1 carry 'legacy'; the same
      // machine then starts sending a real source id with a continuing rowid
      // sequence. Neither may swallow the other.
      await post({ events: [ev({ id: 1 }), ev({ id: 2 })] });
      const upgraded = await post({ source_id: "abcd1234", events: [ev({ id: 3 })] });

      expect(upgraded.json).toMatchObject({ inserted: 1 });
      expect(await rows()).toBe(3);
    });

    it("still de-duplicates events with no client id the way it always did", async () => {
      // NULL client ids are distinct in a SQL unique index, so these do count
      // twice — unchanged from before, and documented rather than silently
      // different.
      await post({ source_id: "abcd1234", events: [ev({ id: undefined })] });
      await post({ source_id: "abcd1234", events: [ev({ id: undefined })] });
      expect(await rows()).toBe(2);
    });
  });

  describe("upgrading across the source_id change", () => {
    it("REPRO: a lost ACK before the upgrade duplicates when the event comes back under a new id", async () => {
      // 1. An old hook syncs event 42 with no source_id at all.
      const first = await post({ events: [ev({ id: 42, lines_added: 10 })] });
      expect(first.json).toMatchObject({ inserted: 1 });

      // 2. The response never reached the hook, so the local row is still
      //    synced = 0. 3. The user upgrades. 4. The new hook re-sends the same
      //    local row, now stamped with this installation's fresh source id.
      const afterUpgrade = await post({
        source_id: "brandnewinstall",
        events: [ev({ id: 42, lines_added: 10 })],
      });

      // The Worker has no way to know these are the same event: it was told
      // two different identities for it. Duplication is therefore a property
      // of the CLIENT losing the event's original identity, and has to be
      // fixed there — the local row must remember which namespace it was
      // queued under.
      expect(afterUpgrade.json).toMatchObject({ inserted: 1, duplicates: 0 });
      expect(await rows()).toBe(2);
      expect(await rolledLines()).toBe(20); // the card would show double
    });

    it("de-duplicates when the event keeps the identity it was queued under", async () => {
      // Same scenario, but the upgraded hook remembers that row 42 predates
      // its source id and re-sends it as legacy.
      await post({ events: [ev({ id: 42, lines_added: 10 })] });
      const afterUpgrade = await post({
        source_id: "brandnewinstall",
        events: [{ ...ev({ id: 42, lines_added: 10 }), source_id: "legacy" }],
      });

      expect(afterUpgrade.json).toMatchObject({ inserted: 0, duplicates: 1 });
      expect(await rows()).toBe(1);
      expect(await rolledLines()).toBe(10);
    });

    it("accepts a batch mixing legacy and new events", async () => {
      // The realistic first sync after an upgrade: a backlog queued before the
      // change, plus events captured after it, in one batch.
      await post({ events: [ev({ id: 41 }), ev({ id: 42 })] }); // pre-upgrade, ACK lost

      const mixed = await post({
        source_id: "brandnewinstall",
        events: [
          { ...ev({ id: 41 }), source_id: "legacy" }, // re-sent backlog
          { ...ev({ id: 42 }), source_id: "legacy" }, // re-sent backlog
          ev({ id: 43 }), // captured after the upgrade -> batch default
          ev({ id: 44 }),
        ],
      });

      expect(mixed.json).toMatchObject({ inserted: 2, duplicates: 2, skipped: 0 });
      expect(await rows()).toBe(4);

      const bySource = await env.DB.prepare(
        "SELECT source_id, COUNT(*) AS n FROM events GROUP BY source_id ORDER BY source_id"
      ).all();
      expect(bySource.results).toEqual([
        { source_id: "brandnewinstall", n: 2 },
        { source_id: "legacy", n: 2 },
      ]);
    });

    it("lets a per-event source_id override the batch default in both directions", async () => {
      await post({ source_id: "machine-a", events: [ev({ id: 1 })] });
      // Same rowid, same batch default, different per-event namespace: distinct.
      const other = await post({
        source_id: "machine-a",
        events: [{ ...ev({ id: 1 }), source_id: "machine-b" }],
      });
      expect(other.json).toMatchObject({ inserted: 1 });
      expect(await rows()).toBe(2);
    });

    it("rejects a malformed per-event source_id instead of silently relabelling it", async () => {
      const res = await post({
        source_id: "machine-a",
        events: [ev({ id: 1 }), { ...ev({ id: 2 }), source_id: "no" }],
      });
      expect(res.json).toMatchObject({ inserted: 1, skipped: 1 });
      const row = await env.DB.prepare("SELECT source_id FROM events").first();
      expect((row as { source_id: string }).source_id).toBe("machine-a");
    });
  });

  describe("source_id validation", () => {
    it("rejects a malformed source_id instead of folding it into legacy", async () => {
      for (const bad of ["a", "x".repeat(65), "has space", "semi;colon", "../../etc", "'; DROP--"]) {
        const res = await SELF.fetch(ingestRequest({ source_id: bad, events: [] }));
        expect(res.status, `source_id=${bad}`).toBe(400);
      }
    });

    it("rejects a non-string source_id", async () => {
      expect((await post({ source_id: 12345, events: [] })).status).toBe(400);
      expect((await post({ source_id: { a: 1 }, events: [] })).status).toBe(400);
    });

    it("accepts the hex token the hook generates", async () => {
      const res = await post({ source_id: "0123456789abcdef0123456789abcdef", events: [ev({ id: 1 })] });
      expect(res.status).toBe(200);
      expect(res.json).toMatchObject({ inserted: 1 });
    });
  });
});

describe("ingest rollups", () => {
  beforeEach(async () => {
    await resetDb();
  });

  it("folds only the events that actually landed into every rollup", async () => {
    await post({
      source_id: "machine-a",
      events: [
        ev({ id: 1, language: "Python", lines_added: 10, bytes_added: 100, ts: 1750000000 }),
        ev({ id: 2, language: "Python", lines_added: 5, bytes_added: 50, ts: 1750000000 }),
        ev({ id: 3, language: "Rust", lines_added: 7, bytes_added: 70, ts: 1750000000 }),
        ev({ id: 4, language: null, lines_added: 0, bytes_added: 0, event_type: "commit" }),
      ],
    });

    const langs = await env.DB.prepare("SELECT language, lines FROM agg_language ORDER BY language").all();
    expect(langs.results).toEqual([
      { language: "Python", lines: 15 },
      { language: "Rust", lines: 7 },
    ]);

    const types = await env.DB.prepare(
      "SELECT event_type, n FROM agg_event_type ORDER BY event_type"
    ).all();
    expect(types.results).toEqual([
      { event_type: "commit", n: 1 },
      { event_type: "edit", n: 3 },
    ]);

    const totals = await env.DB.prepare("SELECT bytes, events, first_ts FROM agg_totals WHERE id = 1").first();
    expect(totals).toMatchObject({ bytes: 220, events: 4, first_ts: 1750000000 });
  });

  it("only ever moves first_ts backwards", async () => {
    await post({ source_id: "machine-a", events: [ev({ id: 1, ts: 1750000000 })] });
    await post({ source_id: "machine-a", events: [ev({ id: 2, ts: 1760000000 })] });
    expect(await count("SELECT first_ts AS n FROM agg_totals WHERE id = 1")).toBe(1750000000);

    // A backfill carrying older events must pull it back.
    await post({ source_id: "machine-a", events: [ev({ id: 3, ts: 1700000000 })] });
    expect(await count("SELECT first_ts AS n FROM agg_totals WHERE id = 1")).toBe(1700000000);
  });

  it("keys agg_day by the worker's configured timezone, not by UTC", async () => {
    // 2025-06-15T23:30:00Z is still the 15th in Europe/Dublin (UTC+1 in June),
    // so this pins that the day key comes from Intl and not from the raw epoch.
    await post({ source_id: "machine-a", events: [ev({ id: 1, ts: 1750030200, lines_added: 3 })] });
    const day = await env.DB.prepare("SELECT day, lines FROM agg_day").first();
    expect(day).toMatchObject({ day: "2025-06-16", lines: 3 });
  });

  it("separates git-mode diffs from agent edits in the event-type rollup", async () => {
    await post({
      source_id: "machine-a",
      events: [
        ev({ id: 1, event_type: "edit" }),
        ev({ id: 2, event_type: "write" }),
        ev({ id: 3, event_type: "diff" }),
        ev({ id: 4, event_type: "commit", language: null, lines_added: 0 }),
      ],
    });
    const types = await env.DB.prepare(
      "SELECT event_type, n FROM agg_event_type ORDER BY event_type"
    ).all();
    expect(types.results).toEqual([
      { event_type: "commit", n: 1 },
      { event_type: "diff", n: 1 },
      { event_type: "edit", n: 1 },
      { event_type: "write", n: 1 },
    ]);
  });
});

describe("privacy invariants", () => {
  beforeEach(async () => {
    await resetDb();
  });

  it("has no column anywhere that could hold a path, filename or project name", async () => {
    // The product's central promise, asserted against the real schema rather
    // than against a comment.
    const cols = await env.DB.prepare("PRAGMA table_info(events)").all();
    const names = (cols.results as { name: string }[]).map((c) => c.name).sort();
    expect(names).toEqual([
      "bytes_added",
      "client_event_id",
      "event_type",
      "id",
      "language",
      "lines_added",
      "lines_removed",
      "source_id",
      "ts",
    ]);
  });

  it("drops unknown fields a client tries to smuggle in", async () => {
    await post({
      source_id: "machine-a",
      events: [{ ...ev({ id: 1 }), project_key: "C:/IA/secret-client", file_path: "/etc/passwd" }],
    });
    const row = await env.DB.prepare("SELECT * FROM events").first();
    expect(JSON.stringify(row)).not.toContain("secret-client");
    expect(JSON.stringify(row)).not.toContain("passwd");
  });
});
