import { SELF, env } from "cloudflare:test";
import { beforeEach, describe, expect, it } from "vitest";
import { resetDb, ev, ingestRequest, TOKEN, WRONG_TOKEN } from "./helpers";

async function seed(): Promise<void> {
  const res = await SELF.fetch(
    ingestRequest({
      events: [
        ev({ id: 1, language: "Python", lines_added: 120 }),
        ev({ id: 2, language: "TypeScript", lines_added: 80 }),
        ev({ id: 3, language: null, lines_added: 0, event_type: "commit" }),
      ],
      repo_count: 40,
      source_id: "seedsource",
    })
  );
  expect(res.status).toBe(200);
}

describe("/svg rendering", () => {
  beforeEach(async () => {
    await resetDb();
    await seed();
  });

  it("renders a well-formed SVG for the default request", async () => {
    const res = await SELF.fetch("https://card.example/svg");
    expect(res.status).toBe(200);
    expect(res.headers.get("Content-Type")).toContain("image/svg+xml");
    const body = await res.text();
    expect(body.startsWith("<svg")).toBe(true);
    expect(body.trimEnd().endsWith("</svg>")).toBe(true);
    expect(body).toContain("lines written");
  });

  it("404s a user that is not the configured owner", async () => {
    const res = await SELF.fetch("https://card.example/svg?user=someone-else");
    expect(res.status).toBe(404);
  });

  it("answers HEAD with the real headers and no body", async () => {
    const res = await SELF.fetch("https://card.example/svg", { method: "HEAD" });
    expect(res.status).toBe(200);
    expect(res.headers.get("Content-Type")).toContain("image/svg+xml");
    expect(await res.text()).toBe("");
  });

  describe("hostile query parameters", () => {
    // `THEMES[name]` and `STRINGS[tag]` are plain-object indexings: without an
    // own-property guard, "constructor" resolves to Object.prototype.constructor
    // and the render either 500s (theme) or paints "undefined" (lang).
    const hostile = ["constructor", "__proto__", "prototype", "toString", "hasOwnProperty", ""];

    for (const value of hostile) {
      it(`falls back to the default theme for ?theme=${value || "(empty)"}`, async () => {
        const res = await SELF.fetch(`https://card.example/svg?theme=${encodeURIComponent(value)}`);
        expect(res.status).toBe(200);
        const body = await res.text();
        // The default theme is the only one that emits a dark-mode block.
        expect(body).toContain("prefers-color-scheme:dark");
        expect(body).not.toContain("undefined");
      });

      it(`falls back to English for ?lang=${value || "(empty)"}`, async () => {
        const res = await SELF.fetch(`https://card.example/svg?lang=${encodeURIComponent(value)}`);
        expect(res.status).toBe(200);
        const body = await res.text();
        expect(body).toContain("lines written");
        expect(body).not.toContain("undefined");
      });

      it(`falls back to the full layout for ?layout=${value || "(empty)"}`, async () => {
        const res = await SELF.fetch(`https://card.example/svg?layout=${encodeURIComponent(value)}`);
        expect(res.status).toBe(200);
        const body = await res.text();
        expect(body).toContain('width="480"');
        expect(body).not.toContain("undefined");
      });
    }

    it("ignores a hostile Accept-Language and still renders English", async () => {
      const res = await SELF.fetch("https://card.example/svg", {
        headers: { "Accept-Language": "constructor,__proto__;q=0.9,toString;q=0.8" },
      });
      expect(res.status).toBe(200);
      const body = await res.text();
      expect(body).toContain("lines written");
      expect(body).not.toContain("undefined");
    });
  });

  describe("themes and layouts", () => {
    it("serves each named theme with its own palette", async () => {
      const terminal = await (await SELF.fetch("https://card.example/svg?theme=terminal")).text();
      const cyberpunk = await (await SELF.fetch("https://card.example/svg?theme=cyberpunk")).text();
      expect(terminal).toContain("#39ff6a");
      expect(cyberpunk).toContain("#ece8ff");
      expect(terminal).not.toEqual(cyberpunk);
      // Single-look themes deliberately have no dark override.
      expect(terminal).not.toContain("prefers-color-scheme:dark");
    });

    it("serves each layout at its documented width", async () => {
      const sizes: [string, string][] = [
        ["banner", 'width="480" height="72"'],
        ["half", 'width="480" height="152"'],
        ["vertical", 'width="280"'],
      ];
      for (const [layout, marker] of sizes) {
        const body = await (await SELF.fetch(`https://card.example/svg?layout=${layout}`)).text();
        expect(body).toContain(marker);
      }
    });
  });

  describe("XML escaping", () => {
    it("escapes badge labels, repo names and notes", async () => {
      await env.DB.prepare(
        "INSERT INTO profile_entries (kind, label, detail, created_at) VALUES (?, ?, NULL, 0)"
      )
        .bind("badge", '<script>&"x"')
        .run();
      await env.DB.prepare(
        "INSERT INTO pinned_repos (repo, note, position, created_at) VALUES (?, ?, 0, 0)"
      )
        .bind('evil"repo', "<b>note</b>")
        .run();

      const body = await (await SELF.fetch("https://card.example/svg?nocache=escape")).text();
      expect(body).not.toContain("<script>");
      expect(body).toContain("&lt;script&gt;");
      // The repo name lands inside an href attribute too — a raw quote there
      // would break out of the attribute.
      expect(body).not.toContain('evil"repo');
      expect(body).toContain("evil&quot;repo");
    });
  });

  describe("rollup-backed numbers", () => {
    it("reports the languages, totals and repo count that were ingested", async () => {
      const body = await (await SELF.fetch("https://card.example/svg")).text();
      expect(body).toContain("200"); // 120 + 80 lines
      expect(body).toContain("Python");
      expect(body).toContain("TypeScript");
      expect(body).toContain("40 repos");
    });

    it("renders an empty account without dividing by zero", async () => {
      await resetDb();
      const res = await SELF.fetch("https://card.example/svg?nocache=empty");
      expect(res.status).toBe(200);
      const body = await res.text();
      expect(body).not.toContain("NaN");
      expect(body).not.toContain("undefined");
    });
  });

  it("rejects unknown paths", async () => {
    expect((await SELF.fetch("https://card.example/")).status).toBe(404);
    expect((await SELF.fetch("https://card.example/ingest")).status).toBe(404);
  });
});

describe("ingest guard rails", () => {
  beforeEach(async () => {
    await resetDb();
  });

  it("rejects a missing or wrong token", async () => {
    expect((await SELF.fetch(ingestRequest({ events: [] }, WRONG_TOKEN))).status).toBe(401);
    const noToken = new Request("https://card.example/ingest", {
      method: "POST",
      body: JSON.stringify({ events: [] }),
    });
    expect((await SELF.fetch(noToken)).status).toBe(401);
  });

  it("rejects malformed JSON", async () => {
    const res = await SELF.fetch(ingestRequest(null, TOKEN, "{not json"));
    expect(res.status).toBe(400);
  });

  it("rejects a non-array events field", async () => {
    expect((await SELF.fetch(ingestRequest({ events: {} }))).status).toBe(400);
  });

  it("rejects a batch above the documented limit", async () => {
    const events = Array.from({ length: 101 }, (_, i) => ev({ id: i + 1 }));
    expect((await SELF.fetch(ingestRequest({ events }))).status).toBe(400);
  });

  it("rejects an oversized body even when Content-Length lies", async () => {
    const big = "x".repeat(300 * 1024);
    const req = new Request("https://card.example/ingest", {
      method: "POST",
      headers: { "X-Devcard-Token": TOKEN, "Content-Length": "10" },
      body: JSON.stringify({ events: [], pad: big }),
    });
    expect((await SELF.fetch(req)).status).toBe(413);
  });

  it("skips implausible events instead of erroring", async () => {
    const res = await SELF.fetch(
      ingestRequest({
        source_id: "abcd1234",
        events: [
          ev({ id: 1, lines_added: 999999 }), // above the per-event cap
          ev({ id: 2, ts: 5 }), // before the sane window
          ev({ id: 3, event_type: "drop table" }), // not a known type
          ev({ id: 4, lines_added: -1 }),
          ev({ id: 5, language: "x".repeat(64) }),
          ev({ id: 6 }), // the one good event
        ],
      })
    );
    expect(res.status).toBe(200);
    expect(await res.json()).toMatchObject({ inserted: 1, skipped: 5 });
  });

  it("ignores an out-of-range repo_count instead of publishing it", async () => {
    await SELF.fetch(ingestRequest({ events: [], repo_count: 999999, source_id: "abcd1234" }));
    const row = await env.DB.prepare("SELECT repo_count FROM stats_snapshot WHERE id = 1").first();
    expect((row as { repo_count: number }).repo_count).toBe(0);
  });
});
