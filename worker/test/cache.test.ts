import { SELF, env } from "cloudflare:test";
import { beforeEach, describe, expect, it } from "vitest";
import { resetDb, ev, ingestRequest, purgeCardCache } from "./helpers";

const EN = { "Accept-Language": "en-US,en;q=0.9" };
const EN_GB = { "Accept-Language": "en-GB,en;q=0.7" };
const PT = { "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8" };
const ES = { "Accept-Language": "es-ES,es;q=0.9" };

async function seed(): Promise<void> {
  const res = await SELF.fetch(
    ingestRequest({
      events: [ev({ id: 1, language: "Python", lines_added: 120 })],
      repo_count: 40,
      source_id: "cachetest",
    })
  );
  expect(res.status).toBe(200);
}

/** Bump a rollup behind the Worker's back — a later render that still shows the
 *  old number proves it came from cache, not from D1. */
async function bumpLines(): Promise<void> {
  await env.DB.prepare(
    "UPDATE agg_language SET lines = lines + 1000 WHERE language = 'Python'"
  ).run();
}

async function body(query = "", headers: Record<string, string> = {}): Promise<string> {
  const res = await SELF.fetch(`https://card.example/svg${query}`, { headers });
  expect(res.status).toBe(200);
  return res.text();
}

describe("cache key", () => {
  beforeEach(async () => {
    await resetDb();
    await seed();
  });

  describe("language separation", () => {
    it("serves English to an English visitor on the bare URL", async () => {
      expect(await body("", EN)).toContain("lines written");
    });

    it("serves Portuguese to a Portuguese visitor on the same bare URL", async () => {
      expect(await body("", PT)).toContain("linhas escritas");
    });

    it("does not let the first English request contaminate a Portuguese one", async () => {
      // This is the regression: the previous key was the raw request URL, so
      // whoever asked first froze that language into the entry for everyone.
      const en = await body("", EN);
      const pt = await body("", PT);
      const es = await body("", ES);
      expect(en).toContain("lines written");
      expect(pt).toContain("linhas escritas");
      expect(es).toContain("líneas escritas");
      expect(pt).not.toContain("lines written");
      expect(es).not.toContain("linhas escritas");
    });

    it("does not let the first Portuguese request contaminate an English one", async () => {
      const pt = await body("", PT);
      const en = await body("", EN);
      expect(pt).toContain("linhas escritas");
      expect(en).toContain("lines written");
    });

    it("keeps ?lang= deterministic regardless of the visitor's header", async () => {
      expect(await body("?lang=pt", EN)).toContain("linhas escritas");
      expect(await body("?lang=en", PT)).toContain("lines written");
      expect(await body("?lang=es", PT)).toContain("líneas escritas");
    });

    it("ranks Accept-Language by q-value, not by position", async () => {
      const out = await body("", { "Accept-Language": "en;q=0.3, pt;q=0.9" });
      expect(out).toContain("linhas escritas");
    });

    it("treats q=0 as a refusal, not a weak preference", async () => {
      // RFC 9110: q=0 means "not acceptable". Serving it would give the visitor
      // the one language they explicitly refused.
      const out = await body("", { "Accept-Language": "pt;q=0, de;q=0.9" });
      expect(out).toContain("lines written");
      expect(out).not.toContain("linhas escritas");
    });

    it("falls back to English for a header with no language it speaks", async () => {
      expect(await body("", { "Accept-Language": "de-DE,de;q=0.9,fr;q=0.8" })).toContain(
        "lines written"
      );
    });
  });

  describe("variant independence", () => {
    it("keeps themes independent", async () => {
      const terminal = await body("?theme=terminal");
      const gentle = await body("?theme=gentle");
      expect(terminal).toContain("#39ff6a");
      expect(gentle).not.toContain("#39ff6a");
    });

    it("keeps layouts independent", async () => {
      expect(await body("?layout=banner")).toContain('height="72"');
      expect(await body("?layout=half")).toContain('height="152"');
    });

    it("keeps a theme+lang combination from colliding with either alone", async () => {
      const a = await body("?theme=terminal&lang=pt");
      const b = await body("?theme=terminal&lang=en");
      expect(a).toContain("linhas escritas");
      expect(b).toContain("lines written");
      expect(a).toContain("#39ff6a");
      expect(b).toContain("#39ff6a");
    });
  });

  describe("hits and fragmentation", () => {
    it("serves a repeat request from cache", async () => {
      const first = await body("", EN);
      await bumpLines();
      const second = await body("", EN);
      expect(second).toBe(first);
    });

    it("re-renders once the entry is purged", async () => {
      const first = await body("", EN);
      await bumpLines();
      await purgeCardCache();
      const second = await body("", EN);
      expect(second).not.toBe(first);
    });

    it("does not fragment on Accept-Language values that resolve to the same language", async () => {
      // `en-US,en;q=0.9` and `en-GB,en;q=0.7` are two verbatim header values
      // and would have been two cache entries under `Vary: Accept-Language`.
      const first = await body("", EN);
      await bumpLines();
      expect(await body("", EN_GB)).toBe(first);
    });

    it("does not fragment on query parameters that change nothing", async () => {
      const first = await body("", EN);
      await bumpLines();
      expect(await body("?nonsense=1&v=2", EN)).toBe(first);
      expect(await body("?user=augbastos", EN)).toBe(first);
      // Invalid values collapse onto the default they render as.
      expect(await body("?theme=nope&layout=nope", EN)).toBe(first);
    });

    it("still 404s an unknown user before consulting the cache", async () => {
      await body("", EN);
      const res = await SELF.fetch("https://card.example/svg?user=someone-else", { headers: EN });
      expect(res.status).toBe(404);
    });
  });

  it("keeps Vary: Accept-Language for caches downstream of the Worker", async () => {
    const res = await SELF.fetch("https://card.example/svg", { headers: EN });
    expect(res.headers.get("Vary")).toBe("Accept-Language");
    expect(res.headers.get("Cache-Control")).toContain("s-maxage=300");
  });
});
