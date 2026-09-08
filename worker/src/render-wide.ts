// The `wide` layout (840×~400).
//
// A README's content column is 838px on GitHub; the `full` card is 480px, so it
// used a bit over half the width and left the rest empty. This lays the same
// information out across the space instead of stretching it: the legend gets
// three columns rather than two, the heatmap gets bigger cells, and the pinned
// repos sit beside it rather than under it. Nothing is scaled up — the type
// sizes are the ones `full` uses, because a card blown up to fit is not the
// same thing as a card designed to fit.

import { CardData, LanguageSlice, withOtherBucket, NAMED_LANGUAGES } from "./queries";
import { languageBarSegments, languageBarHover, BarGeometry } from "./language-bar";
import { Theme, cssFor } from "./themes";
import { Strings } from "./render";
import {
  MONO,
  SANS,
  HEART_ICON,
  REPO_ICON,
  FLAME_ICON,
  escapeXml,
  truncate,
  fmtCount,
  fmtBytes,
  fmtAge,
  pick,
  sliceColor,
  sliceLabel,
  KIND_ICONS,
} from "./svg-utils";

const W = 840;
const PAD = 28;
const INNER = W - PAD * 2;

function header(data: CardData, t: Strings): string {
  const avatar = data.avatar
    ? `<clipPath id="wav"><circle cx="${PAD + 21}" cy="40" r="21"/></clipPath>
  <image href="${escapeXml(data.avatar)}" x="${PAD}" y="19" width="42" height="42" clip-path="url(#wav)" preserveAspectRatio="xMidYMid slice"/>
  <circle class="avbrd" cx="${PAD + 21}" cy="40" r="21" fill="none" stroke-width="1.5"/>`
    : `<circle class="pill" cx="${PAD + 21}" cy="40" r="21"/><text class="mut" x="${PAD + 21}" y="46" ${SANS} font-size="17" text-anchor="middle">${escapeXml(data.githubUser.charAt(0).toUpperCase())}</text>`;
  const textX = PAD + 54;
  return `${avatar}
  <text class="txt" x="${textX}" y="35" ${SANS} font-size="16" font-weight="700">devcard</text>
  <text class="mut" x="${textX}" y="53" ${MONO} font-size="12.5">@${escapeXml(data.githubUser)}</text>
  <circle class="live" cx="${textX + 72}" cy="30" r="4">
    <animate attributeName="opacity" values="1;0.35;1" dur="2.4s" repeatCount="indefinite"/>
  </circle>
  <a href="https://github.com/${escapeXml(data.githubUser)}?tab=repositories" target="_blank">
    <text class="link" x="${W - PAD}" y="35" ${MONO} font-size="12.5" text-anchor="end">${data.repoCount} ${escapeXml(t.repos)} →</text>
  </a>`;
}

function headline(data: CardData, t: Strings): string {
  const y = 108;
  const streakClass = data.streak >= 7 ? "accent" : "mut";
  return `<text class="txt" x="${PAD}" y="${y}" ${MONO} font-size="32" font-weight="700">${fmtCount(data.totalLines, t.dec)}<tspan class="mut" ${SANS} font-size="13" font-weight="400"> ${escapeXml(t.lines)}</tspan><tspan class="faint" ${MONO} font-size="11.5" font-weight="400"> (${fmtBytes(data.totalBytes, t.dec)})</tspan></text>
  <path class="${streakClass}" d="${FLAME_ICON}" transform="translate(${W - PAD - 8},${y - 9}) scale(1.15)"/>
  <text class="txt" x="${W - PAD - 22}" y="${y}" ${MONO} font-size="27" font-weight="700" text-anchor="end">${data.streak}</text>
  <text class="mut" x="${W - PAD}" y="${y + 17}" ${SANS} font-size="10.5" text-anchor="end">${escapeXml(t.dayStreak)}</text>`;
}

/** Three columns, filled down each column in turn.
 *
 * The legend stays deliberately short — the six biggest languages plus the
 * collapsed rest — so the card reads at a glance. Naming the whole tail here
 * would trade that for five rows of near-zero percentages; the tail is named on
 * hover instead, one sliver at a time.
 */
function legend(data: CardData, slices: LanguageSlice[], t: Strings, top: number): { svg: string; bottom: number } {
  if (slices.length === 0) return { svg: "", bottom: top };
  // Four columns once the legend is long, so `?langs=all` stays a wide block
  // rather than a tall one.
  const columns = slices.length > 9 ? 4 : 3;
  const rowH = 22;
  const perColumn = Math.ceil(slices.length / columns);
  const colW = INNER / columns;
  const svg = slices
    .map((lang, i) => {
      const pct = data.totalLines > 0 ? ((lang.total / data.totalLines) * 100).toFixed(1) : "0.0";
      const cx = PAD + Math.floor(i / perColumn) * colW;
      const y = top + (i % perColumn) * rowH;
      return (
        `<circle cx="${cx + 5}" cy="${y - 4}" r="4.5" fill="${sliceColor(lang)}"/>` +
        `<text class="txt" x="${cx + 17}" y="${y}" ${SANS} font-size="12.5">${escapeXml(truncate(sliceLabel(lang, t.other), 18))}` +
        `<tspan class="mut" ${MONO} font-size="11.5"> ${pct}%</tspan></text>`
      );
    })
    .join("\n  ");
  return { svg, bottom: top + (perColumn - 1) * rowH };
}

/** Heatmap on the left, pinned repos stacked beside it — the arrangement the
 *  extra width buys. Cells are larger than in `full` because there is room. */
function heatAndPins(
  data: CardData,
  top: number
): { svg: string; bottom: number; columnX: number; pinsBottom: number } {
  const cell = 13;
  const gap = 3;
  const step = cell + gap;
  const labelH = 13;
  const gridW = 16 * step - gap;

  const marks = data.monthMarks
    .map(
      (m) =>
        `<text class="faint" x="${PAD + m.weekIndex * step}" y="${top + 9}" ${MONO} font-size="9">${escapeXml(m.label)}</text>`
    )
    .join("");
  const cells: string[] = [];
  data.heatWeeks.forEach((week, w) => {
    week.forEach((c, d) => {
      cells.push(
        `<rect class="heat${c.level}" x="${PAD + w * step}" y="${top + labelH + d * step}" width="${cell}" height="${cell}" rx="2.5"><title>${c.day}: ${c.lines}</title></rect>`
      );
    });
  });
  const heatBottom = top + labelH + 7 * step - gap;

  let pins = "";
  if (data.pins.length > 0) {
    const pinX = PAD + gridW + 26;
    const pinW = W - PAD - pinX;
    const boxH = 40;
    const boxGap = 8;
    pins = data.pins
      .slice(0, 3)
      .map((p, i) => {
        const by = top + i * (boxH + boxGap);
        const starTxt = p.stars !== null ? `★ ${p.stars}` : "";
        const note = truncate(p.note ?? "", Math.floor(pinW / 6.2) - (starTxt ? starTxt.length + 2 : 0));
        const sub = [starTxt, note].filter(Boolean).join("  ");
        return (
          `<a href="https://github.com/${escapeXml(data.githubUser)}/${escapeXml(p.repo)}" target="_blank">` +
          `<rect class="pill" x="${pinX}" y="${by}" width="${pinW.toFixed(1)}" height="${boxH}" rx="8"/>` +
          `<path class="mut" d="${REPO_ICON}" transform="translate(${pinX + 15},${by + 15}) scale(0.85)"/>` +
          `<text class="txt" x="${pinX + 28}" y="${by + 17}" ${SANS} font-size="12" font-weight="700">${escapeXml(truncate(p.repo, 28))}</text>` +
          `<text class="mut" x="${pinX + 12}" y="${by + 32}" ${SANS} font-size="10.5">${escapeXml(sub)}</text>` +
          `</a>`
        );
      })
      .join("\n  ");
  }

  return { svg: marks + cells.join("") + pins, bottom: heatBottom, columnX: PAD + gridW + 26, pinsBottom: top + data.pins.slice(0, 3).length * 48 };
}

export function renderWide(data: CardData, theme: Theme, t: Strings, allLangs = false): string {
  const barY = 132;
  const legendTop = 176;
  // Bar: every language, so nothing disappears and every sliver is pointable.
  // Legend: the tail collapsed, so it stays short. Hover bridges the two.
  const legendSlices = allLangs
    ? data.languages
    : withOtherBucket(data.languages, NAMED_LANGUAGES);
  const slices = data.languages;
  const barGeo: BarGeometry = {
    x: PAD, y: barY, width: INNER, height: 14, clampLeft: PAD, clampRight: W - PAD,
  };
  const { svg: legendSvg, bottom: legendBottom } = legend(data, legendSlices, t, legendTop);
  const heatTop = legendBottom + 22;
  const { svg: heatSvg, bottom: heatBottom, columnX, pinsBottom } = heatAndPins(data, heatTop);

  const contentBottom = Math.max(heatBottom, pinsBottom);
  const divY = contentBottom + 20;
  const footY = divY + 26;
  const stat = (x: number, n: string, label: string) =>
    `<text x="${x}" y="${footY}" font-size="12.5"><tspan class="txt" ${MONO} font-weight="700">${n}</tspan><tspan class="mut" ${SANS}> ${escapeXml(label)}</tspan></text>`;
  // Same rule as `full`: "code edits" only appears when there are agent edits
  // to report, because a git-captured card has no comparable number.
  const footer =
    data.totalActions > 0
      ? stat(PAD, String(data.totalActions), t.edits) + stat(PAD + 220, String(data.totalCommits), t.commits)
      : stat(PAD, String(data.totalCommits), t.commits);

  const nowSec = Math.floor(Date.now() / 1000);
  const age = fmtAge(data.updatedAt, nowSec);
  const sinceDate = data.firstTs ? new Date(data.firstTs * 1000).toISOString().slice(0, 10) : null;
  const provParts: string[] = [];
  if (sinceDate) provParts.push(`${t.since} ${sinceDate}`, `${data.totalEvents.toLocaleString("en-US")} ${t.events}`);
  if (age) provParts.push(t.updatedAgo.replace("{X}", age));
  const provenance = provParts.length
    ? `<text class="faint" x="${W - PAD}" y="${footY}" ${MONO} font-size="9.5" text-anchor="end">${escapeXml(provParts.join(" · "))}</text>`
    : "";

  // Pills go in the right-hand column, under the pinned repos. The heatmap is
  // taller than one or two pin boxes, so that column had a hole in it; putting
  // the pills there fills the space the wide layout bought and keeps the card
  // from growing another row.
  const pillTop = pinsBottom + (data.pins.length > 0 ? 4 : 0);
  const pillLeft = columnX;
  const pillRight = W - PAD;
  let pillX = pillLeft;
  let pillRow = 0;
  const pillParts: string[] = [];
  const addPill = (label: string, iconPath: string | null, opts?: { cls?: string; iconCls?: string; href?: string }) => {
    const iconSpace = iconPath ? 16 : 0;
    const w = Math.round(label.length * 6.2) + 20 + iconSpace;
    if (pillX + w > pillRight) {
      pillRow += 1;
      pillX = pillLeft;
    }
    const y = pillTop + pillRow * 28;
    const icon = iconPath
      ? `<path class="${opts?.iconCls ?? "mut"}" d="${iconPath}" transform="translate(${pillX + 14},${y + 10.5}) scale(0.95)"/>`
      : "";
    let pill =
      `<rect class="${opts?.cls ?? "pill"}" x="${pillX}" y="${y}" width="${w}" height="21" rx="10.5"/>` +
      icon +
      `<text class="mut" x="${pillX + 10 + iconSpace}" y="${y + 14.5}" ${SANS} font-size="11">${escapeXml(label)}</text>`;
    if (opts?.href) pill = `<a href="${opts.href}" target="_blank">${pill}</a>`;
    pillParts.push(pill);
    pillX += w + 8;
  };
  if (data.sponsorable) {
    addPill("Sponsor", HEART_ICON, {
      cls: "pill-sp",
      iconCls: "heart",
      href: `https://github.com/sponsors/${escapeXml(data.githubUser)}`,
    });
  }
  for (const b of data.badges) {
    addPill(b.label, pick(KIND_ICONS, b.kind) ?? KIND_ICONS.badge);
  }
  // The pills sit beside the heatmap, so they cost no height unless enough of
  // them wrap to run past its bottom edge.
  const pillsBottom = pillParts.length > 0 ? pillTop + (pillRow + 1) * 28 : 0;
  const H = Math.max(footY + 18, pillsBottom + 46);

  return `<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="devcard ${escapeXml(data.githubUser)}">
  <style>${cssFor(theme)}</style>
  <rect class="bg brd" x="0.5" y="0.5" width="${W - 1}" height="${H - 1}" rx="14" stroke-width="1"/>

  ${header(data, t)}
  ${headline(data, t)}
  ${languageBarSegments(slices, data.totalLines, barGeo, "wbar")}
  ${legendSvg}
  ${heatSvg}

  <line class="brd" x1="${PAD}" y1="${divY}" x2="${W - PAD}" y2="${divY}" stroke-width="1"/>
  ${footer}
  ${provenance}
  ${pillParts.join("\n  ")}
  ${languageBarHover(slices, data.totalLines, barGeo, t.other)}
</svg>`;
}
