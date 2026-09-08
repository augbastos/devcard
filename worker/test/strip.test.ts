// The split card: the only shape that gives a GitHub README a tooltip per
// language. Everything here guards a property the composition depends on —
// each one, if it broke, would show up as a visibly broken bar in someone's
// README rather than as a failed render.

import { SELF } from "cloudflare:test";
import { beforeEach, describe, expect, it } from "vitest";
import { resetDb, ev, ingestRequest } from "./helpers";
import { stripLayout, MIN_SEG, W, INNER, PAD } from "../src/render-split";
import { LanguageSlice } from "../src/queries";

const BASE = "https://card.example";

/** A realistic distribution: a few big languages and a tail that is invisible
 *  at exact proportion — the case the whole feature exists for. */
const TAIL: Array<[string, number]> = [
  ["Python", 41800],
  ["Markdown", 17700],
  ["TypeScript", 14600],
  ["HTML", 10200],
  ["JavaScript", 5000],
  ["PowerShell", 2800],
  ["JSON", 2600],
  ["CSS", 1800],
  ["SQL", 1600],
  ["YAML", 700],
  ["Rust", 600],
  ["Go", 300],
  ["Shell", 150],
  ["C++", 130],
  ["TOML", 90],
  ["C", 50],
  ["Java", 10],
  ["Ruby", 4],
];

function slices(rows: Array<[string, number]> = TAIL): LanguageSlice[] {
  return rows.map(([language, total]) => ({ language, total }) as LanguageSlice);
}

export const TOTAL_LINES = TAIL.reduce((a, [, n]) => a + n, 0);

/** One event may carry at most MAX_LINES_PER_EVENT lines, so a language whose
 *  total is bigger than that arrives as several events — which is how a real
 *  hook sends it anyway. */
async function seed(): Promise<void> {
  const events: ReturnType<typeof ev>[] = [];
  for (const [language, total] of TAIL) {
    let left = total;
    while (left > 0) {
      const chunk = Math.min(left, 20000);
      events.push(ev({ id: events.length + 1, language, lines_added: chunk }));
      left -= chunk;
    }
  }
  const res = await SELF.fetch(
    ingestRequest({ events, repo_count: 44, source_id: "stripseed" })
  );
  expect(res.status).toBe(200);
  expect((await res.json<{ inserted: number }>()).inserted).toBe(events.length);
}

function imgTags(html: string): string[] {
  return html.match(/<img [^>]*>/g) ?? [];
}

function attr(tag: string, name: string): string | null {
  const m = tag.match(new RegExp(`${name}="([^"]*)"`));
  return m ? m[1] : null;
}

describe("strip layout", () => {
  it("adds up to exactly 100% of the card", () => {
    const strip = stripLayout(slices(), TOTAL_LINES);
    // In ten-thousandths, because that is the precision the markup carries and
    // summing the floats back drifts past 100 on its own.
    const tt = (n: number) => Math.round(n * 1e4);
    const total =
      tt(strip.capLeftPct) + tt(strip.capRightPct) + strip.slots.reduce((a, s) => a + tt(s.pct), 0);
    // A hair over 100% and the last image wraps onto its own line, which is the
    // one failure that actually looks broken rather than merely imprecise.
    expect(total).toBe(1e6);
  });

  it("gives every language a slice a pointer can land on", () => {
    const strip = stripLayout(slices(), TOTAL_LINES);
    expect(strip.slots).toHaveLength(TAIL.length);
    for (const slot of strip.slots) {
      expect(slot.width).toBeGreaterThanOrEqual(MIN_SEG - 0.01);
    }
    // Ruby is 0.004% of the total — 0.03px if drawn honestly.
    const ruby = strip.slots[strip.slots.length - 1];
    expect(ruby.slice.language).toBe("Ruby");
    expect((ruby.share * INNER)).toBeLessThan(1);
    expect(ruby.width).toBeGreaterThanOrEqual(MIN_SEG - 0.01);
  });

  it("takes the floor's pixels out of the segments that have them to spare", () => {
    const strip = stripLayout(slices(), TOTAL_LINES);
    const drawn = strip.slots.reduce((a, s) => a + s.width, 0);
    expect(drawn).toBeGreaterThan(INNER - 1);
    expect(drawn).toBeLessThan(INNER + 1);
    // Python pays the most, and still loses under two points of the card.
    const python = strip.slots[0];
    expect(python.share * INNER - python.width).toBeGreaterThan(0);
    expect((python.share * INNER - python.width) / W * 100).toBeLessThan(2);
  });

  it("reports the true share, whatever the floor did to the pixels", () => {
    const strip = stripLayout(slices(), TOTAL_LINES);
    const sum = strip.slots.reduce((a, s) => a + s.share, 0);
    expect(sum).toBeCloseTo(1, 6);
    expect(strip.slots[0].share).toBeCloseTo(41800 / TOTAL_LINES, 6);
  });

  it("survives a card with no languages at all", () => {
    const strip = stripLayout([], 0);
    expect(strip.slots).toHaveLength(0);
    expect(strip.capLeftPct + strip.capRightPct).toBeCloseTo(100, 4);
  });

  it("shrinks the floor rather than overflowing when there are too many languages", () => {
    const many = Array.from({ length: 400 }, (_, i) => [`L${i}`, 1] as [string, number]);
    const strip = stripLayout(slices(many), 400);
    const total = strip.slots.reduce((a, s) => a + s.pct, 0) + strip.capLeftPct + strip.capRightPct;
    expect(total).toBeLessThanOrEqual(100);
    expect(strip.slots.every((s) => s.width > 0)).toBe(true);
  });
});

describe("/embed", () => {
  beforeEach(async () => {
    await resetDb();
    await seed();
  });

  it("emits a body, two caps and one image per language", async () => {
    const res = await SELF.fetch(`${BASE}/embed`);
    expect(res.status).toBe(200);
    const tags = imgTags(await res.text());
    expect(tags).toHaveLength(1 + 2 + TAIL.length);
    expect(tags[0]).toContain("part=body");
    expect(tags[1]).toContain("part=cap&amp;side=l");
    expect(tags[tags.length - 1]).toContain("part=cap&amp;side=r");
  });

  it("puts no whitespace between the images", async () => {
    const html = (await (await SELF.fetch(`${BASE}/embed`)).text()).trim();
    // A newline between two inline images renders as a space, and a space in
    // the bar is a visible gap between two languages.
    expect(html).not.toMatch(/>\s+<img/);
    expect(html.split("\n")).toHaveLength(1);
  });

  it("names every language and its share in a title", async () => {
    const tags = imgTags(await (await SELF.fetch(`${BASE}/embed`)).text());
    const titles = tags.map((t) => attr(t, "title")).filter(Boolean) as string[];
    expect(titles).toHaveLength(TAIL.length);
    expect(titles[0]).toMatch(/^Python \d+\.\d%$/);
    expect(titles).toContain("Ruby 0.0%");
    expect(titles.some((t) => t.startsWith("C++"))).toBe(true);
  });

  it("stacks every piece with align=top", async () => {
    // align=left would stack without a seam too, but GitHub's CSS gives
    // img[align=left] a 20px right padding, which blows the bar apart.
    const tags = imgTags(await (await SELF.fetch(`${BASE}/embed`)).text());
    expect(tags.every((t) => attr(t, "align") === "top")).toBe(true);
  });

  it("emits widths that sum to the full column", async () => {
    const tags = imgTags(await (await SELF.fetch(`${BASE}/embed`)).text());
    const total = tags
      .slice(1)
      .map((t) => Math.round(Number((attr(t, "width") ?? "0").replace("%", "")) * 1e4))
      .reduce((a, b) => a + b, 0);
    // Exactly the column, in the precision the markup carries: a hair over and
    // the last slice wraps onto its own line.
    expect(total).toBe(1e6);
    expect(attr(tags[0], "width")).toBe("100%");
  });

  it("carries the whole breakdown in the body's alt text", async () => {
    const tags = imgTags(await (await SELF.fetch(`${BASE}/embed`)).text());
    const alt = attr(tags[0], "alt") ?? "";
    // The slices are decorative to a screen reader; the body says it all once.
    expect(alt).toContain("Python");
    expect(alt).toContain("Ruby");
    expect(tags.slice(1).every((t) => attr(t, "alt") === "")).toBe(true);
  });

  it("404s a user that is not the configured owner", async () => {
    expect((await SELF.fetch(`${BASE}/embed?user=someone-else`)).status).toBe(404);
  });
});

describe("/svg?part=", () => {
  beforeEach(async () => {
    await resetDb();
    await seed();
  });

  const get = async (q: string) => {
    const res = await SELF.fetch(`${BASE}/svg?layout=wide&${q}`);
    expect(res.status).toBe(200);
    return res.text();
  };

  it("serves a body with no language bar and a flat bottom", async () => {
    const body = await get("part=body");
    const full = await get("");
    expect(full).toContain('class="track"');
    expect(body).not.toContain('class="track"');
    expect(body).not.toContain('class="hit"');
    // Flat bottom: the frame is drawn taller than the viewBox so its bottom
    // corners fall off-canvas.
    const h = Number(body.match(/<svg[^>]*height="(\d+)"/)?.[1]);
    const frame = Number(body.match(/class="bg brd"[^>]*height="([\d.]+)"/)?.[1]);
    expect(frame).toBeGreaterThan(h);
  });

  it("serves each language its own colour", async () => {
    const python = await get("part=seg&i=0");
    const ruby = await get(`part=seg&i=${TAIL.length - 1}`);
    expect(python).toContain("#3572A5");
    expect(ruby).toContain("#701516");
    expect(python).not.toBe(ruby);
  });

  it("rounds only the outer end of the bar", async () => {
    const first = await get("part=seg&i=0");
    const middle = await get("part=seg&i=5");
    const last = await get(`part=seg&i=${TAIL.length - 1}`);
    expect(first).toMatch(/x="0"[^>]*rx="[1-9]/);
    expect(middle).toContain('rx="0"');
    expect(last).toMatch(/x="-14"/);
  });

  it("draws an empty slice for an index past the end", async () => {
    // A README holds the slice count in its markup, so it can outlive the data.
    // Thin out quietly; do not sprout broken-image boxes across the bar.
    const stale = await get("part=seg&i=200");
    expect(stale).toContain('class="bg"');
    expect(stale).not.toMatch(/fill="#[0-9a-fA-F]{6}"/);
  });

  it("keeps the two caps distinct", async () => {
    const left = await get("part=cap&side=l");
    const right = await get("part=cap&side=r");
    expect(left).toContain('x="0.5"');
    expect(right).toContain('x="-14"');
    expect(Number(left.match(/<svg[^>]*width="([\d.]+)"/)?.[1])).toBeCloseTo(PAD, 1);
  });

  it("caches every piece separately", async () => {
    // One path serves twenty images. A key that ignored `part` would hand the
    // whole card, or Python's slice, to all of them.
    const seen = new Set<string>();
    for (const q of ["part=body", "part=cap&side=l", "part=cap&side=r", "part=seg&i=0", "part=seg&i=1"]) {
      seen.add(await get(q));
    }
    expect(seen.size).toBe(5);
    // And a second read of the same piece is still that piece.
    expect(await get("part=seg&i=1")).toBe(await get("part=seg&i=1"));
  });

  it("ignores part on a layout that is not cut into pieces", async () => {
    const res = await SELF.fetch(`${BASE}/svg?layout=full&part=seg&i=0`);
    expect(res.status).toBe(200);
    const body = await res.text();
    expect(body).toContain("lines written");
    expect(Number(body.match(/<svg[^>]*width="(\d+)"/)?.[1])).toBe(480);
  });

  it("treats a nonsense index as the first slice rather than failing", async () => {
    const junk = await get("part=seg&i=__proto__");
    expect(junk).toContain("#3572A5");
  });
});
