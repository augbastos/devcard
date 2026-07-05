// Alternate embed layouts: banner (480×72), half (480×~150), vertical (280).

import { CardData } from "./queries";
import { Theme, cssFor } from "./themes";
import { MONO, SANS, LANGUAGE_COLORS, FLAME_ICON, escapeXml, fmtCount, truncate, pick } from "./svg-utils";
import { Strings } from "./render";

function miniBar(data: CardData, x0: number, y: number, width: number, height: number): string {
  if (data.totalLines <= 0) return `<rect class="track" x="${x0}" y="${y}" width="${width}" height="${height}" rx="${height / 2}"/>`;
  let x = x0;
  const parts: string[] = [
    `<clipPath id="minibar"><rect x="${x0}" y="${y}" width="${width}" height="${height}" rx="${height / 2}"/></clipPath>`,
    `<rect class="track" x="${x0}" y="${y}" width="${width}" height="${height}" rx="${height / 2}"/>`,
    `<g clip-path="url(#minibar)">`,
  ];
  for (const lang of data.languages) {
    const w = (lang.total / data.totalLines) * width;
    const color = pick(LANGUAGE_COLORS, lang.language) ?? "#8b93a3";
    parts.push(
      `<rect x="${x.toFixed(2)}" y="${y}" width="${w.toFixed(2)}" height="${height}" fill="${color}"><title>${escapeXml(lang.language)}</title></rect>`
    );
    x += w;
  }
  parts.push(`</g>`);
  return parts.join("");
}

function flame(data: CardData, cx: number, cy: number, scale: number): string {
  const cls = data.streak >= 7 ? "accent" : "mut";
  return `<path class="${cls}" d="${FLAME_ICON}" transform="translate(${cx},${cy}) scale(${scale})"/>`;
}

function avatarCircle(data: CardData, cx: number, cy: number, r: number, id: string): string {
  return data.avatar
    ? `<clipPath id="${id}"><circle cx="${cx}" cy="${cy}" r="${r}"/></clipPath>
  <image href="${escapeXml(data.avatar)}" x="${cx - r}" y="${cy - r}" width="${r * 2}" height="${r * 2}" clip-path="url(#${id})" preserveAspectRatio="xMidYMid slice"/>
  <circle class="avbrd" cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke-width="1.2"/>`
    : `<circle class="pill" cx="${cx}" cy="${cy}" r="${r}"/><text class="mut" x="${cx}" y="${cy + 4}" ${SANS} font-size="${r * 0.8}" text-anchor="middle">${escapeXml(data.githubUser.charAt(0).toUpperCase())}</text>`;
}

export function renderBanner(data: CardData, theme: Theme, t: Strings): string {
  const W = 480;
  const H = 72;
  const PAD = 16;
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="devcard ${escapeXml(data.githubUser)}">
  <style>${cssFor(theme)}</style>
  <rect class="bg brd" x="0.5" y="0.5" width="${W - 1}" height="${H - 1}" rx="12" stroke-width="1"/>
  ${avatarCircle(data, PAD + 14, 27, 14, "avb")}
  <text class="txt" x="${PAD + 36}" y="31" ${MONO} font-size="13" font-weight="700">@${escapeXml(data.githubUser)}</text>
  <circle class="live" cx="${PAD + 36 + data.githubUser.length * 8 + 16}" cy="26.5" r="3.5">
    <animate attributeName="opacity" values="1;0.35;1" dur="2.4s" repeatCount="indefinite"/>
  </circle>
  <text x="${W - PAD}" y="31" text-anchor="end" font-size="13"><tspan class="txt" ${MONO} font-weight="700">${fmtCount(data.totalLines, t.dec)}</tspan><tspan class="mut" ${SANS} font-size="11"> ${escapeXml(t.lines)}</tspan><tspan ${MONO} font-size="13" font-weight="700" class="txt">  ${data.streak}</tspan><tspan class="mut" ${SANS} font-size="11">${escapeXml(t.streakAbbr)}</tspan></text>
  ${flame(data, W - PAD - 118 - String(data.streak).length * 8, 26, 0.8)}
  ${miniBar(data, PAD, 46, W - PAD * 2, 8)}
</svg>`;
}

export function renderHalf(data: CardData, theme: Theme, t: Strings): string {
  const W = 480;
  const H = 152;
  const PAD = 20;
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="devcard ${escapeXml(data.githubUser)}">
  <style>${cssFor(theme)}</style>
  <rect class="bg brd" x="0.5" y="0.5" width="${W - 1}" height="${H - 1}" rx="12" stroke-width="1"/>
  ${avatarCircle(data, PAD + 15, 30, 15, "avh")}
  <text class="txt" x="${PAD + 40}" y="27" ${SANS} font-size="13.5" font-weight="700">devcard</text>
  <text class="mut" x="${PAD + 40}" y="41" ${MONO} font-size="11">@${escapeXml(data.githubUser)}</text>
  <a href="https://github.com/${escapeXml(data.githubUser)}?tab=repositories" target="_blank">
    <text class="link" x="${W - PAD}" y="31" ${MONO} font-size="11.5" text-anchor="end">${data.repoCount} ${escapeXml(t.repos)} →</text>
  </a>
  <text class="txt" x="${PAD}" y="86" ${MONO} font-size="24" font-weight="700">${fmtCount(data.totalLines, t.dec)}<tspan class="mut" ${SANS} font-size="11.5" font-weight="400"> ${escapeXml(t.lines)}</tspan></text>
  ${miniBar(data, PAD, 100, W - PAD * 2, 10)}
  <text x="${PAD}" y="134" font-size="11.5"><tspan class="txt" ${MONO} font-weight="700">${data.totalActions}</tspan><tspan class="mut" ${SANS}> ${escapeXml(t.edits)}</tspan><tspan ${MONO}> </tspan><tspan class="txt" ${MONO} font-weight="700">  ${data.totalCommits}</tspan><tspan class="mut" ${SANS}> ${escapeXml(t.commits)}</tspan></text>
  ${flame(data, W - PAD - 44 - String(data.streak).length * 7, 129, 0.75)}
  <text x="${W - PAD}" y="134" text-anchor="end" font-size="11.5"><tspan class="txt" ${MONO} font-weight="700">${data.streak}</tspan><tspan class="mut" ${SANS}> ${escapeXml(t.dayStreak)}</tspan></text>
</svg>`;
}

export function renderVertical(data: CardData, theme: Theme, t: Strings): string {
  const W = 280;
  const PAD = 18;
  const topLangs = data.languages.slice(0, 3);
  const legendTop = 158;
  const rowH = 20;
  const legend = topLangs
    .map((lang, i) => {
      const pct = data.totalLines > 0 ? ((lang.total / data.totalLines) * 100).toFixed(1) : "0.0";
      const y = legendTop + i * rowH;
      const color = pick(LANGUAGE_COLORS, lang.language) ?? "#8b93a3";
      return (
        `<circle cx="${PAD + 5}" cy="${y - 4}" r="4" fill="${color}"/>` +
        `<text class="txt" x="${PAD + 16}" y="${y}" ${SANS} font-size="12">${escapeXml(truncate(lang.language, 14))}</text>` +
        `<text class="mut" x="${W - PAD}" y="${y}" ${MONO} font-size="11" text-anchor="end">${pct}%</text>`
      );
    })
    .join("\n  ");
  const legendBottom = topLangs.length === 0 ? legendTop : legendTop + (topLangs.length - 1) * rowH;
  const statY = legendBottom + 26;
  const H = statY + 40;

  return `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="devcard ${escapeXml(data.githubUser)}">
  <style>${cssFor(theme)}</style>
  <rect class="bg brd" x="0.5" y="0.5" width="${W - 1}" height="${H - 1}" rx="14" stroke-width="1"/>
  ${avatarCircle(data, W / 2, 40, 22, "avv")}
  <text class="txt" x="${W / 2}" y="80" ${MONO} font-size="13" font-weight="700" text-anchor="middle">@${escapeXml(data.githubUser)}</text>
  <text class="txt" x="${W / 2}" y="112" ${MONO} font-size="24" font-weight="700" text-anchor="middle">${fmtCount(data.totalLines, t.dec)}</text>
  <text class="mut" x="${W / 2}" y="128" ${SANS} font-size="10.5" text-anchor="middle">${escapeXml(t.lines)}</text>
  ${miniBar(data, PAD, 138, W - PAD * 2, 8)}
  ${legend}
  ${flame(data, PAD + 8, statY - 4, 0.8)}
  <text x="${PAD + 20}" y="${statY}" font-size="12"><tspan class="txt" ${MONO} font-weight="700">${data.streak}</tspan><tspan class="mut" ${SANS} font-size="10.5"> ${escapeXml(t.dayStreak)}</tspan></text>
  <a href="https://github.com/${escapeXml(data.githubUser)}?tab=repositories" target="_blank">
    <text class="link" x="${W - PAD}" y="${statY}" ${MONO} font-size="11" text-anchor="end">${data.repoCount} ${escapeXml(t.repos)} →</text>
  </a>
</svg>`;
}
