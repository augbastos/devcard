// Golden SVGs: the reference output the Python renderer (devcard/) is held to.
//
// Each fixture in tests/golden/fixtures.json is a list of events. They go in
// through the real /ingest — so the rollups the card reads are built by the
// Worker's own code — and every listed variant is rendered through the real
// /svg with the clock pinned. The Python suite renders the same fixtures from a
// local SQLite and must produce the same files (tests/test_golden.py).
//
// Regenerate after an intentional renderer change with
//   npx vitest run test/golden.test.ts -u
// and commit the diff together with the matching change in devcard/render.py.
import { createExecutionContext, env, waitOnExecutionContext } from "cloudflare:test";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import worker from "../src/index";
import golden from "../../tests/golden/fixtures.json";
import { resetDb, ingestRequest } from "./helpers";

interface FixtureEvent {
  ts: number;
  language: string | null;
  lines_added: number;
  lines_removed: number;
  bytes_added: number;
  event_type: string;
}

interface Fixture {
  events: FixtureEvent[];
  repo_count: number;
  updated_at: number;
  badges?: { kind: string; label: string }[];
  pins?: { repo: string; note: string | null; stars: number | null }[];
}

interface Variant {
  fixture: string;
  layout: string;
  theme: string;
  lang: string;
  langs?: string;
}

const fixtures = golden.fixtures as Record<string, Fixture>;
const variants = golden.variants as Variant[];

function goldenName(v: Variant): string {
  return `${v.fixture}/${v.layout}-${v.theme}-${v.lang}${v.langs === "all" ? "-all" : ""}.svg`;
}

async function call(request: Request): Promise<Response> {
  const ctx = createExecutionContext();
  const res = await worker.fetch(request, env, ctx);
  await waitOnExecutionContext(ctx);
  return res;
}

async function load(fixture: Fixture): Promise<void> {
  await resetDb();
  // Ingest stamps `updated_at` with the clock, so the clock is set to the
  // fixture's sync time for the batch that carries the repo count.
  for (let i = 0; i < fixture.events.length; i += 100) {
    const events = fixture.events.slice(i, i + 100).map((e, j) => ({ ...e, id: i + j + 1 }));
    const res = await call(ingestRequest({ events, source_id: "goldenfixture" }));
    expect(res.status).toBe(200);
  }
  if (fixture.updated_at) {
    vi.setSystemTime(fixture.updated_at * 1000);
    const res = await call(ingestRequest({ events: [], repo_count: fixture.repo_count, source_id: "goldenfixture" }));
    expect(res.status).toBe(200);
  }
  for (const [i, b] of (fixture.badges ?? []).entries()) {
    // Newest first is the card's order; created_at counts down to keep the listed one.
    await env.DB.prepare("INSERT INTO profile_entries (kind, label, detail, created_at) VALUES (?, ?, NULL, ?)")
      .bind(b.kind, b.label, 1000 - i)
      .run();
  }
  for (const [i, p] of (fixture.pins ?? []).entries()) {
    await env.DB.prepare("INSERT INTO pinned_repos (repo, note, position, created_at) VALUES (?, ?, ?, 0)")
      .bind(p.repo, p.note, i)
      .run();
  }
  vi.setSystemTime(golden.now * 1000);
}

describe("golden SVGs", () => {
  beforeAll(() => {
    // Only Date: faking timers too would stall workerd's own I/O.
    vi.useFakeTimers({ toFake: ["Date"] });
  });
  afterAll(() => {
    vi.useRealTimers();
  });

  for (const name of Object.keys(fixtures)) {
    const own = variants.filter((v) => v.fixture === name);
    it(`renders every variant of the ${name} fixture`, async () => {
      await load(fixtures[name]);
      for (const v of own) {
        const query = new URLSearchParams({ lang: v.lang, theme: v.theme, layout: v.layout });
        if (v.langs) query.set("langs", v.langs);
        const res = await call(new Request(`https://card.example/svg?${query}`));
        expect(res.status).toBe(200);
        await expect(await res.text()).toMatchFileSnapshot(`../../tests/golden/${goldenName(v)}`);
      }
    });
  }
});
