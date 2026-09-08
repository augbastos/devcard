import { SELF } from "cloudflare:test";
import { beforeEach, describe, expect, it } from "vitest";
import { resetDb, ev, ingestRequest } from "./helpers";
import { withOtherBucket, OTHER_LANGUAGE, NAMED_LANGUAGES } from "../src/queries";

/** The real distribution from the deployed card: 18 languages, a long tail. */
const REAL = [
  ["Python", 368407], ["Markdown", 157027], ["TypeScript", 128728], ["HTML", 90688],
  ["JavaScript", 44684], ["PowerShell", 24480], ["JSON", 23383], ["CSS", 15806],
  ["SQL", 13835], ["YAML", 5919], ["Rust", 5239], ["Go", 2529], ["Shell", 1329],
  ["C++", 1118], ["TOML", 759], ["C", 456], ["Java", 103], ["Ruby", 8],
] as const;

const slices = (pairs: readonly (readonly [string, number])[]) =>
  pairs.map(([language, total]) => ({ language, total }));

describe("withOtherBucket", () => {
  it("collapses everything past the named languages into one slice", () => {
    const out = withOtherBucket(slices(REAL));
    expect(out).toHaveLength(NAMED_LANGUAGES + 1);
    const other = out[out.length - 1];
    expect(other.isOther).toBe(true);
    expect(other.language).toBe(OTHER_LANGUAGE);
  });

  it("preserves the total exactly — collapsing must not change any number", () => {
    const before = REAL.reduce((s, [, n]) => s + n, 0);
    const after = withOtherBucket(slices(REAL)).reduce((s, l) => s + l.total, 0);
    expect(after).toBe(before);
  });

  it("records what went into the bucket, most lines first", () => {
    const out = withOtherBucket(slices(REAL));
    const other = out[out.length - 1];
    expect(other.members?.[0]).toBe("JSON");
    expect(other.members).toHaveLength(REAL.length - NAMED_LANGUAGES);
  });

  it("names a single leftover language instead of calling it 'other'", () => {
    // Seven languages: bucketing one item would hide a name to save nothing.
    const seven = slices(REAL.slice(0, 7));
    const out = withOtherBucket(seven);
    expect(out).toHaveLength(7);
    expect(out.some((l) => l.isOther)).toBe(false);
  });

  it("leaves a short list untouched", () => {
    const three = slices(REAL.slice(0, 3));
    expect(withOtherBucket(three)).toEqual(three);
  });

  it("drops a tail that is all zeroes rather than adding an empty slice", () => {
    const padded = [...slices(REAL.slice(0, 6)), ...[1, 2, 3].map((i) => ({ language: `Z${i}`, total: 0 }))];
    const out = withOtherBucket(padded);
    expect(out).toHaveLength(6);
    expect(out.some((l) => l.isOther)).toBe(false);
  });

  it("handles an empty list", () => {
    expect(withOtherBucket([])).toEqual([]);
  });
});

describe("the card names every part of its language bar", () => {
  beforeEach(async () => {
    await resetDb();
    // Six named languages plus a tail of six more, mirroring the real account.
    const events = REAL.slice(0, 12).map(([language, total], i) =>
      ev({ id: i + 1, language, lines_added: Math.max(1, Math.round(total / 1000)) })
    );
    const res = await SELF.fetch(
      ingestRequest({ source_id: "langtest", events, repo_count: 40 })
    );
    expect(res.status).toBe(200);
  });

  const card = async (query = "") =>
    (await SELF.fetch(`https://card.example/svg${query}`)).text();

  it("shows an Other entry in the legend of the full layout", async () => {
    const svg = await card();
    expect(svg).toContain(">other<");
  });

  it("gives every bar segment a hover target, however thin the segment is", async () => {
    // Measured on the deployed card, the tail runs to 0.05px and 0.00px wide.
    // The visible bar keeps those exact proportions; the hover layer widens
    // only the invisible target so a pointer has somewhere to land.
    const svg = await card();
    const hits = [...svg.matchAll(/<rect class="hit"[^>]*width="([\d.]+)"[^>]*aria-label="([^"]+)"/g)];
    // One target per LANGUAGE, not per legend row: the bar keeps the whole tail
    // so the thin ones stay visible and pointable.
    expect(hits.length).toBe(12);
    for (const [, width, label] of hits) {
      expect(Number(width), `"${label}" is unhittable`).toBeGreaterThanOrEqual(3);
    }
    // and they tile the bar exactly rather than overlapping each other
    const total = hits.reduce((sum, h) => sum + Number(h[1]), 0);
    expect(total).toBeCloseTo(432, 0);
  });

  it("names the tail languages that the legend groups away", async () => {
    const svg = await card();
    for (const language of ["JSON", "CSS", "SQL", "YAML", "Rust", "Go"]) {
      expect(svg, `${language} must be reachable on the bar`).toContain(`aria-label="${language} `);
    }
    // ...while the legend still shows only six names plus the group.
    expect(svg).toContain(">other<");
  });

  it("keeps the visible bar at exact proportions, unwidened", async () => {
    const svg = await card();
    const visible = [...svg.matchAll(/<rect x="[\d.]+" y="130" width="([\d.]+)"[^>]*fill="#/g)].map(
      (m) => Number(m[1])
    );
    expect(visible.length).toBe(12);
    // The bar is 432px wide; widths must still sum to it, not to a padded
    // total — the hover layer borrows no pixels from what is drawn.
    expect(visible.reduce((a, b) => a + b, 0)).toBeCloseTo(432, 0);
    // and the thinnest drawn segment really is narrower than a hover target
    // can be — which is the entire reason the hover layer exists.
    expect(Math.min(...visible)).toBeLessThan(3);
  });

  it("names each slice with its percentage in the hover label", async () => {
    const svg = await card();
    expect(svg).toMatch(/aria-label="Python 4[0-9]\.[0-9]%"/);
    // The bar names real languages, never the legend's grouping.
    expect(svg).toMatch(/aria-label="Go [0-9.]+%"/);
    expect(svg).not.toMatch(/aria-label="other/);
  });

  it("localizes the Other label", async () => {
    expect(await card("?lang=pt")).toContain(">outras<");
    expect(await card("?lang=es")).toContain(">otras<");
  });

  it("keeps the headline total unchanged by the collapsing", async () => {
    const svg = await card();
    const expected = REAL.slice(0, 12).reduce((s, [, n]) => s + Math.max(1, Math.round(n / 1000)), 0);
    expect(svg).toContain(String(expected));
  });

  it("applies the same rule to the vertical layout", async () => {
    const svg = await card("?layout=vertical");
    expect(svg).toContain("Python");
  });
});

describe("wide layout", () => {
  beforeEach(async () => {
    await resetDb();
    const events = REAL.slice(0, 12).map(([language, total], i) =>
      ev({ id: i + 1, language, lines_added: Math.max(1, Math.round(total / 1000)) })
    );
    events.push(ev({ id: 99, language: null, lines_added: 0, event_type: "commit" }));
    await SELF.fetch(ingestRequest({ source_id: "widetest", events, repo_count: 40 }));
  });

  const wide = async (query = "") =>
    (await SELF.fetch(`https://card.example/svg?layout=wide${query}`)).text();

  it("is 840 wide, so it fills a GitHub README column", async () => {
    const svg = await wide();
    expect(svg).toContain('width="840"');
  });

  it("is a landscape card, not a blown-up portrait one", async () => {
    // The point is the shape: `full` is roughly square and leaves ~40% of a
    // README column empty beside it. Height is allowed to grow a little —
    // the heatmap cells are bigger — as long as the card reads as wide.
    const w = await wide();
    const f = await (await SELF.fetch("https://card.example/svg?layout=full")).text();
    const ratio = (s: string) =>
      Number(/width="(\d+)"/.exec(s)![1]) / Number(/height="(\d+)"/.exec(s)![1]);
    expect(ratio(w)).toBeGreaterThan(1.7);
    expect(ratio(w)).toBeGreaterThan(ratio(f) * 1.5);
  });

  it("keeps the type at full-card sizes rather than scaling everything up", async () => {
    // A 480px card stretched to 840px would carry 1.75x fonts. This must not.
    const w = await wide();
    const sizes = [...w.matchAll(/font-size="([\d.]+)"/g)].map((m) => Number(m[1]));
    expect(Math.max(...sizes)).toBeLessThanOrEqual(34);
  });

  it("renders a complete, well-formed SVG", async () => {
    const svg = await wide();
    expect(svg.startsWith("<svg")).toBe(true);
    expect(svg.trimEnd().endsWith("</svg>")).toBe(true);
    expect(svg).not.toContain("undefined");
    expect(svg).not.toContain("NaN");
  });

  it("carries the same content as the full card", async () => {
    const svg = await wide();
    for (const marker of ["Python", "lines written", "day streak", "repos", "commits"]) {
      expect(svg, marker).toContain(marker);
    }
    expect(svg).toContain('class="heat'); // heatmap
  });

  it("keeps the legend short and names the tail on hover instead", async () => {
    const svg = await wide();
    expect(svg).toContain(">other<");
    // The tail is reachable through the hover layer, not through the legend.
    expect(svg).toMatch(/<rect class="hit"/);
  });

  it("gives its own bar hover targets too", async () => {
    const svg = await wide();
    const hits = [...svg.matchAll(/<rect class="hit"[^>]*width="([\d.]+)"/g)].map((m) => Number(m[1]));
    expect(hits.length).toBe(12);
    for (const w of hits) expect(w).toBeGreaterThanOrEqual(3);
    expect(hits.reduce((a, b) => a + b, 0)).toBeCloseTo(784, 0);
  });

  it("honours theme and language like every other layout", async () => {
    expect(await wide("&theme=terminal")).toContain("#39ff6a");
    expect(await wide("&lang=pt")).toContain("linhas escritas");
    expect(await wide("&lang=es")).toContain("líneas escritas");
  });

  it("survives an empty account", async () => {
    await resetDb();
    const svg = await wide("&nocache=empty");
    expect(svg).not.toContain("undefined");
    expect(svg).not.toContain("NaN");
    expect(svg.trimEnd().endsWith("</svg>")).toBe(true);
  });

  it("escapes pinned repo names and badge labels", async () => {
    const { env } = await import("cloudflare:test");
    await env.DB.prepare(
      "INSERT INTO pinned_repos (repo, note, position, created_at) VALUES (?, ?, 0, 0)"
    )
      .bind('evil"repo', "<b>x</b>")
      .run();
    await env.DB.prepare(
      "INSERT INTO profile_entries (kind, label, detail, created_at) VALUES ('badge', ?, NULL, 0)"
    )
      .bind("<script>")
      .run();
    const svg = await wide("&nocache=escape");
    expect(svg).not.toContain("<script>");
    expect(svg).not.toContain('evil"repo');
  });

  it("gets its own cache entry, separate from full", async () => {
    const w = await wide();
    const f = await (await SELF.fetch("https://card.example/svg?layout=full")).text();
    expect(w).not.toBe(f);
  });
});
