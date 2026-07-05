// Shared SVG/formatting helpers used by every card layout.

export const MONO = 'font-family="ui-monospace,SFMono-Regular,Consolas,monospace"';
export const SANS = `font-family="-apple-system,'Segoe UI',Roboto,'Helvetica Neue',sans-serif"`;

export const LANGUAGE_COLORS: Record<string, string> = {
  Python: "#3572A5",
  JavaScript: "#f1e05a",
  TypeScript: "#3178c6",
  HTML: "#e34c26",
  CSS: "#563d7c",
  Rust: "#dea584",
  PowerShell: "#012456",
  SQL: "#336790",
  Markdown: "#083fa1",
  JSON: "#292929",
  YAML: "#cb171e",
  TOML: "#9c4221",
  Shell: "#89e051",
  Go: "#00add8",
  Java: "#b07219",
  C: "#555555",
  "C++": "#f34b7d",
  Ruby: "#701516",
  PHP: "#4f5d95",
};

export const KIND_ICONS: Record<string, string> = {
  badge: "M0,-6 L1.8,-1.9 6,-1.9 2.7,0.9 3.7,5 0,2.4 -3.7,5 -2.7,0.9 -6,-1.9 -1.8,-1.9 Z",
  certification: "M0,-5.5 A5.5,5.5 0 1 0 0.01,-5.5 Z M-2.6,-0.2 L-0.7,1.8 L2.8,-2 L1.8,-3 L-0.7,-0.3 L-1.6,-1.2 Z",
  award:
    "M-4.5,-6 h9 v2.5 a4.5,4.5 0 0 1 -3.2,4.3 L1,3 h2 v2 h-6 v-2 h2 l-0.3,-2.2 A4.5,4.5 0 0 1 -4.5,-3.5 Z",
};

export const HEART_ICON =
  "M0,4 C-4.6,0.6 -4.6,-3.4 -1.7,-3.4 C-0.6,-3.4 0,-2.5 0,-2.5 C0,-2.5 0.6,-3.4 1.7,-3.4 C4.6,-3.4 4.6,0.6 0,4 Z";

export const REPO_ICON =
  "M0,-5 h7 a2,2 0 0 1 2,2 v8 h-9 a2,2 0 0 0 -2,2 v-10 a2,2 0 0 1 2,-2 Z M-2,7 h11 v3 h-9 a2,2 0 0 1 -2,-2 Z";

// Teardrop flame, centered on (0,0), ~14px tall at scale 1.
export const FLAME_ICON =
  "M0.2,-7 C2.8,-4 4.6,-1.6 4.6,0.9 A4.7,4.7 0 0 1 -4.6,0.9 C-4.6,-0.9 -3.6,-2.4 -2.4,-3.7 C-2.1,-2.7 -1.5,-2 -0.6,-1.5 C-1,-3.4 -0.7,-5.2 0.2,-7 Z";

export function escapeXml(value: string): string {
  return value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

// Own-property lookup — a language/kind named "constructor" must miss, not
// resolve to Object.prototype garbage.
export function pick<T>(map: Record<string, T>, key: string): T | undefined {
  return Object.prototype.hasOwnProperty.call(map, key) ? map[key] : undefined;
}

export function truncate(s: string, max: number): string {
  return s.length > max ? s.slice(0, Math.max(1, max - 1)) + "…" : s;
}

// 12,837 → "12,837" · 171,340 → "171k" · 2,610,000 → "2.6m" (decimal separator per locale)
export function fmtCount(n: number, dec: string): string {
  if (n < 100000) return n.toLocaleString("en-US");
  const units: [number, string][] = [
    [1e12, "t"],
    [1e9, "b"],
    [1e6, "m"],
    [1e3, "k"],
  ];
  for (const [size, suffix] of units) {
    if (n >= size) {
      const v = n / size;
      const text = v < 10 ? v.toFixed(1).replace(".", dec) : String(Math.round(v));
      return text + suffix;
    }
  }
  return String(n);
}

export function fmtBytes(n: number, dec: string): string {
  const units: [number, string][] = [
    [1e12, "tb"],
    [1e9, "gb"],
    [1e6, "mb"],
    [1e3, "kb"],
  ];
  for (const [size, suffix] of units) {
    if (n >= size) {
      const v = n / size;
      const text = v < 10 ? v.toFixed(1).replace(".", dec) : String(Math.round(v));
      return text + suffix;
    }
  }
  return `${n}b`;
}

// "5min" / "3h" for < 24h; ISO date beyond that. Returns null when never synced.
export function fmtAge(updatedAt: number, nowSec: number): string | null {
  if (!updatedAt) return null;
  const diff = Math.max(0, nowSec - updatedAt);
  if (diff < 3600) return `${Math.max(1, Math.round(diff / 60))}min`;
  if (diff < 86400) return `${Math.round(diff / 3600)}h`;
  return new Date(updatedAt * 1000).toISOString().slice(0, 10);
}
