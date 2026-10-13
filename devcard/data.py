"""From the local events table to the numbers the card shows.

Two steps, kept apart because they run on different machines:

1. `aggregate(conn)` folds THIS machine's events into one small dict — the same
   rollups the Worker keeps in D1 (agg_language, agg_event_type, agg_day,
   agg_totals, stats_snapshot). It is what gets published as this machine's
   JSON file, so it is privacy-bound exactly like the old sync payload: built
   from a SQL projection that never selects `project_key`, it can only hold
   language names, counts, day keys and timestamps.
2. `card_data(aggregates, ...)` sums any number of those dicts (one per
   machine) and derives what the renderer draws, mirroring loadCardData() in
   worker/src/queries.ts.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
import math

from .strings import MONTHS

AGGREGATE_FORMAT = 1
HEAT_WEEKS = 16
# Days of `days` worth keeping in an aggregate: the heatmap window plus a
# fortnight, as the Worker's nightly rebuild does (AGG_DAY_KEEP_DAYS).
KEEP_DAYS = HEAT_WEEKS * 7 + 14
NAMED_LANGUAGES = 6
OTHER_LANGUAGE = "\u0000other"


@dataclass
class LanguageSlice:
    language: str
    total: int
    is_other: bool = False
    members: list = field(default_factory=list)


@dataclass
class HeatCell:
    day: str
    lines: int
    level: int


@dataclass
class CardData:
    languages: list
    total_lines: int
    total_bytes: int
    repo_count: int
    badges: list
    pins: list
    total_commits: int
    total_actions: int
    total_diffs: int
    first_ts: object
    total_events: int
    updated_at: int
    heat_weeks: list
    month_marks: list
    streak: int
    avatar: object
    sponsorable: bool
    github_user: str


def day_fn(tz=None):
    """Calendar day (YYYY-MM-DD) of a unix timestamp.

    In the IANA zone `tz` when one is configured, else in this machine's local
    time — which is what a card rendered on the machine that did the work
    should mean by "today".
    """
    if tz:
        from zoneinfo import ZoneInfo

        zone = ZoneInfo(tz)
        return lambda ts: datetime.fromtimestamp(ts, zone).date().isoformat()
    return lambda ts: datetime.fromtimestamp(ts).date().isoformat()


def aggregate(conn, now, tz=None, repo_count=0):
    """This machine's rollups, from the hook's local SQLite.

    Every query names its columns; none can return `project_key`. The day
    buckets use the Worker's rebuild trick: group by 15-minute UTC buckets in
    SQL (every real UTC offset is a multiple of 15 minutes) and map buckets to
    local days here, so the rows read track hours of work, not events.
    """
    to_day = day_fn(tz)
    languages = {
        language: int(lines)
        for language, lines in conn.execute(
            "SELECT language, SUM(lines_added) FROM events"
            " WHERE language IS NOT NULL AND language != '' GROUP BY language"
        )
    }
    event_types = {
        kind: int(n)
        for kind, n in conn.execute("SELECT event_type, COUNT(*) FROM events GROUP BY event_type")
    }
    days = {}
    for bucket, lines in conn.execute(
        "SELECT (ts / 900) * 900 AS bucket, SUM(lines_added) FROM events WHERE ts >= ? GROUP BY bucket",
        (int(now) - KEEP_DAYS * 86400,),
    ):
        day = to_day(bucket)
        days[day] = days.get(day, 0) + int(lines)
    total_bytes, events, first_ts = conn.execute(
        "SELECT COALESCE(SUM(bytes_added), 0), COUNT(*), MIN(ts) FROM events"
    ).fetchone()
    return {
        "format": AGGREGATE_FORMAT,
        "languages": dict(sorted(languages.items())),
        "event_types": dict(sorted(event_types.items())),
        "days": dict(sorted(days.items())),
        "bytes": int(total_bytes),
        "events": int(events),
        "first_ts": None if first_ts is None else int(first_ts),
        "repo_count": int(repo_count),
        "updated_at": int(now),
    }


def _int(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def merge(aggregates):
    """Sum per-machine aggregates into one.

    Counts add up. `repo_count` does not: every machine reads the same GitHub
    account's total, so adding them would multiply it — the largest wins.
    `first_ts` is the earliest, `updated_at` the latest. A value of the wrong
    shape is skipped rather than trusted, since these files come back from a
    repository anyone with push access could edit.
    """
    out = {"languages": {}, "event_types": {}, "days": {}, "bytes": 0, "events": 0,
           "first_ts": None, "repo_count": 0, "updated_at": 0}
    for agg in aggregates:
        if not isinstance(agg, dict) or agg.get("format") != AGGREGATE_FORMAT:
            continue
        for key in ("languages", "event_types", "days"):
            table = agg.get(key)
            if not isinstance(table, dict):
                continue
            for name, value in table.items():
                if isinstance(name, str) and len(name) <= 32:
                    out[key][name] = out[key].get(name, 0) + _int(value)
        out["bytes"] += _int(agg.get("bytes"))
        out["events"] += _int(agg.get("events"))
        first = agg.get("first_ts")
        if _int(first) and (out["first_ts"] is None or first < out["first_ts"]):
            out["first_ts"] = first
        out["repo_count"] = max(out["repo_count"], _int(agg.get("repo_count")))
        out["updated_at"] = max(out["updated_at"], _int(agg.get("updated_at")))
    return out


def with_other_bucket(languages, max_named=NAMED_LANGUAGES):
    """Collapse everything past `max_named` into one slice (legend only)."""
    if len(languages) <= max_named + 1:
        return languages
    head, tail = languages[:max_named], languages[max_named:]
    total = sum(s.total for s in tail)
    if total <= 0:
        return head
    return [*head, LanguageSlice(OTHER_LANGUAGE, total, True, [s.language for s in tail])]


def _shift(day, delta):
    return (date.fromisoformat(day) + timedelta(days=delta)).isoformat()


def _percentile(sorted_asc, p):
    if not sorted_asc:
        return 0
    return sorted_asc[min(len(sorted_asc) - 1, math.floor(p * (len(sorted_asc) - 1)))]


def build_heatmap(day_lines, today, locale):
    """The 16-week grid ending on the week containing `today`, and the streak."""
    today_idx = date.fromisoformat(today).weekday()  # Monday = 0
    grid_end = _shift(today, 6 - today_idx)
    grid_start = _shift(grid_end, -(HEAT_WEEKS * 7 - 1))

    active = sorted(v for v in day_lines.values() if v > 0)
    p90 = max(1, _percentile(active, 0.9))
    months = MONTHS.get(locale, MONTHS["en"])

    weeks, marks, last_month = [], [], ""
    for w in range(HEAT_WEEKS):
        week = []
        for d in range(7):
            day = _shift(grid_start, w * 7 + d)
            lines = 0 if day > today else day_lines.get(day, 0)
            level = 0 if lines <= 0 else max(1, min(4, math.ceil((lines / p90) * 4)))
            week.append(HeatCell(day, lines, level))
        first_day = week[0].day
        month = first_day[:7]
        if month != last_month:
            # Two labels a week apart overlap ("MayJun"); three weeks stays legible.
            if not marks or w - marks[-1][0] >= 3:
                marks.append((w, months[int(first_day[5:7]) - 1]))
            last_month = month
        weeks.append(week)

    streak = 0
    cursor = today if today in day_lines else _shift(today, -1)
    while cursor in day_lines:
        streak += 1
        cursor = _shift(cursor, -1)
    return weeks, marks, streak


def card_data(merged, github_user, now, locale="en", tz=None, avatar=None, badges=(), pins=(),
              sponsorable=False):
    """What the renderer draws, from merged aggregates. Mirrors loadCardData()."""
    to_day = day_fn(tz)
    rows = sorted(
        ((name, lines) for name, lines in merged["languages"].items() if lines > 0),
        key=lambda item: (-item[1], item[0]),
    )
    languages = [LanguageSlice(name, lines) for name, lines in rows]
    counts = merged["event_types"]
    heat_cutoff = to_day(int(now) - (HEAT_WEEKS * 7 + 2) * 86400)
    day_lines = {day: lines for day, lines in merged["days"].items() if day >= heat_cutoff}
    weeks, marks, streak = build_heatmap(day_lines, to_day(int(now)), locale)
    return CardData(
        languages=languages,
        total_lines=sum(s.total for s in languages),
        total_bytes=merged["bytes"],
        repo_count=merged["repo_count"],
        badges=[dict(b) for b in badges][:8],
        pins=[dict(p) for p in pins][:3],
        total_commits=counts.get("commit", 0),
        total_actions=counts.get("edit", 0) + counts.get("write", 0),
        total_diffs=counts.get("diff", 0),
        first_ts=merged["first_ts"],
        total_events=merged["events"],
        updated_at=merged["updated_at"],
        heat_weeks=weeks,
        month_marks=marks,
        streak=streak,
        avatar=avatar,
        sponsorable=sponsorable,
        github_user=github_user,
    )
