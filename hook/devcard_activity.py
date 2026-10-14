"""Pure event-based activity estimates and content-private aggregate export.

No hook payloads, credentials, filesystem paths or installation identifiers are
needed here. Times are Unix seconds; callers must supply a reporting timezone.
"""
import json
import math
from datetime import datetime, time, timedelta, tzinfo
from zoneinfo import ZoneInfo

AGENTS = ("claude-code", "codex", "git", "unknown")
DEFAULT_IDLE_MINUTES = 15
DEFAULT_TAIL_MINUTES = 2


def normalize_agent(agent):
    """Keep only fixed origin labels; NULL/legacy/unrecognized values are unknown."""
    return agent if isinstance(agent, str) and agent in AGENTS else "unknown"


def _timezone(value):
    zone = ZoneInfo(value) if isinstance(value, str) else value
    if not isinstance(zone, tzinfo) or datetime(2000, 1, 1, tzinfo=zone).utcoffset() is None:
        raise ValueError("an explicit timezone is required")
    return zone


def _minutes(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite nonnegative number")
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be a finite nonnegative number")
    return value * 60


def active_minutes(events, *, timezone, idle_minutes=DEFAULT_IDLE_MINUTES,
                   tail_minutes=DEFAULT_TAIL_MINUTES):
    """Return {local ISO day: {agent: minutes}} from independent agent sessions.

    Sort and deduplicate each agent's timestamps. A gap strictly greater than
    idle_minutes closes a session; its duration is last minus first plus tail.
    Split sessions at local midnight using elapsed Unix time (including DST).
    Concurrent agents are credited independently, so summing their estimates
    gives agent time, which can exceed elapsed wall time. Inputs are not mutated.
    """
    zone = _timezone(timezone)
    idle = _minutes(idle_minutes, "idle_minutes")
    tail = _minutes(tail_minutes, "tail_minutes")
    timestamps = {}
    for event in events:
        ts = event["ts"]
        if isinstance(ts, bool) or not isinstance(ts, (int, float)) or not math.isfinite(ts):
            raise ValueError("event timestamp must be finite Unix seconds")
        agent = normalize_agent(event.get("agent"))
        timestamps.setdefault(agent, set()).add(ts)

    days = {}

    def credit(start, end, agent):
        while start < end:
            local = datetime.fromtimestamp(start, zone)
            day = local.date().isoformat()
            midnight = datetime.combine(local.date() + timedelta(days=1), time.min, zone).timestamp()
            stop = min(end, midnight)
            bucket = days.setdefault(day, {})
            bucket[agent] = bucket.get(agent, 0) + (stop - start) / 60
            start = stop

    for agent, values in timestamps.items():
        ordered = sorted(values)
        first = last = ordered[0]
        for ts in ordered[1:]:
            if ts - last > idle:
                credit(first, last + tail, agent)
                first = ts
            last = ts
        credit(first, last + tail, agent)
    return {day: dict(sorted(agents.items())) for day, agents in sorted(days.items())}


def export_aggregate(conn, *, timezone, idle_minutes=DEFAULT_IDLE_MINUTES,
                     tail_minutes=DEFAULT_TAIL_MINUTES):
    """Serialize only per-agent totals and daily active minutes as UTF-8 JSON.

    An explicit SQL projection excludes project_key, source_id and row ids.
    Languages, raw timestamps and arbitrary event strings are not exported
    either. This is a local M2 export; the legacy Worker wire format is intact.
    """
    rows = [dict(zip(("ts", "agent", "lines_added", "lines_removed", "bytes_added", "event_type"), row, strict=True))
            for row in conn.execute(
                "SELECT ts, agent, lines_added, lines_removed, bytes_added, event_type FROM events"
            )]
    activity = active_minutes(rows, timezone=timezone, idle_minutes=idle_minutes, tail_minutes=tail_minutes)
    totals = {}
    for event in rows:
        agent = normalize_agent(event["agent"])
        total = totals.setdefault(agent, {
            "events": 0, "commits": 0, "code_edits": 0,
            "lines_added": 0, "lines_removed": 0, "bytes_added": 0, "active_minutes": 0,
        })
        total["events"] += 1
        total["commits"] += event["event_type"] == "commit"
        total["code_edits"] += event["event_type"] in ("edit", "write")
        for key in ("lines_added", "lines_removed", "bytes_added"):
            total[key] += event[key]
    for agents in activity.values():
        for agent, minutes in agents.items():
            totals[agent]["active_minutes"] += minutes
    return json.dumps({"agents": totals, "active_minutes": activity},
                      sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
