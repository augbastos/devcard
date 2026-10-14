"""Offline, incremental coding-agent usage; no network or hook-side effects.

Only explicit source paths are read. Callers supply the existing SQLite
connection and run this module in the background, outside tool capture.
"""

from collections import defaultdict
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone, tzinfo
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import hmac
import json
from pathlib import Path
import secrets
import sqlite3


COST_LABEL = (
    "API-equivalent cost (estimate at bundled API rates; not your subscription bill)"
)
MODEL_FAMILIES = frozenset({
    "claude-sonnet", "claude-opus", "claude-haiku", "gpt", "o", "unknown",
})
AGENTS = frozenset({"claude", "codex"})
TOKEN_FIELDS = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens")
PUBLIC_FIELDS = ("date", "agent", "model_family", *TOKEN_FIELDS, "estimated_cost_usd")
_HERE = Path(__file__).resolve().parent
# The price table ships inside the `devcard` package: next to this file when installed
# (site-packages), one level up in a checkout (hook/ beside devcard/).
PRICES_PATH = next((p for p in (_HERE / "devcard" / "prices.json", _HERE.parent / "devcard" / "prices.json")
                    if p.exists()), _HERE.parent / "devcard" / "prices.json")
MAX_LINE_BYTES = 4 * 1024 * 1024

# Exact spellings only. A free-form model field can itself carry private text.
_MODELS = {
    "claude-sonnet-4-5": "claude-sonnet",
    "claude-sonnet-4-5-20250929": "claude-sonnet",
    "claude-sonnet-4.5": "claude-sonnet",
    "claude-sonnet-4": "claude-sonnet",
    "claude-sonnet-4-20250514": "claude-sonnet",
    "claude-sonnet-4-6": "claude-sonnet",
    "claude-opus-4": "claude-opus",
    "claude-opus-4-20250514": "claude-opus",
    "claude-opus-4-1": "claude-opus",
    "claude-opus-4-1-20250805": "claude-opus",
    "claude-opus-4-5": "claude-opus",
    "claude-opus-4-5-20251101": "claude-opus",
    "claude-opus-4-6": "claude-opus",
    "claude-haiku-4-5": "claude-haiku",
    "claude-haiku-4-5-20251001": "claude-haiku",
    **dict.fromkeys((
        "gpt-5", "gpt-5-codex", "gpt-5.1", "gpt-5.1-codex",
        "gpt-5.1-codex-max", "gpt-5.2", "gpt-5.2-codex", "gpt-5.3-codex",
        "gpt-5.4", "gpt-6", "gpt-6.1",
    ), "gpt"),
    "o3": "o", "o4-mini": "o",
}


class UsageDataError(ValueError):
    """Structural diagnostics only: never include source data in the message."""


@dataclass(frozen=True)
class LocatedRecord:
    start: int
    end: int
    record: Mapping | None
    diagnostic: str | None = None


@dataclass(frozen=True)
class UsageCall:
    key: str
    agent: str
    timestamp: datetime
    model: str | None
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cache_write_5m_tokens: int | None = None
    cache_write_1h_tokens: int | None = None
    message_key: str | None = None
    request_missing: bool = False
    kind: str = "response"
    pricing_complete: bool = True

    @property
    def model_family(self):
        return _MODELS.get(self.model, "unknown")


UsageRevision = UsageCall


@dataclass(frozen=True)
class PriceTable:
    table_version: str
    models: Mapping
    aliases: Mapping


@dataclass(frozen=True)
class PublicUsage:
    date: str
    agent: str
    model_family: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    estimated_cost_usd: Decimal | None


@dataclass
class ScanReport:
    files: int = 0
    lines: int = 0
    calls_updated: int = 0
    incomplete: bool = False
    diagnostics: dict[str, int] = field(default_factory=dict)

    def note(self, code):
        self.diagnostics[code] = self.diagnostics.get(code, 0) + 1
        self.incomplete = True


def _identity(salt: bytes, *parts: object) -> str:
    encoded = json.dumps(parts, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    return hmac.new(salt, encoded, hashlib.sha256).hexdigest()


def _mapping(value):
    return value if isinstance(value, Mapping) else {}


def _count(value):
    if type(value) is not int or not 0 <= value <= 2**63 - 1:
        raise UsageDataError("invalid_token_count")
    return value


def _timestamp(value):
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None or result.utcoffset() is None:
            raise ValueError
        return result.astimezone(timezone.utc)
    except (TypeError, AttributeError, ValueError):
        raise UsageDataError("invalid_timestamp") from None


def _model(value):
    return value if isinstance(value, str) and value in _MODELS else None


def load_prices(path: Path | None = None) -> PriceTable:
    """Load the bundled table only. No refresh, network or third-party library."""
    with (PRICES_PATH if path is None else Path(path)).open(encoding="utf-8") as source:
        data = json.load(source)
    if (data.get("schema_version") != 1 or data.get("currency") != "USD"
            or not isinstance(data.get("table_version"), str)):
        raise ValueError("unsupported_price_table")
    return PriceTable(data["table_version"], data["models"], data.get("aliases", {}))


def _rate(value):
    try:
        rate = Decimal(value) if isinstance(value, str) else None
        return rate if rate is not None and rate.is_finite() and rate >= 0 else None
    except InvalidOperation:
        return None


def estimate_api_equivalent_cost(call: UsageCall, prices: PriceTable) -> Decimal | None:
    """Price disjoint categories once, per call, before any aggregation."""
    if call.model is None:
        return None
    entry = _mapping(prices.models.get(prices.aliases.get(call.model, call.model)))
    if not call.pricing_complete:
        # A snapshot interval has no call boundaries. A reviewed flat schedule
        # is linear, so pricing its disjoint delta is exactly the sum of calls;
        # a tier/context-dependent schedule cannot make that guarantee.
        if (call.kind != "snapshot" or entry.get("context_tiers")
                or entry.get("context_limit") is not None):
            return None
    rates = entry.get("rates_per_million")
    context = call.input_tokens + call.cache_read_tokens + call.cache_write_tokens
    tiers = entry.get("context_tiers", [])
    if tiers:
        # A tier is a complete rate schedule, never an implicit multiplier.
        rates = None
        for tier in tiers:
            maximum = tier.get("max_input_tokens")
            if maximum is None or context <= maximum:
                rates = tier.get("rates_per_million")
                break
    elif entry.get("context_limit") is not None and context > entry["context_limit"]:
        return None
    if not isinstance(rates, Mapping):
        return None
    categories = [(call.input_tokens, "input"), (call.output_tokens, "output"),
                  (call.cache_read_tokens, "cache_read")]
    if call.agent == "claude" and call.cache_write_tokens:
        if (call.cache_write_5m_tokens is None or call.cache_write_1h_tokens is None
                or call.cache_write_5m_tokens + call.cache_write_1h_tokens != call.cache_write_tokens):
            return None
        categories.extend([(call.cache_write_5m_tokens, "cache_write_5m"),
                           (call.cache_write_1h_tokens, "cache_write_1h")])
    else:
        categories.append((call.cache_write_tokens, "cache_write"))
    with localcontext() as context_decimal:
        context_decimal.prec = 80
        total = Decimal(0)
        for tokens, category in categories:
            _count(tokens)
            if not tokens:
                continue
            rate = _rate(rates.get(category))
            if rate is None:
                return None
            total += tokens * rate
        return total / Decimal(1_000_000)


def iter_jsonl(path: Path, *, offset: int = 0, limit: int) -> Iterator[LocatedRecord]:
    """Read a frozen byte prefix; leave the last unfinished line on disk.

    Malformed complete lines advance the cursor and emit a structural code.
    Oversized lines are drained in bounded chunks without retaining their text.
    """
    with Path(path).open("rb") as source:
        source.seek(offset)
        while source.tell() < limit:
            start = source.tell()
            line = source.readline(min(limit - start, MAX_LINE_BYTES + 1))
            oversized = len(line) > MAX_LINE_BYTES
            while not line.endswith(b"\n") and source.tell() < limit and oversized:
                line = source.readline(min(limit - source.tell(), MAX_LINE_BYTES + 1))
            if not line.endswith(b"\n"):
                break
            end = source.tell()
            if oversized:
                yield LocatedRecord(start, end, None, "oversized_line")
                continue
            try:
                record = json.loads(line)
                if not isinstance(record, Mapping):
                    raise ValueError
            except (ValueError, UnicodeError):
                yield LocatedRecord(start, end, None, "malformed_line")
            else:
                yield LocatedRecord(start, end, record)


def parse_claude(record: Mapping, *, salt: bytes) -> UsageRevision | None:
    if record.get("type") != "assistant":
        return None
    message = _mapping(record.get("message"))
    usage = message.get("usage")
    if not isinstance(usage, Mapping):
        return None
    normal = _count(usage.get("input_tokens", 0))
    output = _count(usage.get("output_tokens", 0))
    read = _count(usage.get("cache_read_input_tokens", 0))
    write = _count(usage.get("cache_creation_input_tokens", 0))
    message_id = message.get("id")
    request_id = record.get("requestId")
    if not isinstance(message_id, str) or not message_id:
        if normal + output + read + write:
            raise UsageDataError("missing_claude_identity")
        return None
    missing = not isinstance(request_id, str) or not request_id
    ttl = _mapping(usage.get("cache_creation"))
    five = ttl.get("ephemeral_5m_input_tokens")
    hour = ttl.get("ephemeral_1h_input_tokens")
    if five is not None:
        five = _count(five)
    if hour is not None:
        hour = _count(hour)
    complete = (five is not None and hour is not None and five + hour == write)
    if not write and not (five or hour):
        complete = True
    return UsageCall(
        _identity(salt, "claude", message_id, None if missing else request_id),
        "claude", _timestamp(record.get("timestamp")), _model(message.get("model")),
        normal, output, read, write, five, hour,
        _identity(salt, "claude-message", message_id), missing,
        pricing_complete=complete,
    )


def _codex_vector(usage):
    usage = _mapping(usage)
    total_input = _count(usage.get("input_tokens", 0))
    read = _count(usage.get("cached_input_tokens", 0))
    write = _count(usage.get("cache_write_input_tokens", 0))
    output = _count(usage.get("output_tokens", 0))
    if read + write > total_input or _count(usage.get("reasoning_output_tokens", 0)) > output:
        raise UsageDataError("inconsistent_codex_usage")
    if "total_tokens" in usage and _count(usage["total_tokens"]) != total_input + output:
        raise UsageDataError("inconsistent_codex_total")
    return (total_input - read - write, output, read, write)


@dataclass
class CodexState:
    salt: bytes
    file_key: str = "standalone"
    model: str | None = None
    session_key: str | None = None
    previous: tuple | None = None
    pending: tuple = (0, 0, 0, 0)
    epoch: int = 0
    untrusted_baseline: bool = False
    last_snapshot_key: str | None = None
    last_snapshot_residual: tuple = (0, 0, 0, 0)
    seen_responses: set = field(default_factory=set)
    diagnostics: list = field(default_factory=list)
    snapshot_adjustments: list = field(default_factory=list)

    def dump(self):
        return json.dumps({
            "model": self.model, "session_key": self.session_key,
            "previous": self.previous, "pending": self.pending, "epoch": self.epoch,
            "untrusted_baseline": self.untrusted_baseline,
            "last_snapshot_key": self.last_snapshot_key,
            "last_snapshot_residual": self.last_snapshot_residual,
        }, separators=(",", ":"))

    @classmethod
    def restore(cls, salt, file_key, data):
        state = cls(salt, file_key)
        if data:
            stored = json.loads(data)
            state.model = _model(stored["model"])
            state.session_key = stored["session_key"]
            state.previous = tuple(stored["previous"]) if stored["previous"] is not None else None
            state.pending = tuple(stored["pending"])
            state.epoch = stored["epoch"]
            state.untrusted_baseline = stored.get("untrusted_baseline", False)
            state.last_snapshot_key = stored.get("last_snapshot_key")
            state.last_snapshot_residual = tuple(stored.get("last_snapshot_residual", (0, 0, 0, 0)))
        return state


def parse_codex(record: Mapping, state: CodexState) -> UsageRevision | None:
    payload = _mapping(record.get("payload"))
    kind = record.get("type")
    if kind == "session_meta":
        session_id = payload.get("id")
        if isinstance(session_id, str) and session_id:
            session_key = _identity(state.salt, "codex-session", session_id)
            if state.session_key is not None and session_key != state.session_key:
                state.previous = None
                state.pending = (0, 0, 0, 0)
                state.epoch = 0
                state.model = None
                state.untrusted_baseline = False
                state.last_snapshot_key = None
                state.last_snapshot_residual = (0, 0, 0, 0)
                state.diagnostics.append("codex_session_changed")
            state.session_key = session_key
            state.untrusted_baseline = False
        if any(payload.get(name) for name in ("forked_from_id", "forked_from", "parent_session_id")):
            state.untrusted_baseline = True
            state.diagnostics.append("fork_history_requires_baseline")
        return None
    if kind == "turn_context":
        state.model = _model(payload.get("model"))
        return None
    if kind == "token_usage_record":
        response_id = payload.get("response_id")
        if not isinstance(response_id, str) or not response_id:
            raise UsageDataError("missing_codex_identity")
        key = _identity(state.salt, "codex", response_id)
        if key in state.seen_responses:
            return None
        if not isinstance(payload.get("usage"), Mapping):
            raise UsageDataError("missing_codex_usage")
        vector = _codex_vector(payload["usage"])
        stamp = _timestamp(record.get("timestamp"))
        state.seen_responses.add(key)
        cumulative = payload.get("thread_token_usage")
        covered = False
        if state.previous is not None and isinstance(cumulative, Mapping):
            cumulative = _codex_vector(cumulative)
            covered = all(a <= b for a, b in zip(cumulative, state.previous, strict=True))
            if covered:
                if (cumulative == state.previous and state.last_snapshot_key is not None
                        and all(a <= b for a, b in zip(vector, state.last_snapshot_residual, strict=True))):
                    state.snapshot_adjustments.append((state.last_snapshot_key, key, vector))
                    state.last_snapshot_residual = tuple(
                        b - a for a, b in zip(vector, state.last_snapshot_residual, strict=True))
                else:
                    # There is no identifiable snapshot interval to revise. Keep
                    # its counted tokens and diagnose, rather than double count.
                    state.diagnostics.append("unreconciled_codex_response_overlap")
                    return None
        if not covered:
            state.pending = tuple(a + b for a, b in zip(state.pending, vector, strict=True))
        if state.model is None:
            state.diagnostics.append("unknown_codex_model")
        return UsageCall(key, "codex", stamp, state.model, *vector)
    if kind != "event_msg" or payload.get("type") != "token_count":
        return None
    info = payload.get("info")
    if info is None:
        return None
    if not isinstance(info, Mapping) or not isinstance(info.get("total_token_usage"), Mapping):
        raise UsageDataError("invalid_codex_snapshot")
    current = _codex_vector(info["total_token_usage"])
    stamp = _timestamp(record.get("timestamp"))
    previous = state.previous
    if previous is None:
        last = info.get("last_token_usage")
        verified = (not any(current) or current == state.pending
                    or (not state.untrusted_baseline and isinstance(last, Mapping)
                        and _codex_vector(last) == current))
        if not verified:
            state.previous = current
            # A first snapshot can lag explicit responses too. The unverified
            # historical prefix is not counted, but response coverage beyond
            # this baseline must survive until a later snapshot catches up.
            state.pending = tuple(max(0, b - a) for a, b in zip(current, state.pending, strict=True))
            state.diagnostics.append("unverified_codex_baseline")
            state.untrusted_baseline = False
            state.last_snapshot_key = None
            return None
        previous = (0, 0, 0, 0)
        state.untrusted_baseline = False
    delta = tuple(a - b for a, b in zip(current, previous, strict=True))
    if any(value < 0 for value in delta):
        state.epoch += 1
        state.previous = current
        state.pending = (0, 0, 0, 0)
        state.last_snapshot_key = None
        state.last_snapshot_residual = (0, 0, 0, 0)
        state.diagnostics.append("codex_counter_reset")
        return None
    residual = tuple(max(0, a - b) for a, b in zip(delta, state.pending, strict=True))
    state.pending = tuple(max(0, b - a) for a, b in zip(delta, state.pending, strict=True))
    state.previous = current
    if any(delta):
        state.last_snapshot_key = _identity(
            state.salt, "codex-delta", state.session_key or state.file_key,
            state.epoch, previous, current)
        state.last_snapshot_residual = residual
    if not any(residual):
        return None
    if state.seen_responses:
        state.diagnostics.append("partial_codex_response_coverage")
    if state.model is None:
        state.diagnostics.append("unknown_codex_model")
    key = state.last_snapshot_key
    # Snapshots may span several calls: the estimator can use reviewed flat
    # rates, but cannot establish a per-call context tier for this interval.
    return UsageCall(key, "codex", stamp, state.model, *residual, kind="snapshot",
                     pricing_complete=False)


def ensure_usage_schema(conn: sqlite3.Connection):
    """Add local tables to the caller's database without touching event schema.

    No executescript/implicit commit: safe even in the caller's transaction.
    """
    statements = (
        "CREATE TABLE IF NOT EXISTS usage_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
        """CREATE TABLE IF NOT EXISTS usage_files (
            file_key TEXT PRIMARY KEY, agent TEXT NOT NULL, generation INTEGER NOT NULL,
            offset INTEGER NOT NULL, signature TEXT NOT NULL, prefix_hash TEXT NOT NULL,
            boundary_hash TEXT NOT NULL, mtime_ns INTEGER NOT NULL, state TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS usage_calls (
            call_key TEXT PRIMARY KEY, agent TEXT NOT NULL, model TEXT,
            model_family TEXT NOT NULL, timestamp TEXT NOT NULL, revised_at TEXT NOT NULL,
            date TEXT NOT NULL, input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL,
            cache_read_tokens INTEGER NOT NULL, cache_write_tokens INTEGER NOT NULL,
            cache_write_5m_tokens INTEGER, cache_write_1h_tokens INTEGER,
            estimated_cost_usd TEXT, price_version TEXT NOT NULL, kind TEXT NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS usage_calls_bucket ON usage_calls(date, agent, model_family)",
        """CREATE TABLE IF NOT EXISTS usage_messages (
            message_key TEXT NOT NULL, call_key TEXT NOT NULL, missing INTEGER NOT NULL,
            PRIMARY KEY (message_key, call_key))""",
        """CREATE TABLE IF NOT EXISTS usage_file_responses (
            file_key TEXT NOT NULL, generation INTEGER NOT NULL, call_key TEXT NOT NULL,
            PRIMARY KEY (file_key, generation, call_key))""",
        """CREATE TABLE IF NOT EXISTS usage_codex_reconciliations (
            snapshot_key TEXT NOT NULL, response_key TEXT NOT NULL,
            input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL,
            cache_read_tokens INTEGER NOT NULL, cache_write_tokens INTEGER NOT NULL,
            PRIMARY KEY(snapshot_key, response_key))""",
        """CREATE TABLE IF NOT EXISTS usage_aggregates (
            date TEXT NOT NULL, agent TEXT NOT NULL, model_family TEXT NOT NULL,
            input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL,
            cache_read_tokens INTEGER NOT NULL, cache_write_tokens INTEGER NOT NULL,
            known_cost_usd TEXT NOT NULL, unknown_cost_calls INTEGER NOT NULL,
            call_count INTEGER NOT NULL, PRIMARY KEY(date, agent, model_family))""",
        """CREATE TABLE IF NOT EXISTS usage_diagnostics (
            file_key TEXT NOT NULL, generation INTEGER NOT NULL, code TEXT NOT NULL,
            count INTEGER NOT NULL, PRIMARY KEY(file_key, generation, code))""",
    )
    for statement in statements:
        conn.execute(statement)
    conn.execute("INSERT OR IGNORE INTO usage_meta VALUES ('schema_version', '1')")
    version = conn.execute("SELECT value FROM usage_meta WHERE key='schema_version'").fetchone()[0]
    if version != "1":
        raise ValueError("unsupported_usage_schema")
    conn.execute("INSERT OR IGNORE INTO usage_meta VALUES ('salt', ?)", (secrets.token_hex(32),))


def _rows(conn, sql, params=()):
    cursor = conn.execute(sql, params)
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def _adjust_bucket(conn, row, sign):
    bucket = (row["date"], row["agent"], row["model_family"])
    existing = _rows(conn, "SELECT * FROM usage_aggregates WHERE date=? AND agent=? AND model_family=?", bucket)
    old = existing[0] if existing else {**dict.fromkeys(TOKEN_FIELDS, 0),
                                      "known_cost_usd": "0", "unknown_cost_calls": 0, "call_count": 0}
    count = old["call_count"] + sign
    if not count:
        conn.execute("DELETE FROM usage_aggregates WHERE date=? AND agent=? AND model_family=?", bucket)
        return
    tokens = [old[name] + sign * row[name] for name in TOKEN_FIELDS]
    unknown = old["unknown_cost_calls"] + sign * (row["estimated_cost_usd"] is None)
    with localcontext() as context:
        context.prec = 80
        cost = Decimal(old["known_cost_usd"]) + sign * Decimal(row["estimated_cost_usd"] or "0")
    conn.execute("INSERT OR REPLACE INTO usage_aggregates VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 (*bucket, *tokens, format(cost, "f"), unknown, count))


def _store_call(conn, call, tz, prices):
    old = _rows(conn, "SELECT * FROM usage_calls WHERE call_key=?", (call.key,))
    if old and call.agent == "codex":
        # Response ids and stable snapshot transition keys are global first-wins.
        return False
    if call.kind == "snapshot":
        # A wholly replaced snapshot keeps a numeric tombstone so a rotated
        # copy cannot reintroduce the tokens now owned by explicit responses.
        covered = _rows(conn, "SELECT * FROM usage_codex_reconciliations WHERE snapshot_key=?", (call.key,))
        if covered:
            counts = {name: max(0, getattr(call, name) - sum(row[name] for row in covered))
                      for name in TOKEN_FIELDS}
            if not any(counts.values()):
                return False
            call = replace(call, **counts)
    revised_at = call.timestamp.isoformat()
    if old and revised_at < old[0]["revised_at"]:
        return False
    if old:
        logical = ("model", *TOKEN_FIELDS, "cache_write_5m_tokens", "cache_write_1h_tokens", "kind")
        if all(getattr(call, name) == old[0][name] for name in logical):
            # Reimporting an identical observation must not undo an explicit
            # reprice or silently apply a newly replaced bundled table.
            if revised_at != old[0]["revised_at"]:
                conn.execute("UPDATE usage_calls SET revised_at=? WHERE call_key=?", (revised_at, call.key))
                return True
            return False
    timestamp = old[0]["timestamp"] if old else revised_at
    date = _timestamp(timestamp).astimezone(tz).date().isoformat()
    cost = estimate_api_equivalent_cost(call, prices)
    row = dict(zip((
        "call_key", "agent", "model", "model_family", "timestamp", "revised_at", "date",
        *TOKEN_FIELDS, "cache_write_5m_tokens", "cache_write_1h_tokens", "estimated_cost_usd",
        "price_version", "kind",
    ), (call.key, call.agent, call.model, call.model_family, timestamp, revised_at, date,
        *(getattr(call, name) for name in TOKEN_FIELDS), call.cache_write_5m_tokens,
        call.cache_write_1h_tokens, None if cost is None else format(cost, "f"),
        prices.table_version, call.kind), strict=True))
    if old and old[0] == row:
        return False
    if old:
        _adjust_bucket(conn, old[0], -1)
    conn.execute("INSERT OR REPLACE INTO usage_calls VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 tuple(row.values()))
    _adjust_bucket(conn, row, 1)
    return True


def _reconcile_snapshot(conn, snapshot_key, response_key, vector, prices):
    inserted = conn.execute("INSERT OR IGNORE INTO usage_codex_reconciliations VALUES (?, ?, ?, ?, ?, ?)",
                            (snapshot_key, response_key, *vector)).rowcount
    if not inserted:
        return
    rows = _rows(conn, "SELECT * FROM usage_calls WHERE call_key=? AND kind='snapshot'", (snapshot_key,))
    if not rows:
        return
    row = rows[0]
    _adjust_bucket(conn, row, -1)
    counts = [max(0, row[name] - value) for name, value in zip(TOKEN_FIELDS, vector, strict=True)]
    if any(counts):
        row.update(zip(TOKEN_FIELDS, counts, strict=True))
        call = UsageCall(snapshot_key, "codex", _timestamp(row["timestamp"]), row["model"],
                         *counts, kind="snapshot", pricing_complete=False)
        cost = (estimate_api_equivalent_cost(call, prices)
                if row["price_version"] == prices.table_version else None)
        row["estimated_cost_usd"] = None if cost is None else format(cost, "f")
        conn.execute("""UPDATE usage_calls SET input_tokens=?, output_tokens=?, cache_read_tokens=?,
                     cache_write_tokens=?, estimated_cost_usd=? WHERE call_key=?""",
                     (*counts, row["estimated_cost_usd"], snapshot_key))
        _adjust_bucket(conn, row, 1)
    else:
        conn.execute("DELETE FROM usage_calls WHERE call_key=?", (snapshot_key,))


def _claude_identity(conn, call):
    observations = _rows(conn, "SELECT * FROM usage_messages WHERE message_key=?", (call.message_key,))
    full = [row for row in observations if not row["missing"]]
    fallback = [row for row in observations if row["missing"]]
    if call.request_missing and len(full) > 1:
        raise UsageDataError("ambiguous_claude_request")
    if call.request_missing and full:
        call = replace(call, key=full[0]["call_key"])
    elif not call.request_missing and fallback:
        if full and all(row["call_key"] != call.key for row in full):
            raise UsageDataError("ambiguous_claude_request")
        # Promote a validated message-only identity, preserving its first date.
        conn.execute("UPDATE usage_calls SET call_key=? WHERE call_key=?", (call.key, fallback[0]["call_key"]))
        conn.execute("DELETE FROM usage_messages WHERE message_key=? AND missing=1", (call.message_key,))
    conn.execute("INSERT OR IGNORE INTO usage_messages VALUES (?, ?, ?)",
                 (call.message_key, call.key, int(call.request_missing and not full)))
    return call


def discover_usage_paths(root: Path, *, agent: str) -> list[Path]:
    """Explicit root only; recursive JSONL discovery includes Claude subagents."""
    if agent not in AGENTS:
        raise ValueError("unsupported_agent")
    return sorted(path for path in Path(root).rglob("*.jsonl") if path.is_file() and not path.is_symlink())


def _fingerprints(path, offset):
    with path.open("rb") as source:
        prefix = source.read(min(256, offset))
        source.seek(max(0, offset - 256))
        boundary = source.read(min(256, offset))
    return hashlib.sha256(prefix).hexdigest(), hashlib.sha256(boundary).hexdigest()


def scan_usage(paths: Iterable[Path], conn: sqlite3.Connection, *, agent: str,
               tz: tzinfo = timezone.utc, prices: PriceTable | None = None) -> ScanReport:
    """Commit cursor, revisions, diagnostics and bucket deltas atomically.

    Savepoints preserve any caller-owned transaction. Replacing the bundled
    table does not silently reprice existing calls; use reprice_usage explicitly.
    """
    if agent not in AGENTS:
        raise ValueError("unsupported_agent")
    if tz is None:
        raise ValueError("explicit_timezone_required")
    prices = load_prices() if prices is None else prices
    report = ScanReport()
    conn.execute("SAVEPOINT usage_scan")
    try:
        ensure_usage_schema(conn)
        zone = getattr(tz, "key", str(tz))
        conn.execute("INSERT OR IGNORE INTO usage_meta VALUES ('timezone', ?)", (zone,))
        if conn.execute("SELECT value FROM usage_meta WHERE key='timezone'").fetchone()[0] != zone:
            raise ValueError("usage_timezone_changed")
        salt = bytes.fromhex(conn.execute("SELECT value FROM usage_meta WHERE key='salt'").fetchone()[0])
        for path in sorted(set(Path(path).resolve() for path in paths)):
            # Filenames are local and explicit; .env and non-transcripts are never opened.
            if path.suffix != ".jsonl":
                report.note("non_jsonl_source")
                continue
            try:
                stat = path.stat()
            except OSError:
                report.note("source_unavailable")
                continue
            file_key = _identity(salt, "file", str(path))
            signature = _identity(salt, "file-stat", stat.st_dev, stat.st_ino,
                                  getattr(stat, "st_birthtime_ns", None))
            stored = _rows(conn, "SELECT * FROM usage_files WHERE file_key=?", (file_key,))
            old = stored[0] if stored else None
            if old and old["agent"] != agent:
                raise ValueError("source_agent_changed")
            generation = old["generation"] if old else 0
            offset = old["offset"] if old else 0
            prefix, boundary = _fingerprints(path, min(offset, stat.st_size))
            rotated = old and (
                stat.st_size < offset or signature != old["signature"]
                or prefix != old["prefix_hash"] or boundary != old["boundary_hash"]
                or (stat.st_size == offset and stat.st_mtime_ns != old["mtime_ns"])
            )
            if rotated:
                generation += 1
                offset = 0
                report.note("source_generation_changed")
                conn.execute("DELETE FROM usage_file_responses WHERE file_key=?", (file_key,))
            state = CodexState.restore(salt, file_key, old["state"] if old and not rotated else None)
            if rotated and agent == "codex":
                # Rotation can leave a segment without its original session
                # header. Retain only the previously verified hashed identity,
                # not counters or model attribution. A new explicit header
                # replaces it; an omitted header leaves the baseline untrusted.
                state.session_key = json.loads(old["state"]).get("session_key")
                state.untrusted_baseline = True
            state.seen_responses = {row[0] for row in conn.execute(
                "SELECT call_key FROM usage_file_responses WHERE file_key=? AND generation=?", (file_key, generation))}
            report.files += 1
            for located in iter_jsonl(path, offset=offset, limit=stat.st_size):
                report.lines += 1
                offset = located.end
                diagnostic = located.diagnostic
                call = None
                if located.record is not None:
                    try:
                        if agent == "claude":
                            call = parse_claude(located.record, salt=salt)
                            if call:
                                call = _claude_identity(conn, call)
                                prior = _rows(conn, "SELECT * FROM usage_calls WHERE call_key=?", (call.key,))
                                if call.request_missing:
                                    state.diagnostics.append("claude_message_only_identity")
                                if prior and any(getattr(call, name) < prior[0][name] for name in TOKEN_FIELDS):
                                    state.diagnostics.append("decreasing_claude_revision")
                                if prior and call.model != prior[0]["model"]:
                                    state.diagnostics.append("conflicting_claude_model_revision")
                                if not call.pricing_complete:
                                    state.diagnostics.append("unknown_claude_cache_ttl")
                        else:
                            call = parse_codex(located.record, state)
                            for snapshot_key, response_key, vector in state.snapshot_adjustments:
                                _reconcile_snapshot(conn, snapshot_key, response_key, vector, prices)
                            state.snapshot_adjustments.clear()
                        if call:
                            report.calls_updated += int(_store_call(conn, call, tz, prices))
                            if agent == "codex" and call.kind == "response":
                                conn.execute("INSERT OR IGNORE INTO usage_file_responses VALUES (?, ?, ?)",
                                             (file_key, generation, call.key))
                    except UsageDataError as error:
                        diagnostic = str(error)
                codes = ([diagnostic] if diagnostic else []) + state.diagnostics
                state.diagnostics.clear()
                for code in codes:
                    report.note(code)
                    conn.execute("""INSERT INTO usage_diagnostics VALUES (?, ?, ?, 1)
                        ON CONFLICT(file_key, generation, code) DO UPDATE SET count=count+1""",
                                 (file_key, generation, code))
            final_stat = path.stat()
            final_signature = _identity(salt, "file-stat", final_stat.st_dev, final_stat.st_ino,
                                        getattr(final_stat, "st_birthtime_ns", None))
            if final_stat.st_size < stat.st_size or final_signature != signature:
                raise UsageDataError("source_changed_during_scan")
            prefix, boundary = _fingerprints(path, offset)
            conn.execute("INSERT OR REPLACE INTO usage_files VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (file_key, agent, generation, offset, signature, prefix, boundary,
                          stat.st_mtime_ns, state.dump()))
        # A no-op rerun must not hide an earlier structural accounting gap.
        report.incomplete = report.incomplete or conn.execute(
            "SELECT 1 FROM usage_diagnostics LIMIT 1").fetchone() is not None
        conn.execute("RELEASE SAVEPOINT usage_scan")
    except BaseException:
        conn.execute("ROLLBACK TO SAVEPOINT usage_scan")
        conn.execute("RELEASE SAVEPOINT usage_scan")
        raise
    return report


def reprice_usage(conn: sqlite3.Connection, prices: PriceTable):
    """Explicit local repricing, atomic with the aggregate adjustment."""
    conn.execute("SAVEPOINT usage_reprice")
    try:
        for row in _rows(conn, "SELECT * FROM usage_calls"):
            call = UsageCall(row["call_key"], row["agent"], _timestamp(row["timestamp"]), row["model"],
                             *(row[name] for name in TOKEN_FIELDS), row["cache_write_5m_tokens"],
                             row["cache_write_1h_tokens"], kind=row["kind"],
                             pricing_complete=row["kind"] != "snapshot")
            cost = estimate_api_equivalent_cost(call, prices)
            _adjust_bucket(conn, row, -1)
            row["estimated_cost_usd"] = None if cost is None else format(cost, "f")
            row["price_version"] = prices.table_version
            conn.execute("UPDATE usage_calls SET estimated_cost_usd=?, price_version=? WHERE call_key=?",
                         (row["estimated_cost_usd"], row["price_version"], row["call_key"]))
            _adjust_bucket(conn, row, 1)
        conn.execute("RELEASE SAVEPOINT usage_reprice")
    except BaseException:
        conn.execute("ROLLBACK TO SAVEPOINT usage_reprice")
        conn.execute("RELEASE SAVEPOINT usage_reprice")
        raise


def read_usage(conn: sqlite3.Connection) -> list[PublicUsage]:
    return [PublicUsage(row["date"], row["agent"], row["model_family"],
                        *(row[name] for name in TOKEN_FIELDS),
                        None if row["unknown_cost_calls"] else Decimal(row["known_cost_usd"]))
            for row in _rows(conn, "SELECT * FROM usage_aggregates ORDER BY date, agent, model_family")]


def aggregate_usage(calls: Iterable[UsageCall], *, tz: tzinfo = timezone.utc,
                    prices: PriceTable | None = None) -> list[PublicUsage]:
    """Aggregate already-deduplicated calls; the scanner owns identity policy."""
    prices = load_prices() if prices is None else prices
    buckets = defaultdict(list)
    for call in calls:
        buckets[(call.timestamp.astimezone(tz).date().isoformat(), call.agent, call.model_family)].append(call)
    result = []
    for key, members in sorted(buckets.items()):
        tokens = [sum(getattr(call, name) for call in members) for name in TOKEN_FIELDS]
        costs = [estimate_api_equivalent_cost(call, prices) for call in members]
        with localcontext() as context:
            context.prec = 80
            cost = None if any(value is None for value in costs) else sum(costs, Decimal(0))
        result.append(PublicUsage(*key, *tokens, cost))
    return result


def export_usage(records: Iterable[PublicUsage | Mapping]) -> bytes:
    """Build the wire projection from its exact allowlist; never redact a raw row."""
    output = []
    for record in records:
        def get(name, record=record):
            return record[name] if isinstance(record, Mapping) else getattr(record, name)
        date, agent, family = get("date"), get("agent"), get("model_family")
        try:
            valid_date = isinstance(date, str) and datetime.strptime(date, "%Y-%m-%d").date().isoformat() == date
        except ValueError:
            valid_date = False
        if not valid_date or agent not in AGENTS or family not in MODEL_FAMILIES:
            raise ValueError("invalid_public_usage_enum")
        tokens = [_count(get(name)) for name in TOKEN_FIELDS]
        raw_cost = get("estimated_cost_usd")
        cost = None
        if raw_cost is not None:
            try:
                value = Decimal(raw_cost)
                if not value.is_finite() or value < 0:
                    raise ValueError
                cost = format(value, "f")
            except (InvalidOperation, TypeError, ValueError):
                raise ValueError("invalid_public_usage_cost") from None
        output.append(dict(zip(PUBLIC_FIELDS, (date, agent, family, *tokens, cost), strict=True)))
    return json.dumps(output, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
