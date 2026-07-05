// All D1 + external reads for the card, gathered into one CardData object.
// Every SQL projection here is privacy-bound: only anonymized aggregate
// columns (language, line/byte counts, event type, timestamps) are ever
// selected — never project identifiers, which don't even exist in this schema.

export interface HeatCell {
  day: string; // YYYY-MM-DD in the owner's timezone
  lines: number;
  level: number; // 0..4
}

export interface CardData {
  languages: { language: string; total: number }[];
  totalLines: number;
  totalBytes: number;
  repoCount: number;
  badges: { kind: string; label: string }[];
  pins: { repo: string; note: string | null; stars: number | null }[];
  totalCommits: number;
  totalActions: number;
  firstTs: number | null;
  totalEvents: number;
  updatedAt: number;
  heatWeeks: HeatCell[][]; // [week][weekday 0=Mon..6=Sun], oldest week first
  monthMarks: { weekIndex: number; label: string }[];
  streak: number;
  avatar: string | null;
  sponsorable: boolean;
  githubUser: string;
}

interface DBEnv {
  DB: D1Database;
  GITHUB_USERNAME: string;
  TIMEZONE?: string;
}

const HEAT_WEEKS = 16;

// Local calendar day (YYYY-MM-DD) for a unix timestamp in the owner's tz.
// Intl handles DST correctly, which a fixed SQL offset would not.
function makeDayFn(tz: string): (tsSec: number) => string {
  const fmt = new Intl.DateTimeFormat("en-CA", {
    timeZone: tz,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
  return (tsSec: number) => fmt.format(new Date(tsSec * 1000));
}

function shiftDay(day: string, deltaDays: number): string {
  const d = new Date(day + "T12:00:00Z"); // noon avoids UTC day-boundary drift
  d.setUTCDate(d.getUTCDate() + deltaDays);
  return d.toISOString().slice(0, 10);
}

// Monday=0 .. Sunday=6 for a YYYY-MM-DD.
function weekdayIndex(day: string): number {
  const dow = new Date(day + "T12:00:00Z").getUTCDay(); // Sun=0
  return (dow + 6) % 7;
}

function percentile(sortedAsc: number[], p: number): number {
  if (sortedAsc.length === 0) return 0;
  const idx = Math.min(sortedAsc.length - 1, Math.floor(p * (sortedAsc.length - 1)));
  return sortedAsc[idx];
}

export function buildHeatmap(
  dayLines: Map<string, number>,
  today: string,
  monthLocale: string
): { weeks: HeatCell[][]; monthMarks: { weekIndex: number; label: string }[]; streak: number } {
  // Grid ends on the week containing today; cells after today render as level 0.
  const todayIdx = weekdayIndex(today);
  const gridEnd = shiftDay(today, 6 - todayIdx); // Sunday of the current week
  const gridStart = shiftDay(gridEnd, -(HEAT_WEEKS * 7 - 1));

  const active = [...dayLines.values()].filter((v) => v > 0).sort((a, b) => a - b);
  const p90 = Math.max(1, percentile(active, 0.9));

  const weeks: HeatCell[][] = [];
  const monthMarks: { weekIndex: number; label: string }[] = [];
  const monthFmt = new Intl.DateTimeFormat(monthLocale, { month: "short" });
  let lastMonth = "";

  for (let w = 0; w < HEAT_WEEKS; w++) {
    const week: HeatCell[] = [];
    for (let d = 0; d < 7; d++) {
      const day = shiftDay(gridStart, w * 7 + d);
      const lines = day > today ? 0 : dayLines.get(day) ?? 0;
      const level = lines <= 0 ? 0 : Math.max(1, Math.min(4, Math.ceil((lines / p90) * 4)));
      week.push({ day, lines, level });
    }
    const firstDay = week[0].day;
    const month = firstDay.slice(0, 7);
    if (month !== lastMonth) {
      monthMarks.push({ weekIndex: w, label: monthFmt.format(new Date(firstDay + "T12:00:00Z")) });
      lastMonth = month;
    }
    weeks.push(week);
  }

  // Streak: consecutive active days ending today or yesterday (yesterday keeps
  // the streak alive before the day's first edit).
  let streak = 0;
  let cursor = today;
  if (!dayLines.has(today)) {
    cursor = shiftDay(today, -1);
  }
  while (dayLines.has(cursor)) {
    streak += 1;
    cursor = shiftDay(cursor, -1);
  }

  return { weeks, monthMarks, streak };
}

async function fetchAvatarDataUri(user: string): Promise<string | null> {
  const url = `https://github.com/${user}.png?size=96`;
  const cache = (caches as unknown as { default: Cache }).default;
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
  const cache = (caches as unknown as { default: Cache }).default;
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
  const cache = (caches as unknown as { default: Cache }).default;
  const cacheKey = new Request(url + "#devcard-stars");
  const hit = await cache.match(cacheKey);
  if (hit) {
    const v = await hit.text();
    return v === "" ? null : Number(v);
  }
  let stars: number | null = null;
  try {
    const resp = await fetch(url, {
      headers: { "User-Agent": "devcard/1.0", Accept: "application/vnd.github+json" },
    });
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

export async function loadCardData(env: DBEnv, monthLocale: string): Promise<CardData> {
  const tz = env.TIMEZONE || "UTC";
  const dayFn = makeDayFn(tz);
  const nowSec = Math.floor(Date.now() / 1000);
  const heatCutoff = nowSec - (HEAT_WEEKS * 7 + 2) * 86400;

  const [avatar, sponsorable, langRows, bytesRow, eventTypeRows, snapshot, profileRows, pinRows, firstRow, heatRows] =
    await Promise.all([
      fetchAvatarDataUri(env.GITHUB_USERNAME),
      hasSponsors(env.GITHUB_USERNAME),
      env.DB.prepare(
        "SELECT language, SUM(lines_added) as total FROM events WHERE language IS NOT NULL GROUP BY language ORDER BY total DESC"
      ).all(),
      env.DB.prepare("SELECT SUM(bytes_added) as b FROM events").first(),
      env.DB.prepare("SELECT event_type, COUNT(*) as n FROM events GROUP BY event_type").all(),
      env.DB.prepare("SELECT repo_count, updated_at FROM stats_snapshot WHERE id = 1").first(),
      env.DB.prepare("SELECT kind, label FROM profile_entries ORDER BY created_at DESC LIMIT 8").all(),
      env.DB.prepare("SELECT repo, note FROM pinned_repos ORDER BY position ASC, id ASC LIMIT 3").all(),
      env.DB.prepare("SELECT MIN(ts) as first_ts, COUNT(*) as n FROM events").first(),
      env.DB.prepare("SELECT ts, lines_added FROM events WHERE ts >= ?").bind(heatCutoff).all(),
    ]);

  const languages = (langRows.results as { language: string; total: number }[]) ?? [];
  const totalLines = languages.reduce((sum, l) => sum + l.total, 0);
  const snap = snapshot as { repo_count: number; updated_at: number } | null;
  const badges = (profileRows.results as { kind: string; label: string }[]) ?? [];

  const eventCounts = (eventTypeRows.results as { event_type: string; n: number }[]) ?? [];
  const totalCommits = eventCounts.find((r) => r.event_type === "commit")?.n ?? 0;
  const totalActions = eventCounts
    .filter((r) => r.event_type === "edit" || r.event_type === "write")
    .reduce((sum, r) => sum + r.n, 0);

  const dayLines = new Map<string, number>();
  for (const row of (heatRows.results as { ts: number; lines_added: number }[]) ?? []) {
    const day = dayFn(row.ts);
    dayLines.set(day, (dayLines.get(day) ?? 0) + row.lines_added);
  }
  const today = dayFn(nowSec);
  const { weeks, monthMarks, streak } = buildHeatmap(dayLines, today, monthLocale);

  const rawPins = (pinRows.results as { repo: string; note: string | null }[]) ?? [];
  const pins = await Promise.all(
    rawPins.map(async (p) => ({
      repo: p.repo,
      note: p.note,
      stars: await fetchStars(env.GITHUB_USERNAME, p.repo),
    }))
  );

  const provenance = firstRow as { first_ts: number | null; n: number } | null;

  return {
    languages,
    totalLines,
    totalBytes: (bytesRow as { b: number | null } | null)?.b ?? 0,
    repoCount: snap?.repo_count ?? 0,
    badges,
    pins,
    totalCommits,
    totalActions,
    firstTs: provenance?.first_ts ?? null,
    totalEvents: provenance?.n ?? 0,
    updatedAt: snap?.updated_at ?? 0,
    heatWeeks: weeks,
    monthMarks,
    streak,
    avatar,
    sponsorable,
    githubUser: env.GITHUB_USERNAME,
  };
}
