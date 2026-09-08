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
 *  tail into one row.
 *
 * It exists because a GitHub README cannot deliver hover: `<object>`,
 * `<iframe>`, inline `<svg>`, `<style>` and `<map>`/`<area>` are all stripped
 * by GitHub's sanitizer, so no pointer event can reach inside the card. What
 * GitHub does allow is `<details>` with an image inside — so the full
 * breakdown can be a second, live render one click away, instead of a caption
 * someone has to keep up to date by hand.
 */
export function langsAll(url: URL): boolean {
  return url.searchParams.get("langs") === "all";
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
  allLangs = false
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
  return new Request(key.toString(), { method: "GET" });
}

