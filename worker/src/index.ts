import { loadCardData } from "./queries";
import { pickTheme } from "./themes";
import { renderFull, Strings } from "./render";
import { renderBanner, renderHalf, renderVertical } from "./render-layouts";

export interface Env {
  DB: D1Database;
  INGEST_TOKEN: string;
  GITHUB_USERNAME: string;
  TIMEZONE?: string;
}

interface IngestEvent {
  id?: number;
  ts: number;
  language: string | null;
  lines_added: number;
  lines_removed: number;
  bytes_added?: number;
  event_type: string;
}

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
const MAX_BYTES_PER_EVENT = 10485760; // 10 MB — far beyond any plausible single edit
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
  const ba = ev.bytes_added ?? 0;
  if (typeof ba !== "number" || !Number.isInteger(ba) || ba < 0 || ba > MAX_BYTES_PER_EVENT) return null;
  return {
    id: id as number | undefined,
    ts: Math.floor(ts),
    language: (language as string | null | undefined) ?? null,
    lines_added: la,
    lines_removed: lr,
    bytes_added: ba,
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
      "INSERT OR IGNORE INTO events (ts, language, lines_added, lines_removed, bytes_added, event_type, client_event_id) VALUES (?, ?, ?, ?, ?, ?, ?)"
    ).bind(e.ts, e.language, e.lines_added, e.lines_removed, e.bytes_added ?? 0, e.event_type, e.id ?? null)
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

const STRINGS: Record<string, Strings> = {
  en: {
    lines: "lines of code",
    edits: "code edits",
    commits: "commits",
    repos: "repos",
    since: "tracking since",
    events: "events",
    dayStreak: "day streak",
    streakAbbr: "d",
    updatedAgo: "updated {X} ago",
    dec: ".",
    locale: "en",
  },
  pt: {
    lines: "linhas de código",
    edits: "edições de código",
    commits: "commits",
    repos: "repos",
    since: "medindo desde",
    events: "eventos",
    dayStreak: "dias seguidos",
    streakAbbr: "d",
    updatedAgo: "atualizado há {X}",
    dec: ",",
    locale: "pt",
  },
  es: {
    lines: "líneas de código",
    edits: "ediciones de código",
    commits: "commits",
    repos: "repos",
    since: "midiendo desde",
    events: "eventos",
    dayStreak: "días seguidos",
    streakAbbr: "d",
    updatedAgo: "actualizado hace {X}",
    dec: ",",
    locale: "es",
  },
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

const LAYOUTS = new Set(["full", "banner", "half", "vertical"]);

async function handleSvg(request: Request, env: Env): Promise<Response> {
  const url = new URL(request.url);
  const requestedUser = url.searchParams.get("user");
  if (requestedUser && requestedUser !== env.GITHUB_USERNAME) {
    return new Response("unknown user", { status: 404 });
  }
  const t = pickLang(request, url);
  const theme = pickTheme(url.searchParams.get("theme"));
  const layoutParam = url.searchParams.get("layout") ?? "full";
  const layout = LAYOUTS.has(layoutParam) ? layoutParam : "full";

  const data = await loadCardData(env, t.locale);

  let svg: string;
  if (layout === "banner") svg = renderBanner(data, theme, t);
  else if (layout === "half") svg = renderHalf(data, theme, t);
  else if (layout === "vertical") svg = renderVertical(data, theme, t);
  else svg = renderFull(data, theme, t);

  return new Response(svg, {
    headers: {
      "Content-Type": "image/svg+xml; charset=utf-8",
      "Cache-Control": "public, max-age=60",
      "Vary": "Accept-Language",
    },
  });
}
