// The card, served in pieces, so a GitHub README can hover one language.
//
// Why this exists at all: a README embeds the card through an `<img>`, and a
// browser renders SVG-in-`<img>` in secure static mode — no pointer event ever
// reaches inside the document. Every element that could carry the interaction
// instead (`<object>`, `<embed>`, `<iframe>`, inline `<svg>`, `<style>`,
// `<map>`/`<area>`) is removed by GitHub's HTML sanitizer. Measured against
// GitHub's own markdown renderer, exactly two things survive: `<details>`, and
// a `title` attribute on an `<img>`.
//
// A `title` names the whole image, so one image can only ever have one tooltip.
// The way out is to stop the language bar from being part of one image: the
// card is served as a body plus a row of per-language slices, and each slice
// carries its own `title`. Pointing at Ruby's sliver names Ruby.
//
// Two measurements from GitHub's rendered README shaped the geometry:
//
//   * Adjacent `<img>` tags with no whitespace between them tile with a gap of
//     exactly 0, and a row of percentage widths spans the column exactly. So
//     the bar can be a row of images.
//   * `align="left"` stacks with no vertical gap, but GitHub's CSS gives
//     `img[align=left]` a `padding-right: 20px` — fatal for a horizontal row.
//     `align="top"` stacks with no gap and adds no padding, so that is what
//     every piece uses.
//   * A paragraph always reserves a 24px line box. A row of short images
//     therefore leaves ~12px of slack *after* it. That is why the bar is the
//     card's last row: the slack falls below the card, where nothing shows it.
//     Any other position would put that gap inside the card on a narrow column.

import { CardData, LanguageSlice } from "./queries";
import { Theme } from "./themes";
import { escapeXml, sliceColor, sliceLabel } from "./svg-utils";

export const W = 840;
export const PAD = 28;
export const INNER = W - PAD * 2;

/** The bar's own band: the strip is the card's bottom edge, so it carries the
 *  space around the bar and the card's bottom border and corners. */
export const STRIP_TOP = 6;
export const BAR_H = 14;
export const STRIP_BOTTOM = 14;
export const STRIP_H = STRIP_TOP + BAR_H + STRIP_BOTTOM;
export const CORNER = 14;

/** Narrowest a slice may be drawn.
 *
 * Unlike the in-card hover layer, here the target *is* the visible segment, so
 * a floor costs real proportion rather than nothing. Four pixels is the price
 * of a language existing on the card at all: measured on a real account, seven
 * of eighteen languages draw under 4px, five under a single pixel and two under
 * a tenth of one — a bar that draws them honestly draws them invisible. The
 * floor is paid for out of the segments that have pixels to spare, so the row
 * still tiles the bar exactly.
 */
export const MIN_SEG = 4;

export interface StripSlot {
  slice: LanguageSlice;
  /** Width as a percentage of the card, to 4 decimals — this is the number
   *  that goes in the README, so the SVG is drawn at exactly W * pct / 100 and
   *  every slice ends up the same rendered height whatever the column width. */
  pct: number;
  width: number;
  /** True share, for the label. The floor moves pixels, never percentages. */
  share: number;
}

export interface Strip {
  capLeftPct: number;
  capRightPct: number;
  slots: StripSlot[];
}

/** Trim binary float noise: `W * 3.3333 / 100` is 27.999719999999996, and that
 *  is what would land in the SVG's width attribute otherwise. */
const num = (n: number) => String(Math.round(n * 1e6) / 1e6);

/** How the bar is cut up. Shared by the renderer and the embed generator so
 *  the markup's widths and the drawn slices can never disagree. */
export function stripLayout(slices: LanguageSlice[], totalLines: number): Strip {
  // Widths are carried as integer ten-thousandths of a percent all the way to
  // the markup. Summing rounded floats drifts — 100.00000000000001 was the
  // measured result — and a total a hair over 100% makes the last image wrap
  // onto its own line, which is the one failure here that looks broken rather
  // than merely imprecise.
  const capLeftTt = Math.round((PAD / W) * 1e6);
  const tt = (v: number) => v / 1e4;
  if (slices.length === 0 || totalLines <= 0) {
    return { capLeftPct: tt(capLeftTt), capRightPct: tt(1e6 - capLeftTt), slots: [] };
  }

  const floor = Math.min(MIN_SEG, INNER / slices.length);
  const widths = slices.map((s) => Math.max((s.total / totalLines) * INNER, floor));
  const overflow = widths.reduce((a, b) => a + b, 0) - INNER;
  if (overflow > 0) {
    const slack = widths.map((w) => Math.max(0, w - floor));
    const totalSlack = slack.reduce((a, b) => a + b, 0);
    if (totalSlack > 0) {
      for (let i = 0; i < widths.length; i++) widths[i] -= overflow * (slack[i] / totalSlack);
    }
  }

  const slots = slices.map((slice, i) => {
    const pct = tt(Math.round((widths[i] / W) * 1e6));
    return { slice, pct, width: (W * pct) / 100, share: slice.total / totalLines };
  });

  // The right cap absorbs every other piece's rounding, so the row adds up to
  // exactly 100% by construction rather than by luck.
  const usedTt = capLeftTt + slots.reduce((a, s) => a + Math.round(s.pct * 1e4), 0);
  return { capLeftPct: tt(capLeftTt), capRightPct: tt(Math.max(0, 1e6 - usedTt)), slots };
}

/** Only the tokens the strip pieces use, with the same dark-mode behaviour as
 *  the full card so `theme=default` still follows the reader's system. */
function stripCss(theme: Theme): string {
  const tokens = (k: Theme["base"]) => `.bg{fill:${k.bg}}.brd{stroke:${k.brd}}.brdf{fill:${k.brd}}`;
  let css = tokens(theme.base);
  if (theme.dark) css += `@media(prefers-color-scheme:dark){${tokens(theme.dark)}}`;
  return css;
}

function open(width: string, height: number): string {
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" ` +
    `viewBox="0 0 ${width} ${height}">`
  );
}

/** A card corner and the side border, at the end of the bar row.
 *
 * The rounded rect is drawn oversized so three of its corners fall outside the
 * viewBox — the same trick the body uses for its flat bottom. What is left on
 * canvas is one rounded corner, one side border and the bottom border, all in
 * the card's own stroke so the piece cannot drift from the body above it.
 */
export function renderStripCap(theme: Theme, side: "l" | "r", pct: number): string {
  const width = Math.max(1, (W * pct) / 100);
  const x = side === "l" ? 0.5 : -CORNER;
  const w = width + CORNER - 0.5;
  return (
    open(num(width), STRIP_H) +
    `<style>${stripCss(theme)}</style>` +
    `<rect class="bg brd" x="${x}" y="${-CORNER}" width="${num(w)}" ` +
    `height="${num(STRIP_H - 0.5 + CORNER)}" rx="${CORNER}" stroke-width="1"/>` +
    `</svg>`
  );
}

/** One language's slice of the bar, plus the card background and bottom border
 *  around it. `end` rounds the bar's cap on whichever side this slice sits. */
export function renderStripSegment(
  theme: Theme,
  slot: StripSlot | null,
  end: "l" | "r" | "both" | null,
  width: number
): string {
  const w = Math.max(0.01, width);
  const parts = [
    open(num(w), STRIP_H),
    `<style>${stripCss(theme)}</style>`,
    `<rect class="bg" width="${num(w)}" height="${STRIP_H}"/>`,
    `<rect class="brdf" y="${STRIP_H - 1}" width="${num(w)}" height="1"/>`,
  ];
  if (slot) {
    // Round only the outer end: the rect is extended past the viewBox on the
    // inner side so that corner never shows. A radius wider than the slice
    // itself would draw a cap the slice has no room for, so it is capped.
    const r = Math.min(BAR_H / 2, end ? w / 2 : BAR_H / 2);
    const x = end === "r" ? -BAR_H : 0;
    const rw = end === "both" ? w : w + BAR_H;
    parts.push(
      `<rect x="${x}" y="${STRIP_TOP}" width="${num(rw)}" height="${BAR_H}" ` +
        `rx="${end ? num(r) : 0}" fill="${sliceColor(slot.slice)}"/>`
    );
  }
  return parts.join("") + `</svg>`;
}

/** "Python 41.8%" — the text the README puts in the slice's `title`. */
export function slotLabel(slot: StripSlot, otherWord: string): string {
  return `${sliceLabel(slot.slice, otherWord)} ${(slot.share * 100).toFixed(1)}%`;
}

const pctText = (n: number) => String(Math.round(n * 1e4) / 1e4);

/** The block a README pastes in.
 *
 * Every `<img>` sits on one line with no whitespace between the tags: a newline
 * between two inline images becomes a space, and a space becomes a visible gap
 * in the bar. `align="top"` on every piece is what makes the rows stack with no
 * seam — see the note at the top of this file.
 *
 * The widths and the tooltip text live in the markup, which is static, so this
 * block is regenerated (see .github/workflows/devcard-readme.yml). The pixels
 * are always live; only the proportions and percentages are as fresh as the
 * last regeneration.
 */
export function embedHtml(
  data: CardData,
  strip: Strip,
  origin: string,
  user: string,
  theme: string,
  otherWord: string
): string {
  const q = (params: Record<string, string>) => {
    const parts = [`user=${encodeURIComponent(user)}`, "layout=wide"];
    for (const [k, v] of Object.entries(params)) parts.push(`${k}=${encodeURIComponent(v)}`);
    if (theme !== "default") parts.push(`theme=${encodeURIComponent(theme)}`);
    return `${origin}/svg?${parts.join("&amp;")}`;
  };

  const breakdown = strip.slots
    .map((s) => `${sliceLabel(s.slice, otherWord)} ${(s.share * 100).toFixed(1)}%`)
    .join(", ");
  const alt = `devcard — ${user}'s live coding stats. Languages: ${breakdown}`;

  const pieces = [
    `<img src="${q({ part: "body" })}" width="100%" align="top" alt="${escapeXml(alt)}">`,
    `<img src="${q({ part: "cap", side: "l" })}" width="${pctText(strip.capLeftPct)}%" align="top" alt="">`,
  ];
  strip.slots.forEach((slot, i) => {
    const title = escapeXml(slotLabel(slot, otherWord));
    pieces.push(
      `<img src="${q({ part: "seg", i: String(i) })}" width="${pctText(slot.pct)}%" ` +
        `align="top" title="${title}" alt="">`
    );
  });
  pieces.push(
    `<img src="${q({ part: "cap", side: "r" })}" width="${pctText(strip.capRightPct)}%" align="top" alt="">`
  );
  return `<p>${pieces.join("")}</p>`;
}
