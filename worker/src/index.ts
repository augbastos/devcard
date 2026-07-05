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

// Ingest hardening: strict types, plausibility caps, batch/body limits.
// A single event can't claim more lines than a very large file write, and a
// batch can't exceed what the hook itself sends. Anything invalid is skipped,
// never inserted — gross inflation requires thousands of valid-looking
// requests, which the caps make slow and visible.
const MAX_BATCH = 100;
const MAX_BODY_BYTES = 262144; // 256 KB
const MAX_LINES_PER_EVENT = 20000;
const MAX_REPO_COUNT = 10000;
const EVENT_TYPES = new Set(["edit", "write", "commit"]);

function sanitizeEvent(e: unknown): IngestEvent | null {
  if (typeof e !== "object" || e === null) return null;
  const ev = e as Record<string, unknown>;
  const ts = ev.ts;
  const eventType = ev.event_type;
  if (typeof ts !== "number" || !Number.isFinite(ts) || ts < 1600000000 || ts > 4102444800) return null;
  if (typeof eventType !== "string" || !EVENT_TYPES.has(eventType)) return null;
  const language = ev.language;
  if (language !== null && language !== undefined && (typeof language !== "string" || language.length > 32)) return null;
  const la = ev.lines_added;
  const lr = ev.lines_removed;
  if (typeof la !== "number" || !Number.isInteger(la) || la < 0 || la > MAX_LINES_PER_EVENT) return null;
  if (typeof lr !== "number" || !Number.isInteger(lr) || lr < 0 || lr > MAX_LINES_PER_EVENT) return null;
  const id = ev.id;
  if (id !== undefined && (typeof id !== "number" || !Number.isInteger(id) || id < 0)) return null;
  return {
    id: id as number | undefined,
    ts: Math.floor(ts),
    language: (language as string | null | undefined) ?? null,
    lines_added: la,
    lines_removed: lr,
    event_type: eventType,
  };
}

async function handleIngest(request: Request, env: Env): Promise<Response> {
  const token = request.headers.get("X-Devcard-Token");
  if (!token || token !== env.INGEST_TOKEN) {
    return new Response("unauthorized", { status: 401 });
  }

  const contentLength = Number(request.headers.get("Content-Length") ?? 0);
  if (contentLength > MAX_BODY_BYTES) {
    return new Response("payload too large", { status: 413 });
  }

  let body: { events: unknown; repo_count?: unknown };
  try {
    body = await request.json();
  } catch {
    return new Response("bad json", { status: 400 });
  }

  if (!Array.isArray(body.events)) {
    return new Response("events must be an array", { status: 400 });
  }
  if (body.events.length > MAX_BATCH) {
    return new Response("batch too large", { status: 400 });
  }

  const valid: IngestEvent[] = [];
  let skipped = 0;
  for (const raw of body.events) {
    const ev = sanitizeEvent(raw);
    if (ev) valid.push(ev);
    else skipped += 1;
  }

  const statements = valid.map((e) =>
    env.DB.prepare(
      "INSERT OR IGNORE INTO events (ts, language, lines_added, lines_removed, event_type, client_event_id) VALUES (?, ?, ?, ?, ?, ?)"
    ).bind(e.ts, e.language, e.lines_added, e.lines_removed, e.event_type, e.id ?? null)
  );

  const rc = body.repo_count;
  if (typeof rc === "number" && Number.isInteger(rc) && rc >= 0 && rc <= MAX_REPO_COUNT) {
    statements.push(
      env.DB.prepare("UPDATE stats_snapshot SET repo_count = ?, updated_at = ? WHERE id = 1").bind(
        rc,
        Math.floor(Date.now() / 1000)
      )
    );
  }

  if (statements.length > 0) {
    await env.DB.batch(statements);
  }

  return Response.json({ inserted: valid.length, skipped });
}

interface Strings {
  lines: string;
  activeDays: string;
  edits: string;
  commits: string;
  repos: string;
  since: string;
  events: string;
}

const STRINGS: Record<string, Strings> = {
  en: { lines: "lines of code", activeDays: "active days (30d)", edits: "code edits", commits: "commits", repos: "repos", since: "tracking since", events: "events" },
  pt: { lines: "linhas de código", activeDays: "dias ativos (30d)", edits: "edições de código", commits: "commits", repos: "repos", since: "medindo desde", events: "eventos" },
  es: { lines: "líneas de código", activeDays: "días activos (30d)", edits: "ediciones de código", commits: "commits", repos: "repos", since: "midiendo desde", events: "eventos" },
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

async function fetchStars(user: string, repo: string): Promise<number | null> {
  const url = `https://api.github.com/repos/${user}/${repo}`;
  const cache = caches.default;
  const cacheKey = new Request(url + "#devcard-stars");
  const hit = await cache.match(cacheKey);
  if (hit) {
    const v = await hit.text();
    return v === "" ? null : Number(v);
  }
  let stars: number | null = null;
  try {
    const resp = await fetch(url, { headers: { "User-Agent": "devcard/1.0", "Accept": "application/vnd.github+json" } });
    if (resp.ok) {
      const data = (await resp.json()) as { stargazers_count?: number };
      if (typeof data.stargazers_count === "number") stars = data.stargazers_count;
    }
  } catch {
    stars = null;
  }
  await cache.put(
    cacheKey,
    new Response(stars === null ? "" : String(stars), { headers: { "Cache-Control": "public, max-age=86400" } })
  );
  return stars;
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

  const pinRows = await env.DB.prepare(
    "SELECT repo, note FROM pinned_repos ORDER BY position ASC, id ASC LIMIT 3"
  ).all();

  const firstRow = await env.DB.prepare("SELECT MIN(ts) as first_ts, COUNT(*) as n FROM events").first();

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

  const rawPins = (pinRows.results as { repo: string; note: string | null }[]) ?? [];
  const pins = await Promise.all(
    rawPins.map(async (p) => ({
      repo: p.repo,
      note: p.note,
      stars: await fetchStars(env.GITHUB_USERNAME, p.repo),
    }))
  );

  const provenance = firstRow as { first_ts: number | null; n: number } | null;
  const firstTs = provenance?.first_ts ?? null;
  const totalEvents = provenance?.n ?? 0;

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
    pins,
    firstTs,
    totalEvents,
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
  pins: { repo: string; note: string | null; stars: number | null }[];
  firstTs: number | null;
  totalEvents: number;
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

  // -- pinned repos: up to 3 linked boxes --
  const truncate = (s: string, max: number) => (s.length > max ? s.slice(0, max - 1) + "…" : s);
  let pinnedSvg = "";
  let pinnedBottom = legendBottom;
  if (data.pins.length > 0) {
    const pinTop = legendBottom + 16;
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
          `<path class="mut" d="M0,-5 h7 a2,2 0 0 1 2,2 v8 h-9 a2,2 0 0 0 -2,2 v-10 a2,2 0 0 1 2,-2 Z M-2,7 h11 v3 h-9 a2,2 0 0 1 -2,-2 Z" transform="translate(${(bx + 14).toFixed(1)},${pinTop + 16}) scale(0.9)"/>` +
          `<text class="txt" x="${(bx + 28).toFixed(1)}" y="${pinTop + 18}" ${sans} font-size="12" font-weight="700">${escapeXml(truncate(p.repo, Math.floor(boxW / 7.5)))}</text>` +
          `<text class="mut" x="${(bx + 10).toFixed(1)}" y="${pinTop + 33}" ${sans} font-size="10.5">${escapeXml(sub)}</text>` +
          `</a>`
        );
      })
      .join("\n  ");
    pinnedBottom = pinTop + boxH;
  }

  // -- footer stats --
  const divY = pinnedBottom + 16;
  const footY = divY + 26;
  const stat = (xPos: number, n: string, label: string) =>
    `<text x="${xPos}" y="${footY}" font-size="12"><tspan class="txt" ${mono} font-weight="700">${n}</tspan><tspan class="mut" ${sans}> ${escapeXml(label)}</tspan></text>`;
  const footer =
    stat(PAD, String(data.totalActions), t.edits) +
    stat(PAD + 176, String(data.totalCommits), t.commits) +
    stat(PAD + 322, String(data.activeDays), t.activeDays);

  // -- provenance: honest signal of how long/how much has been measured --
  const sinceDate = data.firstTs
    ? new Date(data.firstTs * 1000).toISOString().slice(0, 10)
    : null;
  const provenanceLine = sinceDate
    ? `<text class="faint" x="${W - PAD}" y="${footY + 18}" ${mono} font-size="9.5" text-anchor="end">${escapeXml(t.since)} ${sinceDate} · ${data.totalEvents.toLocaleString("en-US")} ${escapeXml(t.events)}</text>`
    : "";

  // -- pills: sponsor first (if active), then badges with kind icons --
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
    .bg{fill:#ffffff}.brd{stroke:#d8dce4}.txt{fill:#1b1f27}.mut{fill:#6b7280}.faint{fill:#9aa1ac}
    .track{fill:#edeff4}.sep{fill:#ffffff}
    .pill{fill:#f2f4f8;stroke:#d8dce4}.pill-sp{fill:#fff0f3;stroke:#f1b8c4}.heart{fill:#d1355f}
    .link{fill:#0969da}.avbrd{stroke:#d8dce4}
    @media(prefers-color-scheme:dark){
      .bg{fill:#0f1117}.brd{stroke:#262b38}.txt{fill:#e6e9f0}.mut{fill:#8b93a3}.faint{fill:#5b6270}
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

  ${pinnedSvg}

  <line class="brd" x1="${PAD}" y1="${divY}" x2="${W - PAD}" y2="${divY}" stroke-width="1"/>
  ${footer}
  ${provenanceLine}
  ${pills}
</svg>`;
}

function escapeXml(value: string): string {
  return value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}
