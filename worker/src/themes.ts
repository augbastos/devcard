// Theme system. `default` keeps the original behavior: light palette with an
// automatic dark override via prefers-color-scheme. Named themes (dracula,
// tokyonight) are deliberately single-look — their identity IS the palette,
// so they don't get a light variant.

export interface Tokens {
  bg: string;
  brd: string;
  txt: string;
  mut: string;
  faint: string;
  track: string;
  sep: string;
  pill: string;
  pillStroke: string;
  pillSp: string;
  pillSpStroke: string;
  heart: string;
  link: string;
  avbrd: string;
  accent: string; // flame / streak highlight
  live: string; // pulse dot
  heat: [string, string, string, string, string]; // levels 0..4
}

export interface Theme {
  base: Tokens;
  dark?: Tokens; // when present, emitted under prefers-color-scheme: dark
}

const DEFAULT_LIGHT: Tokens = {
  bg: "#ffffff",
  brd: "#d8dce4",
  txt: "#1b1f27",
  mut: "#6b7280",
  faint: "#9aa1ac",
  track: "#edeff4",
  sep: "#ffffff",
  pill: "#f2f4f8",
  pillStroke: "#d8dce4",
  pillSp: "#fff0f3",
  pillSpStroke: "#f1b8c4",
  heart: "#d1355f",
  link: "#0969da",
  avbrd: "#d8dce4",
  accent: "#e8590c",
  live: "#3fb950",
  heat: ["#ebedf0", "#9be9a8", "#40c463", "#30a14e", "#216e39"],
};

const DEFAULT_DARK: Tokens = {
  bg: "#0f1117",
  brd: "#262b38",
  txt: "#e6e9f0",
  mut: "#8b93a3",
  faint: "#5b6270",
  track: "#1e2230",
  sep: "#0f1117",
  pill: "#171a24",
  pillStroke: "#262b38",
  pillSp: "#2a1620",
  pillSpStroke: "#6e2a3d",
  heart: "#f47892",
  link: "#58a6ff",
  avbrd: "#262b38",
  accent: "#ff922b",
  live: "#3fb950",
  heat: ["#161b22", "#0e4429", "#006d32", "#26a641", "#39d353"],
};

const DARK: Tokens = {
  bg: "#11131a",
  brd: "#262b3a",
  txt: "#eef0f5",
  mut: "#9098ab",
  faint: "#5c6478",
  track: "#1c2029",
  sep: "#11131a",
  pill: "#191d27",
  pillStroke: "#262b3a",
  pillSp: "#2b1922",
  pillSpStroke: "#7a3349",
  heart: "#f2789a",
  link: "#6cb6ff",
  avbrd: "#262b3a",
  accent: "#ff9d4d",
  live: "#3fd67a",
  heat: ["#171c22", "#0f3d29", "#0e6b3a", "#22a355", "#52e08a"],
};

const LIGHT: Tokens = {
  bg: "#fdfbf7",
  brd: "#ddd5c8",
  txt: "#211d17",
  mut: "#6b6255",
  faint: "#9a917f",
  track: "#efe9df",
  sep: "#fdfbf7",
  pill: "#f5f1e9",
  pillStroke: "#ddd5c8",
  pillSp: "#fdeef1",
  pillSpStroke: "#eab8c4",
  heart: "#c93762",
  link: "#1b6fc9",
  avbrd: "#ddd5c8",
  accent: "#d9600c",
  live: "#2ea043",
  heat: ["#e8ecdf", "#9fe9a3", "#4cc463", "#2fa14e", "#1f6e39"],
};

// Soft, elegant, warm — rosé/lilac/cream.
const GENTLE: Tokens = {
  bg: "#fdf2f0",
  brd: "#e8c9d1",
  txt: "#4a1f3d",
  mut: "#8a5468",
  faint: "#b98a9c",
  track: "#f2dde1",
  sep: "#fdf2f0",
  pill: "#f8e6ea",
  pillStroke: "#e8c9d1",
  pillSp: "#ffe3ee",
  pillSpStroke: "#ef93bd",
  heart: "#d6316f",
  link: "#7d4fa0",
  avbrd: "#e8c9d1",
  accent: "#e2795f",
  live: "#7cc48f",
  heat: ["#f6dfe4", "#edc0cd", "#df8fab", "#c14f83", "#8f1457"],
};

// Neon noir — violet black, hot pink, cyan, acid yellow.
const CYBERPUNK: Tokens = {
  bg: "#0a0818",
  brd: "#33224f",
  txt: "#ece8ff",
  mut: "#9b8fc0",
  faint: "#5f5480",
  track: "#190f34",
  sep: "#0a0818",
  pill: "#170f2c",
  pillStroke: "#3a2960",
  pillSp: "#2a0f2e",
  pillSpStroke: "#ff2fa8",
  heart: "#ff3f8f",
  link: "#22d3ee",
  avbrd: "#33224f",
  accent: "#e2ff26",
  live: "#00ff9d",
  heat: ["#150c2a", "#301a52", "#5c2a8a", "#a52bc4", "#ff33d6"],
};

// Green-phosphor CRT, single amber accent.
const TERMINAL: Tokens = {
  bg: "#061309",
  brd: "#1c4526",
  txt: "#39ff6a",
  mut: "#1fbf55",
  faint: "#0f6f34",
  track: "#0d2415",
  sep: "#061309",
  pill: "#0b2013",
  pillStroke: "#1c4526",
  pillSp: "#2b1d06",
  pillSpStroke: "#b8860b",
  heart: "#ffb000",
  link: "#4dffa3",
  avbrd: "#1c4526",
  accent: "#ffb000",
  live: "#33ff66",
  heat: ["#0a1f10", "#134f26", "#1f8f3f", "#39cc5c", "#7dffa8"],
};

export const THEMES: Record<string, Theme> = {
  default: { base: DEFAULT_LIGHT, dark: DEFAULT_DARK },
  dark: { base: DARK },
  light: { base: LIGHT },
  gentle: { base: GENTLE },
  cyberpunk: { base: CYBERPUNK },
  terminal: { base: TERMINAL },
};

export function pickTheme(name: string | null): Theme {
  return (name && THEMES[name]) || THEMES.default;
}

function tokenCss(k: Tokens): string {
  return (
    `.bg{fill:${k.bg}}.brd{stroke:${k.brd}}.txt{fill:${k.txt}}.mut{fill:${k.mut}}.faint{fill:${k.faint}}` +
    `.track{fill:${k.track}}.sep{fill:${k.sep}}` +
    `.pill{fill:${k.pill};stroke:${k.pillStroke}}.pill-sp{fill:${k.pillSp};stroke:${k.pillSpStroke}}.heart{fill:${k.heart}}` +
    `.link{fill:${k.link}}.avbrd{stroke:${k.avbrd}}.accent{fill:${k.accent}}.live{fill:${k.live}}` +
    k.heat.map((c, i) => `.heat${i}{fill:${c}}`).join("")
  );
}

export function cssFor(theme: Theme): string {
  let css = tokenCss(theme.base);
  if (theme.dark) {
    css += `@media(prefers-color-scheme:dark){${tokenCss(theme.dark)}}`;
  }
  return css;
}
