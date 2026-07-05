// Full card layout (the default). Receives data + theme + strings; pure.

import { CardData } from "./queries";
import { Theme, cssFor } from "./themes";
import {
  MONO,
  SANS,
  LANGUAGE_COLORS,
  KIND_ICONS,
  HEART_ICON,
  REPO_ICON,
  FLAME_ICON,
  escapeXml,
  truncate,
  fmtCount,
  fmtBytes,
  fmtAge,
  pick,
} from "./svg-utils";

export interface Strings {
  lines: string;
  edits: string;
  commits: string;
  repos: string;
  since: string;
  events: string;
  dayStreak: string;
  streakAbbr: string; // ultra-short suffix for the banner layout
  updatedAgo: string; // contains {X}
  dec: string;
  locale: string; // for month names
}

export function renderHeatmap(
  data: CardData,
  x0: number,
  top: number,
  cell: number,
  gap: number
): { svg: string; height: number } {
  const step = cell + gap;
  const labelH = 12;
  const marks = data.monthMarks
    .map((m) => `<text class="faint" x="${x0 + m.weekIndex * step}" y="${top + 8}" ${MONO} font-size="8.5">${escapeXml(m.label)}</text>`)
    .join("");
  const cells: string[] = [];
  data.heatWeeks.forEach((week, w) => {
    week.forEach((c, d) => {
      cells.push(
        `<rect class="heat${c.level}" x="${x0 + w * step}" y="${top + labelH + d * step}" width="${cell}" height="${cell}" rx="2"><title>${c.day}: ${c.lines}</title></rect>`
      );
    });
  });
  return { svg: marks + cells.join(""), height: labelH + 7 * step - gap };
}

export function streakBlock(data: CardData, t: Strings, rightX: number, baseY: number): string {
  const hot = data.streak >= 7;
  const cls = hot ? "accent" : "mut";
  const flame = `<path class="${cls}" d="${FLAME_ICON}" transform="translate(${rightX - 8},${baseY - 8}) scale(1.15)"/>`;
  const num = `<text class="txt" x="${rightX - 20}" y="${baseY}" ${MONO} font-size="26" font-weight="700" text-anchor="end">${data.streak}</text>`;
  const label = `<text class="mut" x="${rightX}" y="${baseY + 16}" ${SANS} font-size="10.5" text-anchor="end">${escapeXml(t.dayStreak)}</text>`;
  return flame + num + label;
}

export function renderFull(data: CardData, theme: Theme, t: Strings): string {
  const W = 480;
  const PAD = 24;

  const avatarSvg = data.avatar
    ? `<clipPath id="av"><circle cx="42" cy="36" r="17"/></clipPath>
  <image href="${escapeXml(data.avatar)}" x="25" y="19" width="34" height="34" clip-path="url(#av)" preserveAspectRatio="xMidYMid slice"/>
  <circle class="avbrd" cx="42" cy="36" r="17" fill="none" stroke-width="1.5"/>`
    : `<circle class="pill" cx="42" cy="36" r="17"/><text class="mut" x="42" y="41" ${SANS} font-size="14" text-anchor="middle">${escapeXml(data.githubUser.charAt(0).toUpperCase())}</text>`;
  const headX = 68;

  // -- bar --
  const barY = 130;
  const barH = 12;
  const barW = W - PAD * 2;
  let x = PAD;
  const segs: string[] = [];
  const seps: string[] = [];
  for (const lang of data.languages) {
    const w = data.totalLines > 0 ? (lang.total / data.totalLines) * barW : 0;
    const color = pick(LANGUAGE_COLORS, lang.language) ?? "#8b93a3";
    segs.push(
      `<rect x="${x.toFixed(2)}" y="${barY}" width="${w.toFixed(2)}" height="${barH}" fill="${color}"><title>${escapeXml(lang.language)}</title></rect>`
    );
    x += w;
    if (x < PAD + barW - 1) seps.push(`<rect class="sep" x="${(x - 1).toFixed(2)}" y="${barY}" width="2" height="${barH}"/>`);
  }

  // -- legend --
  const legendTop = 172;
  const rowH = 21;
  const colX = [PAD, PAD + barW / 2 + 8];
  const legend = data.languages
    .slice(0, 6)
    .map((lang, i) => {
      const pct = data.totalLines > 0 ? ((lang.total / data.totalLines) * 100).toFixed(1) : "0.0";
      const cx = colX[Math.floor(i / 3)];
      const y = legendTop + (i % 3) * rowH;
      const color = pick(LANGUAGE_COLORS, lang.language) ?? "#8b93a3";
      return (
        `<circle cx="${cx + 5}" cy="${y - 4}" r="4.5" fill="${color}"/>` +
        `<text class="txt" x="${cx + 17}" y="${y}" ${SANS} font-size="12.5">${escapeXml(lang.language)}` +
        `<tspan class="mut" ${MONO} font-size="11.5"> ${pct}%</tspan></text>`
      );
    })
    .join("\n  ");
  const legendBottom = data.languages.length === 0 ? legendTop : legendTop + (Math.min(data.languages.length, 3) - 1) * rowH;

  // -- heatmap (centered) --
  const heatTop = legendBottom + 18;
  const cellSize = 8;
  const cellGap = 2;
  const gridW = 16 * (cellSize + cellGap) - cellGap;
  const heatX = PAD + Math.floor((barW - gridW) / 2);
  const heat = renderHeatmap(data, heatX, heatTop, cellSize, cellGap);
  const heatBottom = heatTop + heat.height;

  // -- pinned repos --
  let pinnedSvg = "";
  let pinnedBottom = heatBottom;
  if (data.pins.length > 0) {
    const pinTop = heatBottom + 16;
    const boxH = 42;
    const gap = 10;
    const boxW = (barW - gap * (data.pins.length - 1)) / data.pins.length;
    pinnedSvg = data.pins
      .map((p, i) => {
        const bx = PAD + i * (boxW + gap);
        const starTxt = p.stars !== null ? `★ ${p.stars}` : "";
        const noteTxt = truncate(p.note ?? "", Math.floor(boxW / 6.2) - (starTxt ? starTxt.length + 2 : 0));
        const sub = [starTxt, noteTxt].filter(Boolean).join("  ");
        return (
          `<a href="https://github.com/${escapeXml(data.githubUser)}/${escapeXml(p.repo)}" target="_blank">` +
          `<rect class="pill" x="${bx.toFixed(1)}" y="${pinTop}" width="${boxW.toFixed(1)}" height="${boxH}" rx="8"/>` +
          `<path class="mut" d="${REPO_ICON}" transform="translate(${(bx + 14).toFixed(1)},${pinTop + 16}) scale(0.9)"/>` +
          `<text class="txt" x="${(bx + 28).toFixed(1)}" y="${pinTop + 18}" ${SANS} font-size="12" font-weight="700">${escapeXml(truncate(p.repo, Math.floor(boxW / 7.5)))}</text>` +
          `<text class="mut" x="${(bx + 10).toFixed(1)}" y="${pinTop + 33}" ${SANS} font-size="10.5">${escapeXml(sub)}</text>` +
          `</a>`
        );
      })
      .join("\n  ");
    pinnedBottom = pinTop + boxH;
  }

  // -- footer: two stats + provenance-with-staleness --
  const divY = pinnedBottom + 16;
  const footY = divY + 26;
  const stat = (xPos: number, n: string, label: string) =>
    `<text x="${xPos}" y="${footY}" font-size="12"><tspan class="txt" ${MONO} font-weight="700">${n}</tspan><tspan class="mut" ${SANS}> ${escapeXml(label)}</tspan></text>`;
  const footer = stat(PAD, String(data.totalActions), t.edits) + stat(PAD + 200, String(data.totalCommits), t.commits);

  const nowSec = Math.floor(Date.now() / 1000);
  const age = fmtAge(data.updatedAt, nowSec);
  const sinceDate = data.firstTs ? new Date(data.firstTs * 1000).toISOString().slice(0, 10) : null;
  const provParts: string[] = [];
  if (sinceDate) provParts.push(`${t.since} ${sinceDate}`, `${data.totalEvents.toLocaleString("en-US")} ${t.events}`);
  if (age) provParts.push(t.updatedAgo.replace("{X}", age));
  const provenanceLine = provParts.length
    ? `<text class="faint" x="${W - PAD}" y="${footY + 18}" ${MONO} font-size="9.5" text-anchor="end">${escapeXml(provParts.join(" · "))}</text>`
    : "";

  // -- pills --
  const pillTop = footY + 26;
  let pillX = PAD;
  let pillRow = 0;
  const pillParts: string[] = [];
  const addPill = (label: string, iconPath: string | null, opts?: { cls?: string; iconCls?: string; href?: string }) => {
    const iconSpace = iconPath ? 16 : 0;
    const w = Math.round(label.length * 6.2) + 20 + iconSpace;
    if (pillX + w > W - PAD) {
      pillRow += 1;
      pillX = PAD;
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
  const pills = pillParts.join("\n  ");
  const pillRowsUsed = pillParts.length > 0 ? pillRow + 1 : 0;

  const H = pillTop + (pillRowsUsed > 0 ? pillRowsUsed * 28 : 0) + 4;

  return `<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="devcard ${escapeXml(data.githubUser)}">
  <style>${cssFor(theme)}</style>
  <rect class="bg brd" x="0.5" y="0.5" width="${W - 1}" height="${H - 1}" rx="14" stroke-width="1"/>

  ${avatarSvg}
  <text class="txt" x="${headX}" y="32" ${SANS} font-size="15" font-weight="700">devcard</text>
  <text class="mut" x="${headX}" y="48" ${MONO} font-size="12">@${escapeXml(data.githubUser)}</text>
  <circle class="live" cx="${headX + 66}" cy="27.5" r="4">
    <animate attributeName="opacity" values="1;0.35;1" dur="2.4s" repeatCount="indefinite"/>
  </circle>
  <a href="https://github.com/${escapeXml(data.githubUser)}?tab=repositories" target="_blank">
    <text class="link" x="${W - PAD}" y="36" ${MONO} font-size="12" text-anchor="end">${data.repoCount} ${escapeXml(t.repos)} →</text>
  </a>

  <text class="txt" x="${PAD}" y="106" ${MONO} font-size="30" font-weight="700">${fmtCount(data.totalLines, t.dec)}<tspan class="mut" ${SANS} font-size="12" font-weight="400"> ${escapeXml(t.lines)}</tspan><tspan class="faint" ${MONO} font-size="11" font-weight="400"> (${fmtBytes(data.totalBytes, t.dec)})</tspan></text>
  ${streakBlock(data, t, W - PAD, 106)}

  <clipPath id="barclip"><rect x="${PAD}" y="${barY}" width="${barW}" height="${barH}" rx="6"/></clipPath>
  <rect class="track" x="${PAD}" y="${barY}" width="${barW}" height="${barH}" rx="6"/>
  <g clip-path="url(#barclip)">
    ${segs.join("\n    ")}
    ${seps.join("\n    ")}
  </g>

  ${legend}

  ${heat.svg}

  ${pinnedSvg}

  <line class="brd" x1="${PAD}" y1="${divY}" x2="${W - PAD}" y2="${divY}" stroke-width="1"/>
  ${footer}
  ${provenanceLine}
  ${pills}
</svg>`;
}
