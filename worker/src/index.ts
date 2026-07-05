export interface Env {
  DB: D1Database;
  INGEST_TOKEN: string;
  GITHUB_USERNAME: string;
}

interface IngestEvent {
  id?: number;
  ts: number;
  language: string | null;
  lines_added: number;
  lines_removed: number;
  event_type: string;
}

const LANGUAGE_COLORS: Record<string, string> = {
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

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (request.method === "POST" && url.pathname === "/ingest") {
      return handleIngest(request, env);
    }
    if (request.method === "GET" && url.pathname === "/svg") {
      return handleSvg(request, env);
    }
    return new Response("not found", { status: 404 });
  },
};

async function handleIngest(request: Request, env: Env): Promise<Response> {
  const token = request.headers.get("X-Devcard-Token");
  if (!token || token !== env.INGEST_TOKEN) {
    return new Response("unauthorized", { status: 401 });
  }

  let body: { events: IngestEvent[]; repo_count?: number };
  try {
    body = await request.json();
  } catch {
    return new Response("bad json", { status: 400 });
  }

  if (!Array.isArray(body.events)) {
    return new Response("events must be an array", { status: 400 });
  }

  const statements = body.events.map((e) =>
    env.DB.prepare(
      "INSERT OR IGNORE INTO events (ts, language, lines_added, lines_removed, event_type, client_event_id) VALUES (?, ?, ?, ?, ?, ?)"
    ).bind(e.ts, e.language, e.lines_added, e.lines_removed, e.event_type, e.id ?? null)
  );

  if (typeof body.repo_count === "number") {
    statements.push(
      env.DB.prepare("UPDATE stats_snapshot SET repo_count = ?, updated_at = ? WHERE id = 1").bind(
        body.repo_count,
        Math.floor(Date.now() / 1000)
      )
    );
  }

  if (statements.length > 0) {
    await env.DB.batch(statements);
  }

  return Response.json({ inserted: body.events.length });
}

interface Strings {
  lines: string;
  activeDays: string;
  edits: string;
  commits: string;
  repos: string;
}

const STRINGS: Record<string, Strings> = {
  en: { lines: "lines of code", activeDays: "active days (30d)", edits: "code edits", commits: "commits", repos: "repos" },
  pt: { lines: "linhas de código", activeDays: "dias ativos (30d)", edits: "edições de código", commits: "commits", repos: "repos" },
  es: { lines: "líneas de código", activeDays: "días activos (30d)", edits: "ediciones de código", commits: "commits", repos: "repos" },
};

function pickLang(request: Request, url: URL): Strings {
  const forced = url.searchParams.get("lang");
  if (forced && STRINGS[forced]) return STRINGS[forced];
  const header = (request.headers.get("Accept-Language") ?? "").toLowerCase();
  for (const part of header.split(",")) {
    const tag = part.split(";")[0].trim().split("-")[0];
    if (STRINGS[tag]) return STRINGS[tag];
  }
  return STRINGS.en;
}

async function fetchAvatarDataUri(user: string): Promise<string | null> {
  const url = `https://github.com/${user}.png?size=96`;
  const cache = caches.default;
  const cacheKey = new Request(url);
  let resp = await cache.match(cacheKey);
  if (!resp) {
    try {
      resp = await fetch(url, { redirect: "follow" });
      if (!resp.ok) return null;
      resp = new Response(resp.body, resp);
      resp.headers.set("Cache-Control", "public, max-age=86400");
      await cache.put(cacheKey, resp.clone());
    } catch {
      return null;
    }
  }
  const buf = new Uint8Array(await resp.arrayBuffer());
  let binary = "";
  for (let i = 0; i < buf.length; i += 8192) {
    binary += String.fromCharCode(...buf.subarray(i, i + 8192));
  }
  const ct = resp.headers.get("Content-Type") ?? "image/png";
  return `data:${ct};base64,${btoa(binary)}`;
}

async function hasSponsors(user: string): Promise<boolean> {
  const url = `https://github.com/sponsors/${user}`;
  const cache = caches.default;
  const cacheKey = new Request(url + "#devcard-check");
  const hit = await cache.match(cacheKey);
  if (hit) return (await hit.text()) === "1";
  let active = false;
  try {
    const resp = await fetch(url, { method: "HEAD", redirect: "manual" });
    active = resp.status === 200;
  } catch {
    active = false;
  }
  await cache.put(
    cacheKey,
    new Response(active ? "1" : "0", { headers: { "Cache-Control": "public, max-age=86400" } })
  );
  return active;
}

async function handleSvg(request: Request, env: Env): Promise<Response> {
  const url = new URL(request.url);
  const requestedUser = url.searchParams.get("user");
  if (requestedUser && requestedUser !== env.GITHUB_USERNAME) {
    return new Response("unknown user", { status: 404 });
  }
  const t = pickLang(request, url);
  const [avatar, sponsorable] = await Promise.all([
    fetchAvatarDataUri(env.GITHUB_USERNAME),
    hasSponsors(env.GITHUB_USERNAME),
  ]);

  const langRows = await env.DB.prepare(
    "SELECT language, SUM(lines_added) as total FROM events WHERE language IS NOT NULL GROUP BY language ORDER BY total DESC"
  ).all();

  const streakRow = await env.DB.prepare(
    "SELECT COUNT(DISTINCT date(ts, 'unixepoch')) as days FROM events WHERE ts >= ?"
  )
    .bind(Math.floor(Date.now() / 1000) - 30 * 86400)
    .first();

  const eventTypeRows = await env.DB.prepare("SELECT event_type, COUNT(*) as n FROM events GROUP BY event_type").all();

  const snapshot = await env.DB.prepare("SELECT repo_count FROM stats_snapshot WHERE id = 1").first();

  const profileRows = await env.DB.prepare(
    "SELECT kind, label FROM profile_entries ORDER BY created_at DESC LIMIT 8"
  ).all();

  const languages = (langRows.results as { language: string; total: number }[]) ?? [];
  const totalLines = languages.reduce((sum, l) => sum + l.total, 0);
  const repoCount = (snapshot as { repo_count: number } | null)?.repo_count ?? 0;
  const activeDays = (streakRow as { days: number } | null)?.days ?? 0;
  const badges = (profileRows.results as { kind: string; label: string }[]) ?? [];

  const eventCounts = (eventTypeRows.results as { event_type: string; n: number }[]) ?? [];
  const totalCommits = eventCounts.find((r) => r.event_type === "commit")?.n ?? 0;
  const totalActions = eventCounts
    .filter((r) => r.event_type === "edit" || r.event_type === "write")
    .reduce((sum, r) => sum + r.n, 0);

  const svg = renderCard({
    languages,
    totalLines,
    repoCount,
    activeDays,
    badges,
    totalCommits,
    totalActions,
    githubUser: env.GITHUB_USERNAME,
    t,
    avatar,
    sponsorable,
  });

  return new Response(svg, {
    headers: {
      "Content-Type": "image/svg+xml; charset=utf-8",
      "Cache-Control": "public, max-age=60",
      "Vary": "Accept-Language",
    },
  });
}

const KIND_ICONS: Record<string, string> = {
  badge: "M0,-6 L1.8,-1.9 6,-1.9 2.7,0.9 3.7,5 0,2.4 -3.7,5 -2.7,0.9 -6,-1.9 -1.8,-1.9 Z",
  certification: "M0,-5.5 A5.5,5.5 0 1 0 0.01,-5.5 Z M-2.6,-0.2 L-0.7,1.8 L2.8,-2 L1.8,-3 L-0.7,-0.3 L-1.6,-1.2 Z",
  award:
    "M-4.5,-6 h9 v2.5 a4.5,4.5 0 0 1 -3.2,4.3 L1,3 h2 v2 h-6 v-2 h2 l-0.3,-2.2 A4.5,4.5 0 0 1 -4.5,-3.5 Z",
};
const HEART_ICON =
  "M0,4 C-4.6,0.6 -4.6,-3.4 -1.7,-3.4 C-0.6,-3.4 0,-2.5 0,-2.5 C0,-2.5 0.6,-3.4 1.7,-3.4 C4.6,-3.4 4.6,0.6 0,4 Z";

function renderCard(data: {
  languages: { language: string; total: number }[];
  totalLines: number;
  repoCount: number;
  activeDays: number;
  badges: { kind: string; label: string }[];
  totalCommits: number;
  totalActions: number;
  githubUser: string;
  t: Strings;
  avatar: string | null;
  sponsorable: boolean;
}): string {
  const W = 480;
  const PAD = 24;
  const t = data.t;
  const mono = 'font-family="ui-monospace,SFMono-Regular,Consolas,monospace"';
  const sans = `font-family="-apple-system,'Segoe UI',Roboto,'Helvetica Neue',sans-serif"`;

  // -- header: avatar + wordmark --
  const avatarSvg = data.avatar
    ? `<clipPath id="av"><circle cx="42" cy="36" r="17"/></clipPath>
  <image href="${data.avatar}" x="25" y="19" width="34" height="34" clip-path="url(#av)" preserveAspectRatio="xMidYMid slice"/>
  <circle class="avbrd" cx="42" cy="36" r="17" fill="none" stroke-width="1.5"/>`
    : `<circle class="pill" cx="42" cy="36" r="17"/><text class="mut" x="42" y="41" ${sans} font-size="14" text-anchor="middle">${escapeXml(data.githubUser.charAt(0).toUpperCase())}</text>`;
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
    const color = LANGUAGE_COLORS[lang.language] ?? "#8b93a3";
    segs.push(
      `<rect x="${x.toFixed(2)}" y="${barY}" width="${w.toFixed(2)}" height="${barH}" fill="${color}"><title>${escapeXml(lang.language)}</title></rect>`
    );
    x += w;
    if (x < PAD + barW - 1) seps.push(`<rect class="sep" x="${(x - 1).toFixed(2)}" y="${barY}" width="2" height="${barH}"/>`);
  }

  // -- legend: 2 columns x 3 rows --
  const legendTop = 172;
  const rowH = 21;
  const colX = [PAD, PAD + barW / 2 + 8];
  const legend = data.languages
    .slice(0, 6)
    .map((lang, i) => {
      const pct = data.totalLines > 0 ? ((lang.total / data.totalLines) * 100).toFixed(1) : "0.0";
      const cx = colX[Math.floor(i / 3)];
      const y = legendTop + (i % 3) * rowH;
      const color = LANGUAGE_COLORS[lang.language] ?? "#8b93a3";
      return (
        `<circle cx="${cx + 5}" cy="${y - 4}" r="4.5" fill="${color}"/>` +
        `<text class="txt" x="${cx + 17}" y="${y}" ${sans} font-size="12.5">${escapeXml(lang.language)}` +
        `<tspan class="mut" ${mono} font-size="11.5"> ${pct}%</tspan></text>`
      );
    })
    .join("\n  ");

  const legendBottom = data.languages.length === 0 ? legendTop : legendTop + (Math.min(data.languages.length, 3) - 1) * rowH;

  // -- footer stats --
  const divY = legendBottom + 16;
  const footY = divY + 26;
  const stat = (xPos: number, n: string, label: string) =>
    `<text x="${xPos}" y="${footY}" font-size="12"><tspan class="txt" ${mono} font-weight="700">${n}</tspan><tspan class="mut" ${sans}> ${escapeXml(label)}</tspan></text>`;
  const footer =
    stat(PAD, String(data.totalActions), t.edits) +
    stat(PAD + 176, String(data.totalCommits), t.commits) +
    stat(PAD + 322, String(data.activeDays), t.activeDays);

  // -- pills: sponsor first (if active), then badges with kind icons --
  const pillTop = footY + 20;
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
      `<text class="mut" x="${pillX + 10 + iconSpace}" y="${y + 14.5}" ${sans} font-size="11">${escapeXml(label)}</text>`;
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
    addPill(b.label, KIND_ICONS[b.kind] ?? KIND_ICONS.badge);
  }
  const pills = pillParts.join("\n  ");
  const pillRowsUsed = pillParts.length > 0 ? pillRow + 1 : 0;

  const H = pillTop + (pillRowsUsed > 0 ? pillRowsUsed * 28 : 0) + 4;

  return `<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="devcard ${escapeXml(data.githubUser)}">
  <style>
    .bg{fill:#ffffff}.brd{stroke:#d8dce4}.txt{fill:#1b1f27}.mut{fill:#6b7280}
    .track{fill:#edeff4}.sep{fill:#ffffff}
    .pill{fill:#f2f4f8;stroke:#d8dce4}.pill-sp{fill:#fff0f3;stroke:#f1b8c4}.heart{fill:#d1355f}
    .link{fill:#0969da}.avbrd{stroke:#d8dce4}
    @media(prefers-color-scheme:dark){
      .bg{fill:#0f1117}.brd{stroke:#262b38}.txt{fill:#e6e9f0}.mut{fill:#8b93a3}
      .track{fill:#1e2230}.sep{fill:#0f1117}
      .pill{fill:#171a24;stroke:#262b38}.pill-sp{fill:#2a1620;stroke:#6e2a3d}.heart{fill:#f47892}
      .link{fill:#58a6ff}.avbrd{stroke:#262b38}
    }
  </style>
  <rect class="bg brd" x="0.5" y="0.5" width="${W - 1}" height="${H - 1}" rx="14" stroke-width="1"/>

  ${avatarSvg}
  <text class="txt" x="${headX}" y="32" ${sans} font-size="15" font-weight="700">devcard</text>
  <text class="mut" x="${headX}" y="48" ${mono} font-size="12">@${escapeXml(data.githubUser)}</text>
  <circle cx="${headX + 66}" cy="27.5" r="4" fill="#3fb950">
    <animate attributeName="opacity" values="1;0.35;1" dur="2.4s" repeatCount="indefinite"/>
  </circle>
  <a href="https://github.com/${escapeXml(data.githubUser)}?tab=repositories" target="_blank">
    <text class="link" x="${W - PAD}" y="36" ${mono} font-size="12" text-anchor="end">${data.repoCount} ${escapeXml(t.repos)} →</text>
  </a>

  <text class="txt" x="${PAD}" y="106" ${mono} font-size="30" font-weight="700">${data.totalLines.toLocaleString("en-US")}<tspan class="mut" ${sans} font-size="12" font-weight="400"> ${escapeXml(t.lines)}</tspan></text>

  <clipPath id="barclip"><rect x="${PAD}" y="${barY}" width="${barW}" height="${barH}" rx="6"/></clipPath>
  <rect class="track" x="${PAD}" y="${barY}" width="${barW}" height="${barH}" rx="6"/>
  <g clip-path="url(#barclip)">
    ${segs.join("\n    ")}
    ${seps.join("\n    ")}
  </g>

  ${legend}

  <line class="brd" x1="${PAD}" y1="${divY}" x2="${W - PAD}" y2="${divY}" stroke-width="1"/>
  ${footer}
  ${pills}
</svg>`;
}

function escapeXml(value: string): string {
  return value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}
