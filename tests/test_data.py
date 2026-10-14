"""Aggregates: what one machine publishes, and how several add up."""
import json
import os
import time
import unittest

from devcard import data
from devcard._hook import lib

from .helpers import PROJECT, TempDirTest

NOW = 1760000000  # 2025-10-09T08:53:20Z


def agg(**overrides):
    base = {"format": 1, "languages": {}, "event_types": {}, "days": {}, "bytes": 0, "events": 0,
            "first_ts": None, "repo_count": 0, "updated_at": NOW}
    return {**base, **overrides}


class AggregateTest(TempDirTest):
    def aggregate(self, events, tz="UTC"):
        conn = lib.init_db(os.path.join(self.tmp, "events.db"))
        try:
            for e in events:
                lib.insert_event(conn, {"lines_removed": 0, "bytes_added": 0, "project_key": PROJECT,
                                        "source_id": "testsource", **e})
            return data.aggregate(conn, NOW, tz=tz, repo_count=4)
        finally:
            conn.close()

    def test_rollups_match_the_worker_rules(self):
        result = self.aggregate([
            {"ts": NOW - 10, "language": "Python", "lines_added": 5, "bytes_added": 50, "event_type": "edit"},
            {"ts": NOW - 20, "language": "Python", "lines_added": 7, "bytes_added": 70, "event_type": "write"},
            {"ts": NOW - 30, "language": None, "lines_added": 0, "event_type": "commit"},
            {"ts": NOW - 400 * 86400, "language": "Go", "lines_added": 3, "event_type": "diff"},
        ])
        self.assertEqual(result["languages"], {"Go": 3, "Python": 12})
        self.assertEqual(result["event_types"], {"commit": 1, "diff": 1, "edit": 1, "write": 1})
        self.assertEqual(result["bytes"], 120)
        self.assertEqual(result["events"], 4)
        self.assertEqual(result["first_ts"], NOW - 400 * 86400)
        # Days older than the heatmap window plus a fortnight are not published.
        self.assertEqual(result["days"], {"2025-10-09": 12})

    def test_a_commit_only_day_is_kept_because_it_extends_a_streak(self):
        result = self.aggregate([{"ts": NOW - 86400, "language": None, "lines_added": 0, "event_type": "commit"}])
        self.assertEqual(result["days"], {"2025-10-08": 0})
        self.assertEqual(result["repo_count"], 4)

    def test_days_follow_the_configured_zone(self):
        # 23:30 UTC on 2025-10-08 is already the 9th in Tokyo.
        ts = 1759966200
        events = [{"ts": ts, "language": "Rust", "lines_added": 1, "event_type": "edit"}]
        self.assertEqual(list(self.aggregate(events, tz="UTC")["days"]), ["2025-10-08"])
        os.remove(os.path.join(self.tmp, "events.db"))
        self.assertEqual(list(self.aggregate(events, tz="Asia/Tokyo")["days"]), ["2025-10-09"])

    def test_only_aggregate_columns_are_serialised(self):
        result = self.aggregate([{"ts": NOW, "language": "Python", "lines_added": 1, "event_type": "edit"}])
        self.assertNotIn("acme-secret-client", json.dumps(result))


class MergeTest(unittest.TestCase):
    def test_out_of_range_or_non_integer_timestamps_skip_the_whole_file(self):
        for key in ("first_ts", "updated_at"):
            for value in (10**100, int(time.time()) + 86401, 1577836799, True, "now", 1.5):
                with self.subTest(key=key, value=value), self.assertWarnsRegex(RuntimeWarning, "aggregate"):
                    merged = data.merge([agg(languages={"Rust": 900}, **{key: value}),
                                         agg(languages={"Python": 3}, updated_at=NOW)])
                    self.assertEqual(merged["languages"], {"Python": 3})

    def test_invalid_language_names_skip_the_whole_file(self):
        for name in ("bad\u0000", "bad\u0001", "bad\ud800", "bad\ufffe", "<script>", "x" * 33, ""):
            with self.subTest(name=repr(name)), self.assertWarnsRegex(RuntimeWarning, "aggregate"):
                merged = data.merge([agg(languages={name: 100, "Rust": 900}),
                                     agg(languages={"Python": 3}, updated_at=NOW)])
                self.assertEqual(merged["languages"], {"Python": 3})

    def test_valid_language_charset_and_timestamp_boundaries_render(self):
        languages = {name: 1 for name in ("C++", "C#", "Objective-C", "Visual Basic .NET", "F#", "L_1")}
        merged = data.merge([agg(languages=languages, first_ts=1577836800, updated_at=NOW + 86400)], now=NOW)
        self.assertEqual(merged["languages"], languages)
        self.assertEqual(merged["first_ts"], 1577836800)
        data.card_data(merged, "octo-cat", NOW, tz="UTC")

    def test_counts_add_and_the_repo_count_does_not(self):
        merged = data.merge([
            agg(languages={"Python": 10}, event_types={"edit": 2}, days={"2025-10-01": 10},
                bytes=100, events=3, first_ts=NOW - 500, repo_count=9, updated_at=NOW - 1000),
            agg(languages={"Python": 1, "Rust": 4}, event_types={"commit": 1}, days={"2025-10-01": 5},
                bytes=10, events=1, first_ts=NOW - 700, repo_count=9, updated_at=NOW - 500),
        ])
        self.assertEqual(merged["languages"], {"Python": 11, "Rust": 4})
        self.assertEqual(merged["event_types"], {"edit": 2, "commit": 1})
        self.assertEqual(merged["days"], {"2025-10-01": 15})
        self.assertEqual((merged["bytes"], merged["events"]), (110, 4))
        self.assertEqual(merged["first_ts"], NOW - 700)
        self.assertEqual(merged["updated_at"], NOW - 500)
        self.assertEqual(merged["repo_count"], 9)

    def test_a_damaged_or_foreign_file_is_skipped(self):
        """The files come back from a repository; a bad one must not break or inflate the card."""
        merged = data.merge([
            agg(languages={"Python": 3}),
            {"format": 99, "languages": {"Python": 10**9}},
            "not a dict",
            agg(languages={"x" * 40: 5, "Go": -7, "Rust": "12", "C": True}),
        ])
        self.assertEqual(merged["languages"], {"Python": 3})

    def test_other_bucket_and_card_numbers(self):
        langs = {f"L{i}": 100 - i for i in range(9)}
        card = data.card_data(data.merge([agg(languages=langs, event_types={"edit": 2, "write": 1, "diff": 5})]),
                              "octo-cat", NOW, tz="UTC")
        self.assertEqual(card.total_actions, 3)
        self.assertEqual(card.total_diffs, 5)
        legend = data.with_other_bucket(card.languages)
        self.assertEqual(len(legend), 7)
        self.assertTrue(legend[-1].is_other)
        self.assertEqual(legend[-1].members, ["L6", "L7", "L8"])


if __name__ == "__main__":
    unittest.main()
