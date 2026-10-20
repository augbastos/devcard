"""Synthetic usage, transaction and byte-level privacy regression tests."""

from dataclasses import replace
from contextlib import closing
from datetime import timedelta, timezone
from decimal import Decimal, localcontext
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

import devcard_usage as usage


FIXTURES = Path(__file__).parent / "fixtures" / "usage"
SALT = b"synthetic-local-test-salt"


def claude(message="message-one", request="request-one", *, timestamp="2026-10-13T12:00:00Z",
           model="claude-sonnet-4-5", normal=100, output=20, read=0, write=0, ttl=None):
    record = {
        "type": "assistant", "timestamp": timestamp,
        "message": {"id": message, "model": model, "usage": {
            "input_tokens": normal, "output_tokens": output,
            "cache_read_input_tokens": read, "cache_creation_input_tokens": write,
        }},
    }
    if request is not None:
        record["requestId"] = request
    if ttl is not None:
        record["message"]["usage"]["cache_creation"] = {
            "ephemeral_5m_input_tokens": ttl[0], "ephemeral_1h_input_tokens": ttl[1],
        }
    return record


def tokens(normal=100, output=10, read=20, write=0, reasoning=0):
    return {"input_tokens": normal + read + write, "output_tokens": output,
            "cached_input_tokens": read, "cache_write_input_tokens": write,
            "reasoning_output_tokens": reasoning, "total_tokens": normal + read + write + output}


def snapshot(vector, *, last=None, timestamp="2026-10-13T12:00:00Z"):
    return {"type": "event_msg", "timestamp": timestamp, "payload": {
        "type": "token_count", "info": {"total_token_usage": vector, "last_token_usage": last},
    }}


def response(identity="response-one", *, vector=None, timestamp="2026-10-13T12:00:00Z"):
    return {"type": "token_usage_record", "timestamp": timestamp,
            "payload": {"response_id": identity, "usage": tokens() if vector is None else vector}}


def context(model="gpt-5-codex"):
    return {"type": "turn_context", "payload": {"model": model}}


def session(identity="session-one"):
    return {"type": "session_meta", "payload": {"id": identity}}


def jsonl(records):
    return b"".join(json.dumps(record).encode("utf-8") + b"\n" for record in records)


def total(records, name):
    return sum(getattr(record, name) for record in records)


class ParserAndPricingTests(unittest.TestCase):
    def setUp(self):
        self.prices = usage.load_prices()

    def test_current_model_ids_use_exact_family_spellings_without_fabricated_prices(self):
        families = {
            "claude-opus": ("claude-opus-5", "claude-opus-5-5", "claude-opus-4-8"),
            "claude-sonnet": ("claude-sonnet-5", "claude-sonnet-5-5"),
            "claude-haiku": ("claude-haiku-5-5",),
            "gpt": ("gpt-6-astra", "gpt-6.1-sol", "gpt-6-sol", "gpt-5.6-sol", "gpt-5.6-terra",
                    "gpt-6-luna", "gpt-5.6-luna"),
        }
        for family, models in families.items():
            for model in models:
                with self.subTest(model=model):
                    call = usage.parse_claude(claude(model=model), salt=SALT)
                    self.assertEqual(call.model, model)
                    self.assertEqual(call.model_family, family)
                    self.assertIsNone(usage.estimate_api_equivalent_cost(call, self.prices))
                    state = usage.CodexState(SALT)
                    usage.parse_codex(context(model), state)
                    self.assertEqual(usage.parse_codex(response(), state).model_family, family)

    def test_fable_and_free_form_model_suffixes_remain_unknown(self):
        for model in ("claude-fable-5", "claude-fable-5-1", "claude-opus-5-private-model-sentinel",
                      "gpt-6.1-sol-private-model-sentinel", "GPT-6.1-sol", " gpt-6.1-sol"):
            with self.subTest(model=model):
                call = usage.parse_claude(claude(model=model), salt=SALT)
                self.assertIsNone(call.model)
                self.assertEqual(call.model_family, "unknown")
        self.assertEqual(usage.MODEL_FAMILIES,
                         frozenset({"claude-opus", "claude-sonnet", "claude-haiku", "gpt", "o", "unknown"}))

    def test_claude_only_assistants_and_disjoint_categories(self):
        record = claude(normal=100, output=20, read=70, write=30, ttl=(20, 10))
        call = usage.parse_claude(record, salt=SALT)
        self.assertEqual(tuple(getattr(call, name) for name in usage.TOKEN_FIELDS), (100, 20, 70, 30))
        self.assertEqual((call.cache_write_5m_tokens, call.cache_write_1h_tokens), (20, 10))
        record["type"] = "user"
        self.assertIsNone(usage.parse_claude(record, salt=SALT))

    def test_tuple_encoding_and_salt_separate_identities(self):
        first = usage.parse_claude(claude("a,b", "c"), salt=SALT)
        second = usage.parse_claude(claude("a", "b,c"), salt=SALT)
        third = usage.parse_claude(claude("a,b", "c"), salt=b"different-salt")
        self.assertNotEqual(first.key, second.key)
        self.assertNotEqual(first.key, third.key)
        self.assertNotIn("a,b", first.key)

    def test_missing_identity_is_structural_and_positive_usage_incomplete(self):
        with self.assertRaisesRegex(usage.UsageDataError, "missing_claude_identity"):
            usage.parse_claude(claude(None, None), salt=SALT)
        self.assertIsNone(usage.parse_claude(claude(None, None, normal=0, output=0), salt=SALT))

    def test_invalid_tokens_and_timestamps_do_not_echo_source(self):
        for invalid in (-1, True, 1.5, "private-token-sentinel", 2**63):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(usage.UsageDataError, "invalid_token_count"):
                usage.parse_claude(claude(normal=invalid), salt=SALT)
        for stamp in (None, "private-date-sentinel", "2026-10-13T12:00:00"):
            with self.subTest(stamp=stamp), self.assertRaisesRegex(usage.UsageDataError, "invalid_timestamp"):
                usage.parse_claude(claude(timestamp=stamp), salt=SALT)

    def test_design_decimal_cost_and_alias(self):
        record = claude(normal=1000, output=1000, read=5000, write=3500, ttl=(2000, 1500))
        call = usage.parse_claude(record, salt=SALT)
        with localcontext() as decimal_context:
            decimal_context.prec = 4
            self.assertEqual(usage.estimate_api_equivalent_cost(call, self.prices), Decimal("0.036"))
        alias = replace(call, model="claude-sonnet-4-5-20250929")
        self.assertEqual(usage.estimate_api_equivalent_cost(alias, self.prices), Decimal("0.036"))

    def test_unknown_model_or_needed_rate_never_zero(self):
        for model in ("gpt-5-codex", "private-model-sentinel"):
            call = usage.parse_claude(claude(model=model, normal=0, output=0), salt=SALT)
            self.assertIsNone(usage.estimate_api_equivalent_cost(call, self.prices))
        call = usage.parse_claude(claude(), salt=SALT)
        prices = usage.PriceTable("synthetic", {call.model: {"rates_per_million": {"input": "3"}}}, {})
        self.assertIsNone(usage.estimate_api_equivalent_cost(call, prices))

    def test_unknown_ttl_does_not_invent_cache_multiplier(self):
        for ttl in (None, (5, 5), (20, None)):
            call = usage.parse_claude(claude(write=20, ttl=ttl), salt=SALT)
            self.assertFalse(call.pricing_complete)
            self.assertIsNone(usage.estimate_api_equivalent_cost(call, self.prices))
            self.assertEqual(call.cache_write_tokens, 20)
        inconsistent_zero = usage.parse_claude(claude(write=0, ttl=(20, 0)), salt=SALT)
        self.assertFalse(inconsistent_zero.pricing_complete)
        self.assertIsNone(usage.estimate_api_equivalent_cost(inconsistent_zero, self.prices))

    def test_context_tier_per_call_and_unverified_high_context(self):
        call = usage.parse_claude(claude(normal=100, output=0, read=70, write=30, ttl=(30, 0)), salt=SALT)
        rates = {"input": "1", "output": "1", "cache_read": "1", "cache_write_5m": "1"}
        high = dict.fromkeys(rates, "2")
        prices = usage.PriceTable("synthetic-tiers", {call.model: {"context_tiers": [
            {"max_input_tokens": 150, "rates_per_million": rates},
            {"max_input_tokens": 250, "rates_per_million": high},
        ]}}, {})
        self.assertEqual(usage.estimate_api_equivalent_cost(call, prices), Decimal("0.0004"))
        smaller = replace(call, input_tokens=50)
        aggregate = usage.aggregate_usage([call, smaller], prices=prices)
        self.assertEqual(aggregate[0].estimated_cost_usd, Decimal("0.00055"))
        self.assertIsNone(usage.estimate_api_equivalent_cost(replace(call, input_tokens=1000), prices))
        self.assertIsNone(usage.estimate_api_equivalent_cost(replace(call, input_tokens=200001), self.prices))

    def test_codex_reasoning_in_output_and_write_disjoint(self):
        state = usage.CodexState(SALT)
        usage.parse_codex(context(), state)
        call = usage.parse_codex(response(vector=tokens(100, 20, 30, 10, 15)), state)
        self.assertEqual(tuple(getattr(call, name) for name in usage.TOKEN_FIELDS), (100, 20, 30, 10))
        synthetic = usage.PriceTable("synthetic-only", {"gpt-5-codex": {"rates_per_million": {
            "input": "1", "output": "2", "cache_read": "0.1", "cache_write": "3",
        }}}, {})
        self.assertEqual(usage.estimate_api_equivalent_cost(call, synthetic), Decimal("0.000173"))

    def test_codex_inconsistent_cache_or_reasoning_rejected(self):
        for vector in ({"input_tokens": 5, "cached_input_tokens": 6},
                       {"output_tokens": 5, "reasoning_output_tokens": 6},
                       {"input_tokens": 5, "output_tokens": 2, "total_tokens": 99}):
            with self.subTest(vector=vector), self.assertRaises(usage.UsageDataError):
                usage.parse_codex(response(vector=vector), usage.CodexState(SALT))

    def test_snapshot_flat_price_is_linear_but_tiered_price_unavailable(self):
        state = usage.CodexState(SALT)
        usage.parse_codex(context(), state)
        call = usage.parse_codex(snapshot(tokens(), last=tokens()), state)
        rates = {"input": "1", "output": "2", "cache_read": "0.1"}
        flat = usage.PriceTable("synthetic-flat", {call.model: {"rates_per_million": rates}}, {})
        self.assertEqual(usage.estimate_api_equivalent_cost(call, flat), Decimal("0.000122"))
        tiered = usage.PriceTable("synthetic-tiered", {call.model: {"context_tiers": [
            {"max_input_tokens": None, "rates_per_million": rates},
        ]}}, {})
        self.assertIsNone(usage.estimate_api_equivalent_cost(call, tiered))

    def test_bundled_table_metadata_and_only_design_rates(self):
        data = json.loads(usage.PRICES_PATH.read_text(encoding="utf-8"))
        for field in ("schema_version", "table_version", "verified_at", "currency", "source", "calculation_version"):
            self.assertIn(field, data)
        self.assertEqual([name for name, entry in data["models"].items() if entry["rates_per_million"]],
                         ["claude-sonnet-4-5"])
        self.assertEqual(data["models"]["claude-sonnet-4-5"]["rates_per_million"]["cache_write_1h"], "6")


class ScanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="devcard-usage-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.conn = sqlite3.connect(":memory:")
        self.addCleanup(self.conn.close)

    def write(self, name, records, *, append=False):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("ab" if append else "wb") as destination:
            destination.write(jsonl(records))
        return path

    def scan(self, paths, agent="claude", **kwargs):
        return usage.scan_usage(paths, self.conn, agent=agent, **kwargs)

    def rows(self):
        return usage.read_usage(self.conn)

    def count_calls(self):
        return self.conn.execute("SELECT count(*) FROM usage_calls").fetchone()[0]

    def test_model_table_change_reclassifies_both_agents_across_separate_scans(self):
        claude_path = self.write("new-claude.jsonl", [claude(model="claude-opus-5-5")])
        codex_path = self.write("new-codex.jsonl", [session(), context("gpt-6.1-sol"), response()])
        unknown_path = self.write("unknown.jsonl", [claude("fable", "fable", model="claude-fable-5"),
                                  claude("free", "free", model="gpt-6.1-sol-private-model-sentinel")])
        old_models = {model: family for model, family in usage._MODELS.items()
                      if model not in ("claude-opus-5-5", "gpt-6.1-sol")}
        with mock.patch.object(usage, "_MODELS", old_models):
            self.scan([claude_path, unknown_path])
            self.scan([codex_path], "codex")
        self.assertEqual({row.model_family for row in self.rows()}, {"unknown"})
        before = [total(self.rows(), name) for name in usage.TOKEN_FIELDS]
        old_fingerprint = self.conn.execute(
            "SELECT value FROM usage_meta WHERE key='model_table_fingerprint'").fetchone()
        self.assertIsNotNone(old_fingerprint)
        claude_report = self.scan([claude_path, unknown_path])
        self.assertEqual(claude_report.lines, 3)
        self.assertEqual({row.model_family for row in self.rows() if row.agent == "claude"}, {"claude-opus", "unknown"})
        # Updating a shared fingerprint must leave the other root/agent pending.
        codex_report = self.scan([codex_path], "codex")
        self.assertEqual(codex_report.lines, 3)
        self.assertEqual({row.model_family for row in self.rows() if row.agent == "codex"}, {"gpt"})
        self.assertEqual(before, [total(self.rows(), name) for name in usage.TOKEN_FIELDS])
        self.assertEqual(self.count_calls(), 4)
        self.assertEqual({row[0] for row in self.conn.execute("SELECT generation FROM usage_files")}, {1})
        new_fingerprint = self.conn.execute(
            "SELECT value FROM usage_meta WHERE key='model_table_fingerprint'").fetchone()
        self.assertNotEqual(old_fingerprint, new_fingerprint)
        self.assertEqual(len(new_fingerprint[0]), 64)
        self.assertTrue(all(row.estimated_cost_usd is None for row in self.rows()))
        models = {row[0] for row in self.conn.execute("SELECT model FROM usage_calls")}
        self.assertEqual(models, {None, "claude-opus-5-5", "gpt-6.1-sol"})
        dump = "\n".join(self.conn.iterdump())
        self.assertNotIn("private-model-sentinel", dump)
        self.assertNotIn("claude-fable-5", dump)
        with mock.patch.object(usage, "parse_claude", side_effect=AssertionError("reparsed")), \
                mock.patch.object(usage, "parse_codex", side_effect=AssertionError("reparsed")):
            self.assertEqual(self.scan([claude_path, unknown_path]).lines, 0)
            self.assertEqual(self.scan([codex_path], "codex").lines, 0)

    def test_model_fingerprint_is_order_independent_and_unchanged_scan_is_incremental(self):
        path = self.write("unchanged.jsonl", [claude()])
        self.scan([path])
        before = self.conn.execute("SELECT generation, offset FROM usage_files").fetchall()
        reversed_models = dict(reversed(list(usage._MODELS.items())))
        with mock.patch.object(usage, "_MODELS", reversed_models), \
                mock.patch.object(usage, "parse_claude", side_effect=AssertionError("reparsed")):
            report = self.scan([path])
        self.assertEqual((report.lines, report.calls_updated), (0, 0))
        self.assertEqual(self.conn.execute("SELECT generation, offset FROM usage_files").fetchall(), before)

    def test_model_fingerprint_migration_preserves_missing_sources_and_existing_events(self):
        path = self.write("available.jsonl", [claude(model="claude-opus-5")])
        missing = self.write("missing.jsonl", [claude("missing", "missing")])
        self.conn.execute("CREATE TABLE existing_events (value INTEGER)")
        self.conn.execute("INSERT INTO existing_events VALUES (42)")
        self.scan([path, missing])
        self.conn.execute("DELETE FROM usage_meta WHERE key LIKE 'model_%'")
        self.conn.commit()
        missing.unlink()
        report = self.scan([path])
        self.assertEqual(report.lines, 1)
        self.assertEqual(self.count_calls(), 2)
        self.assertEqual(self.conn.execute("SELECT * FROM existing_events").fetchall(), [(42,)])

    def test_model_rescan_and_fingerprint_roll_back_together(self):
        path = self.write("atomic-model.jsonl", [claude(model="claude-opus-5")])
        with mock.patch.object(usage, "_MODELS", {k: v for k, v in usage._MODELS.items() if k != "claude-opus-5"}):
            self.scan([path])
        self.conn.commit()
        before = "\n".join(self.conn.iterdump())
        original = usage._store_call

        def fail_after_call(*args):
            original(*args)
            raise sqlite3.OperationalError("synthetic_model_rescan_failure")

        with mock.patch.object(usage, "_store_call", side_effect=fail_after_call), self.assertRaises(sqlite3.OperationalError):
            self.scan([path])
        self.assertEqual("\n".join(self.conn.iterdump()), before)
        self.assertEqual(self.scan([path]).lines, 1)
        self.assertEqual(self.rows()[0].model_family, "claude-opus")

    def test_model_rescan_preserves_codex_snapshot_reconciliation(self):
        path = self.write("reconciled-model.jsonl", [session(), context("gpt-6.1-sol"),
                          snapshot(tokens(), last=tokens()),
                          {**response(), "payload": {**response()["payload"], "thread_token_usage": tokens()}}])
        with mock.patch.object(usage, "_MODELS", {k: v for k, v in usage._MODELS.items() if k != "gpt-6.1-sol"}):
            self.scan([path], "codex")
        before = [total(self.rows(), name) for name in usage.TOKEN_FIELDS]
        self.assertEqual(self.count_calls(), 1)
        self.assertEqual(self.scan([path], "codex").lines, 4)
        self.assertEqual(self.count_calls(), 1)
        self.assertEqual(self.rows()[0].model_family, "gpt")
        self.assertEqual([total(self.rows(), name) for name in usage.TOKEN_FIELDS], before)

    def test_model_rescan_reclassifies_verified_headerless_codex_baseline(self):
        path = self.write("headerless-model.jsonl", [context("gpt-6.1-sol"), snapshot(tokens(), last=tokens())])
        with mock.patch.object(usage, "_MODELS", {k: v for k, v in usage._MODELS.items() if k != "gpt-6.1-sol"}):
            self.scan([path], "codex")
        before = [total(self.rows(), name) for name in usage.TOKEN_FIELDS]
        self.scan([path], "codex")
        self.assertEqual(self.rows()[0].model_family, "gpt")
        self.assertEqual([total(self.rows(), name) for name in usage.TOKEN_FIELDS], before)

    def test_model_rescan_never_counts_previously_untrusted_rotated_baseline(self):
        records = [session(), context("gpt-6.1-sol"), snapshot(tokens(0, 0, 0)),
                   snapshot(tokens()), snapshot(tokens(150, 20, 30))]
        path = self.write("rotated-model.jsonl", records)
        with mock.patch.object(usage, "_MODELS", {k: v for k, v in usage._MODELS.items() if k != "gpt-6.1-sol"}):
            self.scan([path], "codex")
            self.write("rotated-model.jsonl", [context("gpt-6.1-sol"), snapshot(tokens(50, 5, 5), last=tokens(50, 5, 5))])
            self.scan([path], "codex")
        before = [total(self.rows(), name) for name in usage.TOKEN_FIELDS]
        self.scan([path], "codex")
        self.assertEqual([total(self.rows(), name) for name in usage.TOKEN_FIELDS], before)
        self.assertEqual(self.count_calls(), 2)

    def test_three_revisions_replace_full_vector_and_keep_first_date(self):
        path = self.root / "private-file-sentinel.jsonl"
        path.write_bytes((FIXTURES / "claude-revisions.jsonl").read_bytes())
        report = self.scan([path])
        self.assertEqual(report.calls_updated, 3)
        self.assertEqual(self.count_calls(), 1)
        self.assertEqual(self.rows()[0].date, "2026-10-13")
        self.assertEqual(tuple(getattr(self.rows()[0], field) for field in usage.TOKEN_FIELDS), (200, 30, 100, 40))
        expected = (Decimal(200) * 3 + Decimal(30) * 15 + Decimal(100) * Decimal("0.3")
                    + Decimal(30) * Decimal("3.75") + Decimal(10) * 6) / 1_000_000
        self.assertEqual(self.rows()[0].estimated_cost_usd, expected)

    def test_copy_and_subagent_dedup_globally_distinct_request_counted(self):
        first = self.write("main.jsonl", [claude()])
        copied = self.write("session/subagents/child.jsonl", [claude()])
        separate = self.write("separate.jsonl", [claude(request="request-two")])
        paths = usage.discover_usage_paths(self.root, agent="claude")
        self.assertEqual(set(paths), {first, copied, separate})
        self.scan(paths)
        self.assertEqual(self.count_calls(), 2)
        self.assertEqual(total(self.rows(), "input_tokens"), 200)

    def test_missing_request_validated_then_promoted_without_double_count(self):
        path = self.write("fallback.jsonl", [claude(request=None)])
        self.scan([path])
        self.write("fallback.jsonl", [claude(timestamp="2026-10-14T00:00:00Z", normal=200)], append=True)
        self.scan([path])
        self.assertEqual(self.count_calls(), 1)
        self.assertEqual(self.rows()[0].input_tokens, 200)
        self.assertEqual(self.rows()[0].date, "2026-10-13")
        self.write("fallback.jsonl", [claude(request=None, normal=300, timestamp="2026-10-14T00:01:00Z")], append=True)
        self.scan([path])
        self.assertEqual(self.rows()[0].input_tokens, 300)

    def test_ambiguous_request_and_missing_identity_report_incomplete(self):
        path = self.write("ambiguous.jsonl", [claude(), claude(request="two"), claude(request=None), claude(None, None)])
        report = self.scan([path])
        self.assertTrue(report.incomplete)
        self.assertEqual(report.diagnostics["ambiguous_claude_request"], 1)
        self.assertEqual(report.diagnostics["missing_claude_identity"], 1)
        self.assertEqual(self.count_calls(), 2)
        self.assertTrue(self.scan([path]).incomplete)

    def test_decreasing_revision_replaces_without_independent_maxima(self):
        path = self.write("decreasing.jsonl", [claude(normal=200, output=30, read=10),
            claude(normal=100, output=40, read=20, timestamp="2026-10-13T12:01:00Z")])
        report = self.scan([path])
        self.assertIn("decreasing_claude_revision", report.diagnostics)
        self.assertEqual(tuple(getattr(self.rows()[0], field) for field in usage.TOKEN_FIELDS), (100, 40, 20, 0))

    def test_repeated_snapshot_and_info_null_never_sum_snapshots(self):
        vector = tokens()
        path = self.write("legacy.jsonl", [context(), snapshot(vector, last=vector),
            snapshot(vector, last=vector),
            {"type": "event_msg", "payload": {"type": "token_count", "info": None}},
            snapshot(tokens(150, 30, 30), last=tokens(50, 20, 10))])
        report = self.scan([path], "codex")
        self.assertFalse(report.incomplete)
        self.assertEqual(self.count_calls(), 2)
        self.assertEqual(tuple(total(self.rows(), field) for field in usage.TOKEN_FIELDS), (150, 30, 30, 0))

    def test_unverified_first_snapshot_not_assigned_to_first_day(self):
        path = self.write("history.jsonl", [context(), snapshot(tokens(1000), last=tokens(100)),
                                          snapshot(tokens(1100, 20, 40), last=tokens(100, 10, 20))])
        report = self.scan([path], "codex")
        self.assertIn("unverified_codex_baseline", report.diagnostics)
        self.assertEqual(tuple(total(self.rows(), field) for field in usage.TOKEN_FIELDS), (100, 10, 20, 0))

    def test_reset_starts_new_baseline_not_a_new_snapshot_sum(self):
        initial = tokens(100, 30, 20)
        path = self.write("reset.jsonl", [context(), snapshot(initial, last=initial),
            snapshot(tokens(5, 2, 0)), snapshot(tokens(25, 5, 5))])
        report = self.scan([path], "codex")
        self.assertIn("codex_counter_reset", report.diagnostics)
        self.assertEqual(tuple(total(self.rows(), field) for field in usage.TOKEN_FIELDS), (120, 33, 25, 0))

    def test_fork_history_not_charged_as_first_new_call(self):
        meta = session("fork-session")
        meta["payload"]["forked_from_id"] = "private-parent-session-sentinel"
        path = self.write("fork.jsonl", [meta, context(), snapshot(tokens(1000), last=tokens(1000)),
            snapshot(tokens(1100, 20, 40))])
        report = self.scan([path], "codex")
        self.assertIn("fork_history_requires_baseline", report.diagnostics)
        self.assertIn("unverified_codex_baseline", report.diagnostics)
        self.assertEqual(total(self.rows(), "input_tokens"), 100)
        self.assertNotIn("private-parent-session-sentinel", "\n".join(self.conn.iterdump()))

    def test_session_change_in_one_file_restarts_baseline(self):
        path = self.write("session-change.jsonl", [session("one"), context(),
            snapshot(tokens(), last=tokens()), session("two"), context("gpt-5.2-codex"),
            snapshot(tokens(), last=tokens())])
        report = self.scan([path], "codex")
        self.assertIn("codex_session_changed", report.diagnostics)
        self.assertEqual(total(self.rows(), "input_tokens"), 200)
        self.assertEqual(self.count_calls(), 2)

    def test_legacy_midnight_and_model_change_attribute_each_delta(self):
        path = self.write("midnight.jsonl", [context(),
            snapshot(tokens(), last=tokens(), timestamp="2026-10-13T23:59:00Z"),
            context("gpt-5.2-codex"), snapshot(tokens(150, 30, 40), timestamp="2026-10-14T00:01:00Z")])
        self.scan([path], "codex")
        calls = self.conn.execute("SELECT date, model, input_tokens FROM usage_calls ORDER BY date").fetchall()
        self.assertEqual(calls, [("2026-10-13", "gpt-5-codex", 100), ("2026-10-14", "gpt-5.2-codex", 50)])

    def test_response_format_mixed_with_legacy_prefix(self):
        path = self.root / "mixed.jsonl"
        path.write_bytes((FIXTURES / "codex-mixed.jsonl").read_bytes())
        self.scan([path], "codex")
        self.assertEqual(self.count_calls(), 2)
        self.assertEqual(tuple(total(self.rows(), field) for field in usage.TOKEN_FIELDS), (115, 30, 30, 5))
        self.assertEqual([row.date for row in self.rows()], ["2026-10-13", "2026-10-14"])

    def test_responses_globally_dedup_and_snapshot_lag_allowed(self):
        records = [context(), response(), snapshot(tokens()), response("response-two", vector=tokens(50, 5, 5))]
        first = self.write("first.jsonl", records)
        copied = self.write("copy.jsonl", records)
        self.scan([first, copied], "codex")
        self.assertEqual(self.count_calls(), 2)
        self.assertEqual(tuple(total(self.rows(), field) for field in usage.TOKEN_FIELDS), (150, 15, 25, 0))
        self.write("first.jsonl", [snapshot(tokens(150, 15, 25))], append=True)
        self.scan([first], "codex")
        self.assertEqual(self.count_calls(), 2)

    def test_same_response_twice_in_file_does_not_corrupt_coverage(self):
        path = self.write("replay.jsonl", [context(), response(), response(), snapshot(tokens()),
            response("two", vector=tokens(50, 5, 5)), snapshot(tokens(150, 15, 25))])
        self.scan([path], "codex")
        self.assertEqual(self.count_calls(), 2)
        self.assertEqual(total(self.rows(), "input_tokens"), 150)

    def test_partial_response_coverage_reconciles_missing_delta(self):
        path = self.write("partial-coverage.jsonl", [context(), snapshot(tokens(0, 0, 0)), response(),
            snapshot(tokens(150, 30, 30))])
        report = self.scan([path], "codex")
        self.assertIn("partial_codex_response_coverage", report.diagnostics)
        self.assertEqual(tuple(total(self.rows(), field) for field in usage.TOKEN_FIELDS), (150, 30, 30, 0))

    def test_snapshot_behind_response_does_not_drop_pending_coverage(self):
        path = self.write("lagging.jsonl", [context(), snapshot(tokens(0, 0, 0)),
            response(vector=tokens(200, 20, 40)), snapshot(tokens(100, 10, 20)),
            snapshot(tokens(200, 20, 40))])
        self.scan([path], "codex")
        self.assertEqual(self.count_calls(), 1)
        self.assertEqual(total(self.rows(), "input_tokens"), 200)

    def test_unverified_initial_snapshot_preserves_ahead_response_coverage(self):
        path = self.write("initial-lag.jsonl", [context(), response(vector=tokens(200, 20, 40)),
            snapshot(tokens(150, 15, 30), last=tokens(10, 1, 2)),
            snapshot(tokens(200, 20, 40))])
        report = self.scan([path], "codex")
        self.assertIn("unverified_codex_baseline", report.diagnostics)
        self.assertEqual(self.count_calls(), 1)
        self.assertEqual(total(self.rows(), "input_tokens"), 200)

    def test_verifiable_late_response_replaces_snapshot_without_double_count(self):
        record = response()
        record["payload"]["thread_token_usage"] = tokens()
        records = [session(), context(), snapshot(tokens(), last=tokens()), record]
        path = self.write("late-response.jsonl", records[:3])
        self.scan([path], "codex")
        self.write("late-response.jsonl", records[3:], append=True)
        self.scan([path], "codex")
        self.assertEqual(self.count_calls(), 1)
        self.assertEqual(self.conn.execute("SELECT kind FROM usage_calls").fetchone()[0], "response")
        self.assertEqual(total(self.rows(), "input_tokens"), 100)
        copied = self.write("late-response-copy.jsonl", records)
        self.scan([copied], "codex")
        self.assertEqual(self.count_calls(), 1)
        self.assertEqual(total(self.rows(), "input_tokens"), 100)

    def test_unverifiable_older_response_overlap_diagnosed_not_counted_twice(self):
        record = response()
        record["payload"]["thread_token_usage"] = tokens()
        path = self.write("older-response.jsonl", [context(), snapshot(tokens(), last=tokens()),
            snapshot(tokens(200, 20, 40)), record])
        report = self.scan([path], "codex")
        self.assertIn("unreconciled_codex_response_overlap", report.diagnostics)
        self.assertEqual(total(self.rows(), "input_tokens"), 200)

    def test_partial_late_response_reprices_remaining_flat_snapshot(self):
        prices = usage.PriceTable("synthetic-flat", {"gpt-5-codex": {"rates_per_million": {
            "input": "1", "output": "2", "cache_read": "0.1",
        }}}, {})
        late = response(vector=tokens(50, 5, 10))
        late["payload"]["thread_token_usage"] = tokens()
        path = self.write("partial-late.jsonl", [session(), context(), snapshot(tokens(), last=tokens()), late])
        self.scan([path], "codex", prices=prices)
        self.assertEqual(self.count_calls(), 2)
        self.assertEqual(total(self.rows(), "input_tokens"), 100)
        self.assertEqual(self.rows()[0].estimated_cost_usd, Decimal("0.000122"))

    def test_cursor_append_and_state_persist_across_connections(self):
        db = self.root / "local.db"
        path = self.write("resume.jsonl", [context(), response(), snapshot(tokens())])
        with closing(sqlite3.connect(db)) as conn:
            usage.scan_usage([path], conn, agent="codex")
        self.write("resume.jsonl", [response("two", vector=tokens(50, 5, 5)), snapshot(tokens(150, 15, 25))], append=True)
        with closing(sqlite3.connect(db)) as conn:
            report = usage.scan_usage([path], conn, agent="codex")
            self.assertEqual(report.lines, 2)
            self.assertEqual(total(usage.read_usage(conn), "input_tokens"), 150)

    def test_rerun_does_not_change_totals_or_read_complete_lines(self):
        path = self.write("idempotent.jsonl", [claude()])
        self.scan([path])
        first = usage.export_usage(self.rows())
        second = self.scan([path])
        self.assertEqual(second.lines, 0)
        self.assertEqual(second.calls_updated, 0)
        self.assertEqual(usage.export_usage(self.rows()), first)

    def test_incomplete_line_is_retried_without_persisting_tail(self):
        first = claude()
        second = claude("two", "two")
        data = jsonl([second])
        path = self.write("unfinished.jsonl", [first])
        complete_offset = path.stat().st_size
        with path.open("ab") as destination:
            destination.write(data[:-3])
        self.scan([path])
        self.assertEqual(self.conn.execute("SELECT offset FROM usage_files").fetchone()[0], complete_offset)
        self.assertEqual(self.count_calls(), 1)
        with path.open("ab") as destination:
            destination.write(data[-3:])
        self.scan([path])
        self.assertEqual(self.count_calls(), 2)

    def test_truncation_reprocesses_generation_idempotently(self):
        path = self.write("truncated.jsonl", [claude(), claude("two", "two")])
        self.scan([path])
        self.write("truncated.jsonl", [claude()])
        report = self.scan([path])
        self.assertIn("source_generation_changed", report.diagnostics)
        self.assertEqual(self.conn.execute("SELECT generation FROM usage_files").fetchone()[0], 1)
        self.assertEqual(self.count_calls(), 2)
        self.write("truncated.jsonl", [claude("two", "two")], append=True)
        self.scan([path])
        self.assertEqual(self.count_calls(), 2)

    def test_rotation_detects_replaced_file_with_same_size(self):
        path = self.write("rotated.jsonl", [claude()])
        self.scan([path])
        replacement = self.write("replacement.jsonl", [claude("message-two", "request-two")])
        replacement.replace(path)
        report = self.scan([path])
        self.assertIn("source_generation_changed", report.diagnostics)
        self.assertEqual(self.count_calls(), 2)

    def test_legacy_copy_and_truncation_do_not_duplicate_transitions(self):
        records = [session(), context(), snapshot(tokens(), last=tokens()), snapshot(tokens(150, 20, 30))]
        path = self.write("legacy.jsonl", records)
        copy = self.write("legacy-copy.jsonl", records)
        self.scan([path, copy], "codex")
        self.assertEqual(total(self.rows(), "input_tokens"), 150)
        self.write("legacy.jsonl", records[:3])
        self.scan([path], "codex")
        self.write("legacy.jsonl", records[3:], append=True)
        self.scan([path], "codex")
        self.assertEqual(total(self.rows(), "input_tokens"), 150)

    def test_truncated_codex_segment_without_header_keeps_hashed_identity(self):
        records = [session(), context(), snapshot(tokens(0, 0, 0)),
                   snapshot(tokens()), snapshot(tokens(150, 20, 30))]
        path = self.write("headerless-segment.jsonl", records)
        self.scan([path], "codex")
        self.write("headerless-segment.jsonl", [context(), snapshot(tokens(), last=tokens()),
            snapshot(tokens(150, 20, 30), last=tokens(50, 10, 10))])
        report = self.scan([path], "codex")
        self.assertIn("unverified_codex_baseline", report.diagnostics)
        self.assertEqual(total(self.rows(), "input_tokens"), 150)
        self.assertEqual(self.count_calls(), 2)

    def test_cursor_revision_and_aggregate_roll_back_together(self):
        path = self.write("crash.jsonl", [claude()])
        self.scan([path])
        self.conn.commit()
        offset = self.conn.execute("SELECT offset FROM usage_files").fetchone()[0]
        before = usage.export_usage(self.rows())
        self.write("crash.jsonl", [claude(normal=500, timestamp="2026-10-13T13:00:00Z")], append=True)
        adjust = usage._adjust_bucket
        def fail_after_adjust(conn, row, sign):
            adjust(conn, row, sign)
            if sign == 1:
                raise sqlite3.OperationalError("synthetic_crash")
        with mock.patch.object(usage, "_adjust_bucket", side_effect=fail_after_adjust), self.assertRaises(sqlite3.OperationalError):
            self.scan([path])
        self.assertEqual(self.conn.execute("SELECT offset FROM usage_files").fetchone()[0], offset)
        self.assertEqual(usage.export_usage(self.rows()), before)
        self.scan([path])
        self.assertEqual(self.rows()[0].input_tokens, 500)

    def test_truncation_during_scan_rolls_back_cursor_and_calls(self):
        path = self.write("active-truncation.jsonl", [claude(), claude("two", "two")])
        self.scan([path])
        offset = self.conn.execute("SELECT offset FROM usage_files").fetchone()[0]
        before = usage.export_usage(self.rows())
        self.write("active-truncation.jsonl", [claude("three", "three")], append=True)
        original = usage.iter_jsonl
        def truncate_after_read(source, **kwargs):
            yield from original(source, **kwargs)
            source.write_bytes(b"")
        with mock.patch.object(usage, "iter_jsonl", side_effect=truncate_after_read):
            with self.assertRaisesRegex(usage.UsageDataError, "source_changed_during_scan"):
                self.scan([path])
        self.assertEqual(self.conn.execute("SELECT offset FROM usage_files").fetchone()[0], offset)
        self.assertEqual(usage.export_usage(self.rows()), before)

    def test_schema_and_scan_preserve_caller_transaction(self):
        self.conn.execute("CREATE TABLE existing_events (value INTEGER)")
        self.conn.execute("INSERT INTO existing_events VALUES (42)")
        path = self.write("transaction.jsonl", [claude()])
        self.scan([path])
        self.assertTrue(self.conn.in_transaction)
        self.conn.rollback()
        self.assertEqual(self.conn.execute("SELECT * FROM existing_events").fetchall(), [])
        self.assertEqual(self.conn.execute("SELECT name FROM sqlite_master WHERE name='usage_calls'").fetchall(), [])

    def test_file_sqlite_connection_commits_scanner_without_context_manager(self):
        path = self.write("persistent.jsonl", [claude()])
        db = self.root / "persistent.db"
        conn = sqlite3.connect(db)
        usage.scan_usage([path], conn, agent="claude")
        conn.close()
        with closing(sqlite3.connect(db)) as reopened:
            self.assertEqual(usage.read_usage(reopened)[0].input_tokens, 100)

    def test_unknown_cost_propagates_whole_bucket_and_revision_can_resolve(self):
        path = self.write("unknown-rate.jsonl", [claude(), claude("two", "two", write=20)])
        self.scan([path])
        self.assertIsNone(self.rows()[0].estimated_cost_usd)
        self.write("unknown-rate.jsonl", [claude("two", "two", write=20, ttl=(20, 0),
            timestamp="2026-10-13T13:00:00Z")], append=True)
        self.scan([path])
        self.assertIsNotNone(self.rows()[0].estimated_cost_usd)

    def test_unknown_model_not_stored_and_context_survives_restart(self):
        path = self.write("unknown-model.jsonl", [context("private-model-sentinel"), response()])
        report = self.scan([path], "codex")
        self.assertIn("unknown_codex_model", report.diagnostics)
        self.assertEqual(self.rows()[0].model_family, "unknown")
        self.assertIsNone(self.rows()[0].estimated_cost_usd)
        dump = "\n".join(self.conn.iterdump()).encode()
        self.assertNotIn(b"private-model-sentinel", dump)

    def test_timezone_explicit_uniform_and_change_rejected(self):
        path = self.write("timezone.jsonl", [claude(timestamp="2026-10-13T23:30:00Z")])
        self.scan([path], tz=timezone(timedelta(hours=2)))
        self.assertEqual(self.rows()[0].date, "2026-10-14")
        with self.assertRaisesRegex(ValueError, "usage_timezone_changed"):
            self.scan([path], tz=timezone.utc)

    def test_malformed_and_oversized_complete_lines_advance_and_report(self):
        path = self.root / "malformed.jsonl"
        path.write_bytes(b"not-json-private-sentinel\n[]\n" + jsonl([claude()]))
        report = self.scan([path])
        self.assertEqual(report.diagnostics["malformed_line"], 2)
        self.assertEqual(self.count_calls(), 1)
        with path.open("ab") as destination:
            destination.write(b"x" * 65 + b"\n")
        with mock.patch.object(usage, "MAX_LINE_BYTES", 64):
            report = self.scan([path])
        self.assertIn("oversized_line", report.diagnostics)
        self.assertEqual(self.conn.execute("SELECT offset FROM usage_files").fetchone()[0], path.stat().st_size)

    def test_no_implicit_sources_non_jsonl_never_opened(self):
        path = self.root / "secret.env"
        with mock.patch.object(Path, "open", side_effect=AssertionError("must_not_read")):
            # Pass an explicit table: even the bundled price file must not open in this test.
            report = self.scan([path], prices=usage.PriceTable("synthetic", {}, {}))
        self.assertIn("non_jsonl_source", report.diagnostics)

    def test_explicit_reprice_updates_aggregates_and_provenance(self):
        path = self.write("reprice.jsonl", [claude()])
        self.scan([path])
        original = self.rows()[0].estimated_cost_usd
        prices = usage.PriceTable("synthetic-double", {"claude-sonnet-4-5": {
            "rates_per_million": {"input": "6", "output": "30"},
        }}, {})
        usage.reprice_usage(self.conn, prices)
        self.assertEqual(self.rows()[0].estimated_cost_usd, original * 2)
        self.assertEqual(self.conn.execute("SELECT price_version FROM usage_calls").fetchone()[0], "synthetic-double")
        copied = self.write("reprice-copy.jsonl", [claude()])
        self.scan([copied])
        self.assertEqual(self.rows()[0].estimated_cost_usd, original * 2)
        self.write("reprice.jsonl", [claude(timestamp="2026-10-13T13:00:00Z")], append=True)
        self.scan([path])
        self.assertEqual(self.rows()[0].estimated_cost_usd, original * 2)
        self.assertEqual(self.conn.execute("SELECT price_version FROM usage_calls").fetchone()[0], "synthetic-double")

    def test_no_raw_identity_or_source_content_persisted_or_exported(self):
        path = self.root / "private-file-sentinel.jsonl"
        path.write_bytes((FIXTURES / "claude-revisions.jsonl").read_bytes())
        codex = self.root / "private-codex-file-sentinel.jsonl"
        codex.write_bytes((FIXTURES / "codex-mixed.jsonl").read_bytes())
        self.scan([path])
        self.scan([codex], "codex")
        wire = usage.export_usage(self.rows())
        database = "\n".join(self.conn.iterdump()).encode("utf-8")
        for sentinel in (b"private-file-sentinel", b"private-codex-file-sentinel", b"private-request-sentinel",
                         b"private-session-sentinel", b"private-path-sentinel", b"private-message-sentinel",
                         b"private-text-sentinel", b"private-codex-session-sentinel", b"private-response-sentinel"):
            self.assertNotIn(sentinel, wire)
            self.assertNotIn(sentinel, database)
        for forbidden in (b"sessionId", b"requestId", b"response_id", b"call_key", b"file_key", b"message", b"cwd"):
            self.assertNotIn(forbidden, wire)
        for record in json.loads(wire):
            self.assertEqual(set(record), set(usage.PUBLIC_FIELDS))


class ExportTests(unittest.TestCase):
    def record(self):
        return dict(zip(usage.PUBLIC_FIELDS, ("2026-10-13", "claude", "claude-sonnet", 1, 2, 3, 4, "0.036"), strict=True))

    def test_exact_allowlist_ignores_extra_private_fields_by_bytes(self):
        record = self.record()
        record.update(path="private-path-sentinel", filename="private-file-sentinel",
                      sessionId="private-session-sentinel", requestId="private-request-sentinel",
                      response_id="private-response-sentinel", message="private-text-sentinel",
                      model="private-model-sentinel")
        result = usage.export_usage([record])
        self.assertNotIn(b"private-", result)
        self.assertEqual(json.loads(result), [self.record()])

    def test_injected_enum_date_tokens_and_cost_rejected(self):
        for field, value in (("agent", "private-agent"), ("model_family", "private-family"),
                             ("date", "private-date"), ("date", "2026-1-1"),
                             ("input_tokens", -1), ("input_tokens", True),
                             ("estimated_cost_usd", "private-cost"), ("estimated_cost_usd", "NaN"),
                             ("estimated_cost_usd", "Infinity"), ("estimated_cost_usd", "-1")):
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                usage.export_usage([{**self.record(), field: value}])

    def test_none_and_zero_cost_are_distinct(self):
        result = json.loads(usage.export_usage([{**self.record(), "estimated_cost_usd": None},
            {**self.record(), "estimated_cost_usd": Decimal("0")}]))
        self.assertIsNone(result[0]["estimated_cost_usd"])
        self.assertEqual(result[1]["estimated_cost_usd"], "0")


if __name__ == "__main__":
    unittest.main()
