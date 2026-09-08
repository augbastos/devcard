// Which card a request is asking for.
//
// Everything that turns a raw request into the (language, theme, layout) triple
// the renderer needs — and the cache key for that triple. It lives outside
// src/index.ts because workerd validates every named export of the entrypoint
// module and rejects anything that is not a handler: exporting a plain string
// from there fails the Worker at startup with "Incorrect type for map entry".

import { Strings } from "./render";

export const STRINGS: Record<string, Strings> = {
  en: {
    lines: "lines written",
    edits: "code edits",
    commits: "commits",
    repos: "repos",
    since: "tracking since",
    events: "events",
    dayStreak: "day streak",
    streakAbbr: "d",
    updatedAgo: "updated {X} ago",
    dec: ".",
    other: "other",
    locale: "en",
  },
  pt: {
    lines: "linhas escritas",
    edits: "edições de código",
    commits: "commits",
    repos: "repos",
    since: "medindo desde",
    events: "eventos",
    dayStreak: "dias seguidos",
    streakAbbr: "d",
    updatedAgo: "atualizado há {X}",
    dec: ",",
    other: "outras",
    locale: "pt",
  },
  es: {
    lines: "líneas escritas",
    edits: "ediciones de código",
    commits: "commits",
    repos: "repos",
    since: "midiendo desde",
    events: "eventos",
    dayStreak: "días seguidos",
    streakAbbr: "d",
    updatedAgo: "actualizado hace {X}",
    dec: ",",
    other: "otras",
    locale: "es",
  },
};

export const DEFAULT_LANG = "en";

/** Language actually served for a request: `?lang=` wins, else Accept-Language.
 *
 * Own-property lookup, not `STRINGS[tag]`: `?lang=constructor` used to resolve
 * to `Object.prototype.constructor`, which is truthy and has none of the
 * fields the card reads — so the card rendered "undefined" in every label and
 * "1undefined5" wherever the decimal separator was applied.
 *
 * Header tags are ranked by their q-value rather than by the order they appear
 * in, so `Accept-Language: en;q=0.3, pt;q=0.9` resolves to Portuguese. The
 * resolved name is returned (not just the strings) because it is part of the
 * cache key.
 */
export function langName(request: Request, url: URL): string {
  const forced = url.searchParams.get("lang");
  if (forced && Object.prototype.hasOwnProperty.call(STRINGS, forced)) return forced;

  const header = (request.headers.get("Accept-Language") ?? "").toLowerCase();
  let best: string | null = null;
  let bestQ = -1;
  for (const part of header.split(",")) {
    const [rawTag, ...params] = part.split(";");
    const tag = rawTag.trim().split("-")[0];
    if (!tag || !Object.prototype.hasOwnProperty.call(STRINGS, tag)) continue;
    const qParam = params.find((p) => p.trim().startsWith("q="));
    const q = qParam ? Number(qParam.trim().slice(2)) : 1;
    const quality = Number.isFinite(q) ? q : 0;
    // RFC 9110: q=0 means "not acceptable". Treating it as a weak preference
    // would serve a language the visitor explicitly refused.
    if (quality <= 0) continue;
    if (quality > bestQ) {
      bestQ = quality;
      best = tag;
    }
  }
  return best ?? DEFAULT_LANG;
}

export const DEFAULT_LAYOUT = "full";
export const LAYOUTS = ["full", "wide", "banner", "half", "vertical"] as const;
const LAYOUT_SET: ReadonlySet<string> = new Set(LAYOUTS);

export function layoutName(name: string | null | undefined): string {
  return name && LAYOUT_SET.has(name) ? name : DEFAULT_LAYOUT;
}

/** `?langs=all` makes the legend name every language instead of collapsing the
 *  tail into one row. Useful when the card's URL is opened directly; an
 *  embedded card reads better with the tail grouped. */
export function langsAll(url: URL): boolean {
  return url.searchParams.get("langs") === "all";
}

/** `?part=` serves the card in pieces, which is the only way a README gets a
 *  tooltip per language: an `<img>` carries one `title`, so the bar has to stop
 *  being part of the same image as everything else. render-split.ts holds the
 *  geometry and the measurements behind it.
 *
 * Only `layout=wide` is cut this way. A part asked of another layout, or an
 * unknown value, falls back to the whole card rather than 404ing an embed
 * someone has already pasted somewhere. */
export const PARTS = ["body", "cap", "seg"] as const;
export type Part = (typeof PARTS)[number];
const PART_SET: ReadonlySet<string> = new Set(PARTS);

export function partName(url: URL, layout: string): Part | null {
  if (layout !== "wide") return null;
  const raw = url.searchParams.get("part");
  return raw && PART_SET.has(raw) ? (raw as Part) : null;
}

export function capSide(url: URL): "l" | "r" {
  return url.searchParams.get("side") === "r" ? "r" : "l";
}

/** Which slice of the bar. Anything that is not a plausible index reads as 0;
 *  an index past the end is the renderer's problem, and it draws an empty
 *  slice — markup that has gone stale should thin out, not break. */
export function segIndex(url: URL): number {
  const raw = Number(url.searchParams.get("i"));
  return Number.isInteger(raw) && raw >= 0 && raw < 1000 ? raw : 0;
}

// The variant a request resolves to, as a cache key.
//
// The Cache API keys on the request URL, so the previous `cache.match(request)`
// had two defects. First, the language is resolved from `Accept-Language`,
// which is not in the URL at all, so correctness rested entirely on `Vary`.
// Measured against the deployed card on 2026-09-07, on a variant nobody had
// requested: the first visitor sent `Accept-Language: en-US` and got English;
// the next two sent `pt-BR` and `es-ES` and got English as well. `Vary:
// Accept-Language` is on the response and does NOT separate the variants on
// this `caches.open("default")` path. And where Vary does apply it keys per
// *verbatim* header value, so `en-US,en;q=0.9` and `en-GB,en;q=0.7` would be
// two entries holding the byte-identical English card — the long tail of real
// browser headers shreds the hit rate. Second, the raw URL keys on junk too:
// `?nonsense=1`,
// `?theme=dark&t=2`, and a bare request each got their own entry of the same
// image.
//
// Keying on the resolved (lang, theme, layout) instead bounds the cache at
// 3 x 6 x 4 = 72 entries, one per card that can actually be rendered, and makes
// the language separation a property of this code rather than of edge config.
// `user` is deliberately absent: a wrong user 404s before we get here, and the
// only accepted value renders identically to omitting it.
export function cacheKeyFor(
  url: URL,
  lang: string,
  theme: string,
  layout: string,
  allLangs = false,
  part: Part | null = null,
  side: "l" | "r" = "l",
  index = 0
): Request {
  const key = new URL(url.origin);
  key.pathname = "/svg";
  key.searchParams.set("lang", lang);
  key.searchParams.set("theme", theme);
  key.searchParams.set("layout", layout);
  // Part of the key because it changes the render. Leaving it out would serve
  // the collapsed card to a request that asked for the full breakdown — the
  // exact class of bug the resolved-variant key exists to prevent.
  if (allLangs) key.searchParams.set("langs", "all");
  // Same reason, and it matters far more here: every slice of the bar is a
  // request to the same path, so a key that ignored `part` would serve the
  // whole card — or Python's slice — for all twenty of them.
  if (part) {
    key.searchParams.set("part", part);
    if (part === "cap") key.searchParams.set("side", side);
    if (part === "seg") key.searchParams.set("i", String(index));
  }
  return new Request(key.toString(), { method: "GET" });
}

