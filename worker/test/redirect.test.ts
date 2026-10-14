import { createExecutionContext, env, SELF, waitOnExecutionContext } from "cloudflare:test";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import worker from "../src/index";
import { RETIRE_AT } from "../src/variants";
import { ev, ingestRequest, resetDb, WRONG_TOKEN } from "./helpers";

const REPO = "https://github.com/augbastos/devcard";
const RAW = "https://raw.githubusercontent.com/augbastos/devcard/devcard-data/";

async function call(path: string, method = "GET"): Promise<Response> {
  const ctx = createExecutionContext();
  const response = await worker.fetch(new Request(`https://card.example${path}`, { method }), env, ctx);
  await waitOnExecutionContext(ctx);
  return response;
}

afterEach(() => vi.useRealTimers());

describe("temporary public redirects", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(RETIRE_AT - 86400000);
  });

  it.each([
    ["", "card.svg"],
    ["?theme=light", "card.svg"],
    ["?theme=default", "card.svg"],
    ["?theme=dark", "card-dark.svg"],
    ["?theme=%64ark", "card-dark.svg"],
    ["?theme=gentle", "card.svg"],
    ["?theme=terminal", "card.svg"],
    ["?theme=cyberpunk", "card.svg"],
    ["?theme=unknown", "card.svg"],
    ["?theme=constructor", "card.svg"],
    ["?theme=__proto__", "card.svg"],
    ["?theme=toString", "card.svg"],
    ["?theme=hasOwnProperty", "card.svg"],
    ["?theme=", "card.svg"],
    ["?theme=DARK", "card.svg"],
    ["?theme=dark&theme=light", "card-dark.svg"],
    ["?theme=light&theme=dark", "card.svg"],
    ["?user=someone-else&lang=pt&layout=wide&part=seg&i=3&w=100000", "card.svg"],
    ["?theme=dark&user=someone-else&lang=es&layout=banner", "card-dark.svg"],
    ["?theme=https://example.org/card.svg&redirect=https://example.org", "card.svg"],
  ])("redirects /svg%s to %s", async (query, file) => {
    const response = await call(`/svg${query}`);
    expect(response.status).toBe(301);
    expect(response.headers.get("Location")).toBe(RAW + file);
    expect(response.headers.get("Cache-Control")).toBe("public, max-age=3600");
    expect(await response.text()).toBe("");
  });

  it.each(["/", "/?theme=dark", "/embed", "/embed?user=someone-else", "/embed/card", "/index.html", "/card.html?theme=dark"])(
    "redirects %s to the repository", async (path) => {
      const response = await call(path);
      expect(response.status).toBe(301);
      expect(response.headers.get("Location")).toBe(REPO);
    },
  );

  it("preserves HEAD redirect headers without a body", async () => {
    const response = await call("/svg?theme=dark", "HEAD");
    expect(response.status).toBe(301);
    expect(response.headers.get("Location")).toBe(RAW + "card-dark.svg");
    expect(response.headers.get("Cache-Control")).toBe("public, max-age=3600");
    expect(await response.text()).toBe("");
    expect((await call("/embed", "HEAD")).headers.get("Location")).toBe(REPO);
  });

  it("keeps unsupported methods and unknown paths at 404", async () => {
    for (const [path, method] of [["/svg", "POST"], ["/embed", "POST"], ["/", "POST"], ["/ingest", "GET"], ["/unknown", "GET"]]) {
      expect((await call(path, method)).status).toBe(404);
    }
  });

  it("redirects until the instant before RETIRE_AT", async () => {
    expect(RETIRE_AT).toBe(Date.parse("2027-01-14T00:00:00Z"));
    vi.setSystemTime(RETIRE_AT - 1);
    expect((await call("/svg")).status).toBe(301);
  });

  it.each([0, 1, 86400000])("returns 410 at RETIRE_AT + %i ms", async (offset) => {
    vi.setSystemTime(RETIRE_AT + offset);
    for (const path of ["/svg", "/svg?theme=dark", "/svg?user=unknown&part=seg"]) {
      const response = await call(path);
      expect(response.status).toBe(410);
      expect(response.headers.get("Content-Type")).toBe("text/plain; charset=utf-8");
      expect(response.headers.get("Location")).toBeNull();
      expect(await response.text()).toContain(REPO);
    }
    const head = await call("/svg", "HEAD");
    expect(head.status).toBe(410);
    expect(await head.text()).toBe("");
    expect((await call("/embed")).headers.get("Location")).toBe(REPO);
  });
});

describe("ingest during and after the redirect window", () => {
  beforeEach(resetDb);

  it.each([RETIRE_AT - 1, RETIRE_AT + 1])("keeps ingest and fail-closed auth at time %i", async (now) => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(now);
    const batch = { source_id: "redirect-test", events: [ev({ id: 1 })] };
    const ctx = createExecutionContext();
    const first = await worker.fetch(ingestRequest(batch), env, ctx);
    expect(first.status).toBe(200);
    expect(await first.json()).toEqual({ inserted: 1, skipped: 0, duplicates: 0 });
    const duplicate = await worker.fetch(ingestRequest(batch), env, ctx);
    expect(await duplicate.json()).toEqual({ inserted: 0, skipped: 0, duplicates: 1 });
    expect((await worker.fetch(ingestRequest(batch, WRONG_TOKEN), env, ctx)).status).toBe(401);
    expect((await worker.fetch(ingestRequest(batch), { ...env, INGEST_TOKEN: "" }, ctx)).status).toBe(503);
    await waitOnExecutionContext(ctx);
    expect(await env.DB.prepare("SELECT events FROM agg_totals WHERE id = 1").first("events")).toBe(1);
  });

  it("serves the compatibility response through the deployed handler", async () => {
    // SELF has a separate clock: assert the applicable response without relying
    // on this test module's injected Date.
    const response = await SELF.fetch("https://card.example/svg?theme=dark", { redirect: "manual" });
    if (Date.now() < RETIRE_AT) {
      expect(response.status).toBe(301);
      expect(response.headers.get("Location")).toBe(RAW + "card-dark.svg");
    } else {
      expect(response.status).toBe(410);
    }
  });
});
