"""From the local events table to the numbers the card shows.

Two steps, kept apart because they run on different machines:

1. `aggregate(conn)` folds THIS machine's events into one small dict — the same
   rollups the Worker keeps in D1 (agg_language, agg_event_type, agg_day,
   agg_totals, stats_snapshot). It is what gets published as this machine's
   JSON file, so it is privacy-bound exactly like the old sync payload: built
   from SQL projections and the activity/usage export allowlists. It holds
   language names, fixed agent/model-family labels, counts, day keys,
   activity and cost estimates, and aggregate timestamps, never `project_key`.
2. `card_data(aggregates, ...)` sums any number of those dicts (one per
   machine) and derives what the renderer draws, mirroring loadCardData() in
   worker/src/queries.ts.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, localcontext
import json
import math
import re
import time
import warnings

from .strings import MONTHS
from ._hook import activity, usage as usage_hook
from .usage import public_rows
from . import config

AGGREGATE_FORMAT = 1
MIN_TIMESTAMP = 1577836800  # 2020-01-01 UTC
LANGUAGE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _+#.()\-]{0,31}\Z")
HEAT_WEEKS = 16
# Days of `days` worth keeping in an aggregate: the heatmap window plus a
# fortnight, as the Worker's nightly rebuild does (AGG_DAY_KEEP_DAYS).
KEEP_DAYS = HEAT_WEEKS * 7 + 14
NAMED_LANGUAGES = 6
OTHER_LANGUAGE = "\u0000other"
AGENTS = activity.AGENTS
AGENT_FIELDS = ("lines_added", "lines_removed", "bytes_added", "events", "commits", "code_edits")
CATEGORY_FIELDS = {
    "languages": ("languages", "language_percentages"),
    "activity": ("days", "updated_at"),
    "totals": ("lines", "bytes", "events", "first_ts", "event_types"),
    "repo_count": ("repo_count", "repo_count_private"),
    "agents": ("agents", "active_minutes"),
    "usage": ("usage",),
}
CORE_CATEGORIES = {key: True for key in ("languages", "activity", "totals", "repo_count")}


def consented(agg, consent=None):
    """The publication boundary: a positive allowlist, never a raw-row redaction."""
    allowed = config.consents({"consent": consent})
    out = {"format": agg.get("format")}
    for category, fields in CATEGORY_FIELDS.items():
        if allowed[category]:
            out.update({key: agg[key] for key in fields if key in agg})
    if "languages" in out and not allowed["totals"]:
        total = sum(out["languages"].values())
        out["language_percentages"] = {
            name: round(value / total * 100, 1) if total else 0 for name, value in out.pop("languages").items()
        }
    if "repo_count" in out and not allowed["repo_count_private"] and agg.get("repo_count_private") is not False:
        # Old machine files counted private repos without recording provenance.
        out.pop("repo_count", None)
        out.pop("repo_count_private", None)
    return out


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
    agent_totals: dict = field(default_factory=dict)
    usage: list = field(default_factory=list)
    show_agents: bool = False
    show_usage: bool = False
    active_minutes: object = None
    sections: frozenset = field(default_factory=lambda: frozenset(CORE_CATEGORIES))
    language_total: float = 0
    model_tokens: dict = field(default_factory=dict)
    longest_streak: int = 0
    show_models: bool = False
    polyglot_eligible_languages: frozenset | None = None


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


def aggregate(conn, now, tz=None, repo_count=0, consent=None, repo_count_private=False):
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
    total_bytes, events, first_ts, lines = conn.execute(
        "SELECT COALESCE(SUM(bytes_added), 0), COUNT(*), MIN(ts), COALESCE(SUM(lines_added), 0) FROM events"
    ).fetchone()
    allowed = config.consents({"consent": consent})
    agg = {
        "format": AGGREGATE_FORMAT,
        "languages": dict(sorted(languages.items())),
        "event_types": dict(sorted(event_types.items())),
        "days": dict(sorted(days.items())),
        "bytes": int(total_bytes),
        "events": int(events),
        "first_ts": None if first_ts is None else int(first_ts),
        "repo_count": int(repo_count),
        "repo_count_private": repo_count_private,
        "lines": int(lines),
        "updated_at": int(now),
        **(activity_rows(conn, tz) if allowed["agents"] else {}),
        **({"usage": public_rows(conn)} if allowed["usage"] else {}),
    }
    return consented(agg, consent)


def activity_rows(conn, tz=None):
    """Use M2's exact export allowlist; never reconstruct raw event payloads."""
    if "agent" not in {row[1] for row in conn.execute("PRAGMA table_info(events)")}:
        return {"agents": {}, "active_minutes": {}}
    return json.loads(activity.export_aggregate(conn, timezone=tz or timezone.utc))


def _int(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _valid_minutes(value):
    return type(value) in (int, float) and 0 <= value <= 2**63 - 1 and math.isfinite(value)


def _validate_aggregate(agg, now):
    """Validate a whole machine file before any of its values reach rendering."""
    if not isinstance(agg, dict) or type(agg.get("format")) is not int or agg["format"] != AGGREGATE_FORMAT:
        raise ValueError("unsupported format")
    if set(agg) - {"format", *(key for fields in CATEGORY_FIELDS.values() for key in fields)}:
        raise ValueError("unexpected aggregate field")
    if "repo_count_private" in agg and type(agg["repo_count_private"]) is not bool:
        raise ValueError("invalid repository count provenance")
    for key in ("first_ts", "updated_at"):
        if key not in agg:
            continue
        value = agg.get(key)
        if key == "updated_at" and type(value) is int and value == 0:
            continue  # Legacy golden fixture: never synced.
        if key == "first_ts" and value is None:
            continue
        if type(value) is not int or not MIN_TIMESTAMP <= value <= now + 86400:
            raise ValueError(f"invalid {key}")
    for key in ("lines", "bytes", "events", "repo_count"):
        if key not in agg:
            continue
        value = agg.get(key)
        if type(value) is not int or not 0 <= value <= 2**63 - 1:
            raise ValueError(f"invalid {key}")
    totals = agg.get("agents", {})
    if not isinstance(totals, dict):
        raise ValueError("invalid agent totals")
    for agent, row in totals.items():
        if agent not in AGENTS or not isinstance(row, dict) or set(row) != {*AGENT_FIELDS, "active_minutes"}:
            raise ValueError("invalid agent totals")
        if any(type(row[k]) is not int or not 0 <= row[k] <= 2**63 - 1 for k in AGENT_FIELDS):
            raise ValueError("invalid agent count")
        if not _valid_minutes(row["active_minutes"]):
            raise ValueError("invalid active minutes")
    minutes = agg.get("active_minutes", {})
    if not isinstance(minutes, dict):
        raise ValueError("invalid active minutes")
    for day, agents in minutes.items():
        try:
            valid_day = isinstance(day, str) and date.fromisoformat(day).isoformat() == day
        except ValueError:
            valid_day = False
        if (not valid_day or not isinstance(agents, dict)
                or any(agent not in AGENTS or not _valid_minutes(value) for agent, value in agents.items())):
            raise ValueError("invalid daily active minutes")
    rows = agg.get("usage", [])
    if not isinstance(rows, list):
        raise ValueError("invalid usage")
    # Reuse M4's enum, date, count and Decimal validation on untrusted peers.
    try:
        usage_hook.export_usage(rows)
    except (ValueError, TypeError, KeyError, AttributeError):
        raise ValueError("invalid usage") from None
    for key in ("languages", "language_percentages", "event_types", "days"):
        if key not in agg:
            continue
        table = agg.get(key)
        if not isinstance(table, dict):
            raise ValueError(f"invalid {key}")
        for name, value in table.items():
            valid = (type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 100
                     if key == "language_percentages" else type(value) is int and 0 <= value <= 2**63 - 1)
            if not valid:
                raise ValueError(f"invalid {key} count")
            if not isinstance(name, str):
                raise ValueError(f"invalid {key} name")
            if key in ("languages", "language_percentages") and not LANGUAGE_RE.fullmatch(name):
                raise ValueError("invalid language name")
            if key == "event_types" and name not in ("edit", "write", "diff", "commit"):
                raise ValueError("invalid event type")
            if key == "days":
                try:
                    valid_day = date.fromisoformat(name).isoformat() == name
                except ValueError:
                    valid_day = False
                if not valid_day:
                    raise ValueError("invalid day")


def merge(aggregates, now=None):
    """Sum per-machine aggregates into one.

    Counts add up. `repo_count` does not: every machine reads the same GitHub
    account's total, so adding them would multiply it — the largest wins.
    `first_ts` is the earliest, `updated_at` the latest. A malformed file is
    skipped with a warning rather than trusted, since these files come back from a
    repository anyone with push access could edit.
    """
    now = int(time.time() if now is None else now)
    out = {}
    usage_buckets = {}
    common_languages, rounded_languages = None, False
    for agg in aggregates:
        try:
            _validate_aggregate(agg, now)
        except ValueError as exc:
            warnings.warn(f"Skipping invalid machine aggregate: {exc}", RuntimeWarning, stacklevel=2)
            continue
        if "languages" in agg:
            table = agg["languages"]
            total = sum(table.values())
            qualified = {name for name, value in table.items() if value > 0 and value * 100 >= total}
        elif "language_percentages" in agg:
            table = agg["language_percentages"]
            rounded_languages = True
            qualified = {name for name, value in table.items() if value > 1.0}
        else:
            table = None
        if table:
            common_languages = qualified if common_languages is None else common_languages & qualified
        for key in ("languages", "language_percentages", "event_types", "days"):
            table = agg.get(key)
            if not isinstance(table, dict):
                continue
            out.setdefault(key, {})
            for name, value in table.items():
                if isinstance(name, str) and len(name) <= 32:
                    out[key][name] = out[key].get(name, 0) + value
        # Legacy files represented their line total only through language counts.
        # Include that contribution when mixing them with explicit modern totals.
        if "lines" in agg or "languages" in agg:
            out["lines"] = out.get("lines", 0) + agg.get("lines", sum(agg.get("languages", {}).values()))
        for key in ("bytes", "events"):
            if key in agg:
                out[key] = out.get(key, 0) + agg[key]
        if "first_ts" in agg:
            out.setdefault("first_ts", None)
        first = agg.get("first_ts")
        if _int(first) and (out.get("first_ts") is None or first < out["first_ts"]):
            out["first_ts"] = first
        for key in ("repo_count", "updated_at"):
            if key in agg:
                out[key] = max(out.get(key, 0), agg[key])
        for key in ("agents", "active_minutes", "usage"):
            if key in agg:
                out.setdefault(key, [] if key == "usage" else {})
        for agent, row in agg.get("agents", {}).items():
            dest = out["agents"].setdefault(agent, dict.fromkeys((*AGENT_FIELDS, "active_minutes"), 0))
            for key in (*AGENT_FIELDS, "active_minutes"):
                dest[key] += row[key]
        for day, agents in agg.get("active_minutes", {}).items():
            dest = out["active_minutes"].setdefault(day, {})
            for agent, minutes in agents.items():
                dest[agent] = dest.get(agent, 0) + minutes
        for row in json.loads(usage_hook.export_usage(agg.get("usage", []))):
            key = (row["date"], row["agent"], row["model_family"])
            if key not in usage_buckets:
                usage_buckets[key] = row
                continue
            dest = usage_buckets[key]
            for name in usage_hook.TOKEN_FIELDS:
                dest[name] += row[name]
            a, b = dest["estimated_cost_usd"], row["estimated_cost_usd"]
            with localcontext() as ctx:
                ctx.prec = 80
                dest["estimated_cost_usd"] = None if a is None or b is None else format(Decimal(a) + Decimal(b), "f")
    if "usage" in out:
        out["usage"] = [usage_buckets[key] for key in sorted(usage_buckets)]
    if rounded_languages:
        # Internal rendering provenance, never a field in a machine aggregate.
        # Unknown machine weights require qualification in every source.
        out["_polyglot_eligible_languages"] = sorted(common_languages or ())
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
              sponsorable=False, card=None):
    """What the renderer draws, from merged aggregates. Mirrors loadCardData()."""
    to_day = day_fn(tz)
    rows = sorted(
        ((name, lines) for name, lines in merged.get("languages", merged.get("language_percentages", {})).items() if lines > 0),
        key=lambda item: (-item[1], item[0]),
    )
    languages = [LanguageSlice(name, lines) for name, lines in rows]
    counts = merged.get("event_types", {})
    heat_cutoff = to_day(int(now) - (HEAT_WEEKS * 7 + 2) * 86400)
    day_lines = {day: lines for day, lines in merged.get("days", {}).items() if day >= heat_cutoff}
    weeks, marks, streak = build_heatmap(day_lines, to_day(int(now)), locale)
    today = to_day(int(now))
    published_cutoff = to_day(int(now) - KEEP_DAYS * 86400)
    longest, run, previous = 0, 0, None
    for day, lines in sorted(merged.get("days", {}).items()):
        if lines <= 0 or not published_cutoff <= day <= today:
            continue
        run = run + 1 if previous is not None and day == _shift(previous, 1) else 1
        longest = max(longest, run)
        previous = day
    model_tokens = {}
    for row in merged.get("usage", []):
        family = row["model_family"]
        model_tokens[family] = model_tokens.get(family, 0) + sum(row[name] for name in usage_hook.TOKEN_FIELDS)
    eligible = merged.get("_polyglot_eligible_languages")
    if eligible is None and "languages" not in merged and "language_percentages" in merged:
        eligible = [name for name, pct in merged["language_percentages"].items() if pct > 1.0]
    return CardData(
        languages=languages,
        total_lines=merged.get("lines", sum(s.total for s in languages)),
        total_bytes=merged.get("bytes", 0),
        repo_count=merged.get("repo_count", 0),
        badges=[dict(b) for b in badges][:8],
        pins=[dict(p) for p in pins][:3],
        total_commits=counts.get("commit", 0),
        total_actions=counts.get("edit", 0) + counts.get("write", 0),
        total_diffs=counts.get("diff", 0),
        first_ts=merged.get("first_ts"),
        total_events=merged.get("events", 0),
        updated_at=merged.get("updated_at", 0),
        heat_weeks=weeks,
        month_marks=marks,
        streak=streak,
        avatar=avatar,
        sponsorable=sponsorable,
        github_user=github_user,
        agent_totals=merged.get("agents", {}),
        usage=merged.get("usage", []),
        show_agents=isinstance(card, dict) and card.get("show_agents") is True,
        show_usage=isinstance(card, dict) and card.get("show_usage") is True,
        active_minutes=sum(row["active_minutes"] for row in merged.get("agents", {}).values())
        if merged.get("agents") else None,
        sections=frozenset(category for category, fields in CATEGORY_FIELDS.items() if any(key in merged for key in fields)),
        language_total=sum(s.total for s in languages),
        model_tokens=model_tokens,
        longest_streak=longest,
        show_models=isinstance(card, dict) and card.get("show_models") is True,
        polyglot_eligible_languages=frozenset(eligible) if eligible is not None else None,
    )
