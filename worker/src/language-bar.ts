// The language bar, and the hover layer that names the slivers.
//
// The bar's segments are drawn to exact proportion, which on a real account
// means a long tail of sub-pixel widths — measured on the deployed card:
// Shell 0.65px, C++ 0.55px, TOML 0.37px, C 0.22px, Java 0.05px, Ruby 0.00px.
// A pointer cannot land on 0.05px, so the tooltip needs a target of its own:
// an invisible hit area with a minimum width, laid over the bar without
// changing a single visible pixel of it.
//
// Where this works: anywhere the SVG is a document — opened directly, inlined,
// or embedded with <object>. It does NOT work in a GitHub README, because
// GitHub serves the card through an <img>, and a browser renders SVG-in-<img>
// in secure static mode: no pointer events reach the document. That is a
// browser rule, not something the card can opt out of. Declarative animation
// still runs there, which is why the live dot pulses but hover does nothing.

import { escapeXml, sliceColor, sliceLabel } from "./svg-utils";
import { LanguageSlice } from "./queries";

/** Narrowest a hover target may be.
 *
 * Three pixels is about a text caret — small, but a pointer can land on it,
 * and it is sixty times what Java's 0.05px segment offers. It is deliberately
 * not larger: every pixel a tiny segment gains has to be taken from a bigger
 * neighbour, which drags that neighbour's target away from the colour the
 * reader is actually pointing at. Three keeps the drift near zero on a real
 * distribution — twelve tail languages need 36px of targets and already
 * occupy about 35px of bar.
 */
const MIN_HIT_WIDTH = 3;

const TIP_H = 20;
const TIP_PAD = 9;
const TIP_CHAR = 6.15; // approximate advance width at 11px in the card's stack
// Below the bar, not above: above it there is only the headline number and the
// streak, and a tooltip that covers those reads as breakage. Below, the gap to
// the legend is wider, and the few pixels it does overlap while pointing are
// what a tooltip is expected to do.
const TIP_GAP = 5;

export interface BarGeometry {
  x: number;
  y: number;
  width: number;
  height: number;
  /** Left and right bounds the tooltip may not cross. */
  clampLeft: number;
  clampRight: number;
}

/** The visible bar: exact proportions, no minimum width, no tooltips.
 *  `id` namespaces the clip path so two bars can coexist in one document. */
export function languageBarSegments(
  slices: LanguageSlice[],
  totalLines: number,
  geo: BarGeometry,
  id: string
): string {
  const parts: string[] = [
    `<clipPath id="${id}"><rect x="${geo.x}" y="${geo.y}" width="${geo.width}" height="${geo.height}" rx="${geo.height / 2}"/></clipPath>`,
    `<rect class="track" x="${geo.x}" y="${geo.y}" width="${geo.width}" height="${geo.height}" rx="${geo.height / 2}"/>`,
    `<g clip-path="url(#${id})">`,
  ];
  let x = geo.x;
  for (const slice of slices) {
    const w = totalLines > 0 ? (slice.total / totalLines) * geo.width : 0;
    parts.push(
      `<rect x="${x.toFixed(2)}" y="${geo.y}" width="${w.toFixed(2)}" height="${geo.height}" fill="${sliceColor(slice)}"/>`
    );
    x += w;
  }
  parts.push(`</g>`);
  return parts.join("");
}

/** The hover layer. Emit this LAST in the document so its tooltips paint over
 *  everything below the bar. The rectangles are transparent and sit only over
 *  the bar's own band, so they intercept nothing else. */
export function languageBarHover(
  slices: LanguageSlice[],
  totalLines: number,
  geo: BarGeometry,
  otherWord: string
): string {
  if (totalLines <= 0 || slices.length === 0) return "";

  const widths = slices.map((s) => (s.total / totalLines) * geo.width);

  // Give every segment at least MIN_HIT_WIDTH, then pay for it out of the
  // segments that have pixels to spare, so the targets still tile the bar
  // exactly and never overlap. Overlapping targets would make the topmost one
  // swallow its neighbours, which is precisely the tail.
  const hitWidths = widths.map((w) => Math.max(w, MIN_HIT_WIDTH));
  const overflow = hitWidths.reduce((a, b) => a + b, 0) - geo.width;
  if (overflow > 0) {
    const slack = hitWidths.map((h) => Math.max(0, h - MIN_HIT_WIDTH));
    const totalSlack = slack.reduce((a, b) => a + b, 0);
    if (totalSlack > 0) {
      for (let i = 0; i < hitWidths.length; i++) {
        hitWidths[i] -= overflow * (slack[i] / totalSlack);
      }
    }
  }

  const groups: string[] = [];
  let x = geo.x;
  let hitX = geo.x;

  for (const [i, slice] of slices.entries()) {
    const w = widths[i];
    const hitW = hitWidths[i];
    const pct = ((slice.total / totalLines) * 100).toFixed(1);
    const label = `${sliceLabel(slice, otherWord)} ${pct}%`;

    const tipW = Math.round(label.length * TIP_CHAR) + TIP_PAD * 2;
    let tipX = hitX + hitW / 2 - tipW / 2;
    tipX = Math.min(Math.max(tipX, geo.clampLeft), geo.clampRight - tipW);
    const tipY = geo.y + geo.height + TIP_GAP;

    // A swatch inside the tooltip ties it back to the segment being pointed at.
    const swatch = sliceColor(slice);
    groups.push(
      `<g class="lang">` +
        `<rect class="hit" x="${hitX.toFixed(2)}" y="${geo.y}" width="${hitW.toFixed(2)}" height="${geo.height}" aria-label="${escapeXml(label)}"/>` +
        `<g class="tip">` +
        `<rect class="tipbg" x="${tipX.toFixed(1)}" y="${tipY}" width="${tipW}" height="${TIP_H}" rx="6"/>` +
        `<circle cx="${(tipX + TIP_PAD + 3).toFixed(1)}" cy="${tipY + TIP_H / 2}" r="3.5" fill="${swatch}"/>` +
        `<text class="tiptx" x="${(tipX + TIP_PAD + 12).toFixed(1)}" y="${tipY + TIP_H / 2 + 3.8}" font-family="-apple-system,'Segoe UI',Roboto,sans-serif" font-size="11">${escapeXml(label)}</text>` +
        `</g>` +
        `</g>`
    );
    x += w;
    hitX += hitW;
  }

  return `<g class="langhover">${groups.join("")}</g>`;
}

/** Behaviour rules for the hover layer. Colours come from the theme (see
 *  `tokenCss`), so the tooltip matches whichever palette is in use. */
export const LANGUAGE_HOVER_CSS =
  `.hit{fill:transparent;pointer-events:all}` +
  `.tip{opacity:0;pointer-events:none;transition:opacity .12s ease-out}` +
  `.hit:hover+.tip{opacity:1}`;
