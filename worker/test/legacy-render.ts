// Historical rendering harness for renderer, variant-cache and golden tests.
// Public requests now use the redirect handler; ingest tests still call it.
import { loadCardData } from "../src/queries";
import {
  STRINGS,
  cacheKeyFor,
  langName,
  layoutName,
  langsAll,
  partName,
  capSide,
  segIndex,
  pieceWidth,
  Part,
} from "../src/variants";
import { pickTheme, themeName } from "../src/themes";
import { renderFull, Strings } from "../src/render";
import { renderBanner, renderHalf, renderVertical } from "../src/render-layouts";
import { renderWide } from "../src/render-wide";
import { stripLayout, renderStripCap, renderStripSegment, embedHtml, W as STRIP_W } from "../src/render-split";

import type { Env } from "../src/index";

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
    const isHead = request.method === "HEAD";
    if ((request.method === "GET" || isHead) && url.pathname === "/svg") {
      const getRequest = isHead
        ? new Request(request.url, { method: "GET", headers: request.headers })
        : request;
      const response = await handleSvgCached(getRequest, env, ctx);
      return isHead ? new Response(null, { status: response.status, headers: response.headers }) : response;
    }
    if (request.method === "GET" && url.pathname === "/embed") {
      return handleEmbed(request, env, url);
    }
    return new Response("not found", { status: 404 });
  },
};

async function handleEmbed(request: Request, env: Env, url: URL): Promise<Response> {
  const requestedUser = url.searchParams.get("user");
  if (requestedUser && requestedUser !== env.GITHUB_USERNAME) {
    return new Response("unknown user", { status: 404 });
  }
  const lang = langName(request, url);
  const theme = themeName(url.searchParams.get("theme"));
  const t = STRINGS[lang];
  const data = await loadCardData(env, t.locale);
  const strip = stripLayout(data.languages, data.totalLines);
  const html = embedHtml(strip, url.origin, env.GITHUB_USERNAME, theme, t.other);
  return new Response(html + "\n", {
    headers: {
      "Content-Type": "text/plain; charset=utf-8",
      "X-Content-Type-Options": "nosniff",
      // Short: this is read by a scheduled job, not by a page, and a stale
      // answer would be baked into someone's README until the next run.
      "Cache-Control": "public, max-age=60",
    },
  });
}

/** One piece of the split `wide` card — see render-split.ts.
 *
 * An index past the end of the bar renders an empty slice rather than a 404:
 * the widths and the slice count live in whatever markup someone pasted, so a
 * README that has gone stale should thin out quietly, not sprout broken-image
 * boxes across the bar.
 */
function renderPart(
  data: Awaited<ReturnType<typeof loadCardData>>,
  tokens: ReturnType<typeof pickTheme>,
  t: Strings,
  allLangs: boolean,
  part: Part,
  side: "l" | "r",
  index: number,
  width: number | null
): string {
  if (part === "body") return renderWide(data, tokens, t, allLangs, true);

  const strip = stripLayout(data.languages, data.totalLines);
  if (part === "cap") {
    const pct = width !== null ? width / 1e4 : side === "l" ? strip.capLeftPct : strip.capRightPct;
    return renderStripCap(tokens, side, pct);
  }

  const slot = strip.slots[index] ?? null;
  const last = strip.slots.length - 1;
  const end = strip.slots.length === 1 ? "both" : index === 0 ? "l" : index === last ? "r" : null;
  const px = width !== null ? (STRIP_W * width) / 1e6 : slot ? slot.width : 1;
  return renderStripSegment(tokens, slot, slot ? end : null, px);
}

async function handleSvg(
  env: Env,
  lang: string,
  theme: string,
  layout: string,
  allLangs: boolean,
  part: Part | null = null,
  side: "l" | "r" = "l",
  index = 0,
  width: number | null = null
): Promise<Response> {
  const t = STRINGS[lang];
  const tokens = pickTheme(theme);
  const data = await loadCardData(env, t.locale);

  let svg: string;
  if (part) svg = renderPart(data, tokens, t, allLangs, part, side, index, width);
  else if (layout === "wide") svg = renderWide(data, tokens, t, allLangs);
  else if (layout === "banner") svg = renderBanner(data, tokens, t);
  else if (layout === "half") svg = renderHalf(data, tokens, t);
  else if (layout === "vertical") svg = renderVertical(data, tokens, t);
  else svg = renderFull(data, tokens, t, allLangs);

  return new Response(svg, {
    headers: {
      "Content-Type": "image/svg+xml; charset=utf-8",
      "Cache-Control": "public, max-age=300, s-maxage=300",
      // Opened directly, an SVG is a document that could run script. Nothing
      // dynamic reaches the markup unescaped, and this makes that a property
      // of the response too: no script, no external fetch — only the inline
      // <style> and the avatar's data: URI the card is built from.
      "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src data:",
      "X-Content-Type-Options": "nosniff",
      // For caches downstream of this Worker (the browser, GitHub's image
      // proxy, corporate proxies): the body genuinely depends on the header.
      // This Worker's own cache does NOT rely on it — see cacheKeyFor.
      "Vary": "Accept-Language",
    },
  });
}

// s-maxage was 30s, which had every embed revalidating ~2,880 times a day per
// variant — GitHub's image proxy honours it, so a README that nobody reloads
// still generated constant traffic. Five minutes is still live for a card whose
// underlying hook writes in seconds.
async function handleSvgCached(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
  const url = new URL(request.url);
  const requestedUser = url.searchParams.get("user");
  if (requestedUser && requestedUser !== env.GITHUB_USERNAME) {
    return new Response("unknown user", { status: 404 });
  }

  const lang = langName(request, url);
  const theme = themeName(url.searchParams.get("theme"));
  const layout = layoutName(url.searchParams.get("layout"));
  const allLangs = langsAll(url);
  const part = partName(url, layout);
  const side = capSide(url);
  const index = segIndex(url);
  const width = part === "cap" || part === "seg" ? pieceWidth(url) : null;

  const cache = await caches.open("default");
  const cacheKey = cacheKeyFor(url, lang, theme, layout, allLangs, part, side, index, width);
  const cached = await cache.match(cacheKey);
  if (cached) return cached;

  const response = await handleSvg(env, lang, theme, layout, allLangs, part, side, index, width);
  if (response.ok) {
    ctx.waitUntil(cache.put(cacheKey, response.clone()));
  }
  return response;
}
