import { loadCardData, makeDayFn } from "./queries";
import { STRINGS, cacheKeyFor, langName, layoutName } from "./variants";
import { pickTheme, themeName } from "./themes";
import { renderFull, Strings } from "./render";
import { renderBanner, renderHalf, renderVertical } from "./render-layouts";
import { renderWide } from "./render-wide";

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
  /** Namespace this event was queued under, when it differs from the batch's.
   *  A hook that upgraded across the source_id change carries a backlog that
   *  was queued as `legacy`; re-sending it under the new installation id would
   *  make the Worker see a different event and store it twice. */
  source_id?: string;
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
    if (request.method === "POST" && url.pathname === "/ingest") {
      return handleIngest(request, env);
    }
    // Image proxies and link checkers probe with HEAD before they fetch; a 404
    // there makes an embed look dead even though the card renders fine. Answer
    // with the real headers and no body. The Cache API only accepts GET, so the
    // lookup runs against an equivalent GET request.
    const isHead = request.method === "HEAD";
    if ((request.method === "GET" || isHead) && url.pathname === "/svg") {
      const getRequest = isHead
        ? new Request(request.url, { method: "GET", headers: request.headers })
        : request;
      const response = await handleSvgCached(getRequest, env, ctx);
      return isHead ? new Response(null, { status: response.status, headers: response.headers }) : response;
    }
    return new Response("not found", { status: 404 });
  },

  async scheduled(_event: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    ctx.waitUntil(rebuildRollups(env));
  },
};

// How much of `agg_day` is worth keeping: the heatmap window the card draws,
// plus a fortnight so a timezone or window change has something to fall back
// on. Everything older is deleted on each rebuild, which is what keeps the
// table flat instead of growing a row a day forever.
const AGG_DAY_KEEP_DAYS = 16 * 7 + 14;

// Recompute every rollup from `events`. Ingest maintains them incrementally,
// which is fast but drifts: a deploy landing between a write and the code that
// feeds it, a manual INSERT, a bug. Running this nightly means drift can never
// outlive a day. It costs one pass over the table — a fraction of a percent of
// the daily read allowance, versus the ~75k rows a single un-rolled-up card
// render used to cost.
//
// An ingest landing between the reads and the writes below can be lost from the
// aggregate; that is the same race the incremental path already has, and the
// next night's run corrects it. That is the point of running it on a schedule
// rather than reaching for a lock.
async function rebuildRollups(env: Env): Promise<void> {
  const dayFn = makeDayFn(env.TIMEZONE || "UTC");
  const keepFrom = Math.floor(Date.now() / 1000) - AGG_DAY_KEEP_DAYS * 86400;

  // Local calendar days cannot be computed in SQL — SQLite has no timezone
  // database — but sending back one row per event would grow without bound.
  // 15-minute buckets are the compromise: every real UTC offset is a multiple
  // of 15 minutes, so bucketing this way never splits a local day in the wrong
  // place, and the row count tracks hours spent coding rather than events.
  const buckets = await env.DB.prepare(
    "SELECT (ts / 900) * 900 AS bucket, SUM(lines_added) AS lines FROM events" +
      " WHERE ts >= ? GROUP BY bucket"
  )
    .bind(keepFrom)
    .all();

  const byDay = new Map<string, number>();
  for (const row of (buckets.results as { bucket: number; lines: number }[]) ?? []) {
    const day = dayFn(row.bucket);
    byDay.set(day, (byDay.get(day) ?? 0) + row.lines);
  }

  // D1 runs a batch as one transaction, so the card never observes a rollup
  // that has been emptied but not yet refilled.
  const statements: D1PreparedStatement[] = [
    env.DB.prepare("DELETE FROM agg_language"),
    env.DB.prepare(
      "INSERT INTO agg_language (language, lines) SELECT language, SUM(lines_added)" +
        " FROM events WHERE language IS NOT NULL GROUP BY language"
    ),
    env.DB.prepare("DELETE FROM agg_event_type"),
    env.DB.prepare(
      "INSERT INTO agg_event_type (event_type, n) SELECT event_type, COUNT(*)" +
        " FROM events GROUP BY event_type"
    ),
    env.DB.prepare("DELETE FROM agg_day"),
    ...[...byDay].map(([day, lines]) =>
      env.DB.prepare("INSERT INTO agg_day (day, lines) VALUES (?, ?)").bind(day, lines)
    ),
    env.DB.prepare(
      "UPDATE agg_totals SET bytes = (SELECT COALESCE(SUM(bytes_added), 0) FROM events)," +
        " events = (SELECT COUNT(*) FROM events), first_ts = (SELECT MIN(ts) FROM events)" +
        " WHERE id = 1"
    ),
  ];
  await env.DB.batch(statements);
}

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

// `edit`/`write` come from the Claude Code hook and count one agent tool call
// each. `diff` comes from the git hook and is a per-commit, per-language
// aggregate — a different unit entirely, which is why it is not called `edit`.
// See "Counting rules" in the README.
const EVENT_TYPES = new Set(["edit", "write", "commit", "diff"]);

// Opaque, random, per-install. Deliberately narrow: it is written straight into
// a column that participates in the idempotency key, and there is no reason for
// it to hold anything but the hex token the hook generates.
const SOURCE_ID_RE = /^[A-Za-z0-9_-]{4,64}$/;
// What a row gets when the request carried no source_id: pre-migration rows and
// hooks that predate the field. Keeping them in one namespace preserves their
// original dedupe behaviour exactly.
const LEGACY_SOURCE_ID = "legacy";

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
  // A malformed per-event namespace is skipped, never quietly relabelled onto
  // the batch default: relabelling would move the event into a namespace where
  // its rowid means something else.
  const source = ev.source_id;
  if (source !== undefined && source !== null && (typeof source !== "string" || !SOURCE_ID_RE.test(source))) {
    return null;
  }
  return {
    id: id as number | undefined,
    ts: Math.floor(ts),
    language: (language as string | null | undefined) ?? null,
    lines_added: la,
    lines_removed: lr,
    bytes_added: ba,
    event_type: eventType,
    source_id: (source as string | undefined) ?? undefined,
  };
}

// Constant-time string compare — avoids leaking the ingest token via
// response-timing differences on a byte-by-byte mismatch (CWE-208).
function timingSafeEqual(a: string, b: string): boolean {
  const enc = new TextEncoder();
  const aBytes = enc.encode(a);
  const bBytes = enc.encode(b);
  const len = Math.max(aBytes.length, bBytes.length);
  let diff = aBytes.length ^ bBytes.length;
  for (let i = 0; i < len; i++) {
    diff |= (aBytes[i] ?? 0) ^ (bBytes[i] ?? 0);
  }
  return diff === 0;
}

// Reads the request body up to `limit` bytes without buffering past it —
// an attacker can omit or lie about Content-Length, so this is the
// authoritative cap (the header check above is just a cheap fast-path).
async function readBodyWithLimit(
  request: Request,
  limit: number
): Promise<{ ok: true; text: string } | { ok: false }> {
  if (!request.body) return { ok: true, text: "" };
  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    if (value) {
      total += value.byteLength;
      if (total > limit) {
        await reader.cancel();
        return { ok: false };
      }
      chunks.push(value);
    }
  }
  const buf = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    buf.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return { ok: true, text: new TextDecoder().decode(buf) };
}

async function handleIngest(request: Request, env: Env): Promise<Response> {
  const token = request.headers.get("X-Devcard-Token");
  if (!token || !timingSafeEqual(token, env.INGEST_TOKEN)) {
    return new Response("unauthorized", { status: 401 });
  }

  const contentLength = Number(request.headers.get("Content-Length") ?? 0);
  if (contentLength > MAX_BODY_BYTES) {
    return new Response("payload too large", { status: 413 });
  }

  const read = await readBodyWithLimit(request, MAX_BODY_BYTES);
  if (!read.ok) {
    return new Response("payload too large", { status: 413 });
  }

  let body: { events: unknown; repo_count?: unknown; source_id?: unknown };
  try {
    body = JSON.parse(read.text);
  } catch {
    return new Response("bad json", { status: 400 });
  }

  if (!Array.isArray(body.events)) {
    return new Response("events must be an array", { status: 400 });
  }
  if (body.events.length > MAX_BATCH) {
    return new Response("batch too large", { status: 400 });
  }

  // The batch-level namespace is a DEFAULT, not the identity: an event may
  // carry its own (see IngestEvent.source_id). Absent is fine — that is an
  // older hook, and its events belong in the legacy namespace, which is exactly
  // where they were already stored. Malformed is rejected rather than coerced,
  // because coercing garbage onto `legacy` would let a broken client's rowids
  // collide with real history.
  const rawSource = body.source_id;
  if (rawSource !== undefined && rawSource !== null && typeof rawSource !== "string") {
    return new Response("bad source_id", { status: 400 });
  }
  if (typeof rawSource === "string" && !SOURCE_ID_RE.test(rawSource)) {
    return new Response("bad source_id", { status: 400 });
  }
  const defaultSourceId = typeof rawSource === "string" ? rawSource : LEGACY_SOURCE_ID;

  const valid: IngestEvent[] = [];
  let skipped = 0;
  for (const raw of body.events) {
    const ev = sanitizeEvent(raw);
    if (ev) valid.push(ev);
    else skipped += 1;
  }

  // RETURNING is what makes the rollups below safe: an INSERT OR IGNORE that
  // hits the (source_id, client_event_id) unique index returns no row, so a
  // hook that re-sends a batch cannot double-count itself into the aggregates.
  const statements = valid.map((e) =>
    env.DB.prepare(
      "INSERT OR IGNORE INTO events (ts, language, lines_added, lines_removed, bytes_added, event_type, client_event_id, source_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?) RETURNING id"
    ).bind(
      e.ts,
      e.language,
      e.lines_added,
      e.lines_removed,
      e.bytes_added ?? 0,
      e.event_type,
      e.id ?? null,
      e.source_id ?? defaultSourceId
    )
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

  let landed: IngestEvent[] = [];
  if (statements.length > 0) {
    const results = await env.DB.batch(statements);
    landed = valid.filter((_, i) => ((results[i]?.results as unknown[] | undefined)?.length ?? 0) > 0);
    const rollup = rollupStatements(env, landed);
    if (rollup.length > 0) await env.DB.batch(rollup);
  }

  return Response.json({ inserted: landed.length, skipped, duplicates: valid.length - landed.length });
}

// Fold the events that actually landed into the rollup tables the card reads.
// Written as one batch of UPSERTs keyed by language/type/day, so a 100-event
// batch costs a handful of writes rather than one per event.
function rollupStatements(env: Env, landed: IngestEvent[]): D1PreparedStatement[] {
  if (landed.length === 0) return [];
  const dayFn = makeDayFn(env.TIMEZONE || "UTC");

  const byLanguage = new Map<string, number>();
  const byType = new Map<string, number>();
  const byDay = new Map<string, number>();
  let bytes = 0;
  let firstTs = Infinity;

  for (const e of landed) {
    if (e.language) byLanguage.set(e.language, (byLanguage.get(e.language) ?? 0) + e.lines_added);
    byType.set(e.event_type, (byType.get(e.event_type) ?? 0) + 1);
    const day = dayFn(e.ts);
    byDay.set(day, (byDay.get(day) ?? 0) + e.lines_added);
    bytes += e.bytes_added ?? 0;
    if (e.ts < firstTs) firstTs = e.ts;
  }

  const out: D1PreparedStatement[] = [];
  for (const [language, lines] of byLanguage) {
    out.push(
      env.DB.prepare(
        "INSERT INTO agg_language (language, lines) VALUES (?, ?)" +
          " ON CONFLICT(language) DO UPDATE SET lines = lines + excluded.lines"
      ).bind(language, lines)
    );
  }
  for (const [eventType, n] of byType) {
    out.push(
      env.DB.prepare(
        "INSERT INTO agg_event_type (event_type, n) VALUES (?, ?)" +
          " ON CONFLICT(event_type) DO UPDATE SET n = n + excluded.n"
      ).bind(eventType, n)
    );
  }
  for (const [day, lines] of byDay) {
    out.push(
      env.DB.prepare(
        "INSERT INTO agg_day (day, lines) VALUES (?, ?)" +
          " ON CONFLICT(day) DO UPDATE SET lines = lines + excluded.lines"
      ).bind(day, lines)
    );
  }
  // A late-arriving backfill can carry a timestamp older than anything seen so
  // far, so first_ts only ever moves backwards.
  out.push(
    env.DB.prepare(
      "UPDATE agg_totals SET bytes = bytes + ?, events = events + ?," +
        " first_ts = CASE WHEN first_ts IS NULL OR first_ts > ? THEN ? ELSE first_ts END" +
        " WHERE id = 1"
    ).bind(bytes, landed.length, firstTs, firstTs)
  );
  return out;
}

async function handleSvg(env: Env, lang: string, theme: string, layout: string): Promise<Response> {
  const t = STRINGS[lang];
  const tokens = pickTheme(theme);
  const data = await loadCardData(env, t.locale);

  let svg: string;
  if (layout === "wide") svg = renderWide(data, tokens, t);
  else if (layout === "banner") svg = renderBanner(data, tokens, t);
  else if (layout === "half") svg = renderHalf(data, tokens, t);
  else if (layout === "vertical") svg = renderVertical(data, tokens, t);
  else svg = renderFull(data, tokens, t);

  return new Response(svg, {
    headers: {
      "Content-Type": "image/svg+xml; charset=utf-8",
      "Cache-Control": "public, max-age=300, s-maxage=300",
      // For caches downstream of this Worker (the browser, GitHub's image
      // proxy, corporate proxies): the body genuinely depends on the header.
      // This Worker's own cache does NOT rely on it — see cacheKeyFor.
      "Vary": "Accept-Language",
    },
  });
}

// s-maxage was 30s, which had every embed revalidating ~2,880 times a day per
// variant — GitHub's image proxy honours it, so a README that nobody reloads
// still generated constant traffic. Five minutes is still live for a card whose
// underlying hook writes in seconds.
async function handleSvgCached(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
  const url = new URL(request.url);
  const requestedUser = url.searchParams.get("user");
  if (requestedUser && requestedUser !== env.GITHUB_USERNAME) {
    return new Response("unknown user", { status: 404 });
  }

  const lang = langName(request, url);
  const theme = themeName(url.searchParams.get("theme"));
  const layout = layoutName(url.searchParams.get("layout"));

  const cache = await caches.open("default");
  const cacheKey = cacheKeyFor(url, lang, theme, layout);
  const cached = await cache.match(cacheKey);
  if (cached) return cached;

  const response = await handleSvg(env, lang, theme, layout);
  if (response.ok) {
    ctx.waitUntil(cache.put(cacheKey, response.clone()));
  }
  return response;
}
