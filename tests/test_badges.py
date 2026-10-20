"""Badges expose only opted-in, consented summaries and absolute milestones."""
from dataclasses import replace
import unittest
import xml.etree.ElementTree as ET

from devcard import config, data
from devcard.badges import badge_files, badge_svg

NOW = 1760000000
NAMES = {"lines", "streak", "language", "tokens", "milestone-lines", "milestone-streak", "polyglot", "multi-agent"}
GATES = {"totals": {"lines", "milestone-lines"}, "activity": {"streak", "milestone-streak"},
         "languages": {"language", "polyglot"}, "usage": {"tokens"}, "agents": {"multi-agent"}}


def fixture():
    return replace(data.card_data({
        "lines": 1_234_567, "days": {},
        "languages": {"Python": 40, "Rust": 20, "Go": 15, "JavaScript": 15, "Shell": 10},
        "agents": {"claude-code": {"lines_added": 900, "active_minutes": 10},
                   "codex": {"lines_added": 100, "active_minutes": 5}},
        "usage": [{"model_family": "claude-opus", "input_tokens": 100, "output_tokens": 200,
                   "cache_read_tokens": 300, "cache_write_tokens": 400}],
    }, "octo-cat", NOW, tz="UTC"), longest_streak=29, streak=3)


def cfg(**extra):
    return {"stat_badges": True, "milestone_badges": True, "consent": config.FULL_CONSENT, **extra}


def names(files):
    return {path.removeprefix("badges/").removesuffix(".svg").removesuffix("-dark") for path in files}


class BadgeTest(unittest.TestCase):
    def test_svg_escaping_dimensions_accessibility_and_dark_variant(self):
        text = badge_svg('dev<&"', 'value<&"', "#123456", False)
        root = ET.fromstring(text)
        self.assertEqual(root.attrib["height"], "20")
        self.assertEqual(root.attrib["role"], "img")
        self.assertEqual(root.attrib["aria-label"], 'dev<&": value<&"')
        self.assertIn("&lt;&amp;&quot;", text)
        self.assertLess(int(ET.fromstring(badge_svg("devcard", "short", "#123456", False)).attrib["width"]),
                        int(ET.fromstring(badge_svg("devcard", "a much longer value", "#123456", False)).attrib["width"]))
        self.assertNotEqual(text, badge_svg('dev<&"', 'value<&"', "#123456", True))

    def test_switches_default_off_and_are_independent(self):
        card = fixture()
        self.assertEqual(badge_files(card, {"consent": config.FULL_CONSENT}), {})
        self.assertEqual(badge_files(card, cfg(stat_badges=False, milestone_badges=False)), {})
        self.assertEqual(names(badge_files(card, cfg(milestone_badges=False))), {"lines", "streak", "language", "tokens"})
        self.assertEqual(names(badge_files(card, cfg(stat_badges=False))), NAMES - {"lines", "streak", "language", "tokens"})
        self.assertEqual(badge_files(card, cfg(stat_badges="true", milestone_badges=1)), {})

    def test_every_category_independently_gates_both_variants(self):
        for category, expected in GATES.items():
            with self.subTest(category=category):
                files = badge_files(fixture(), cfg(consent={category: True}))
                self.assertEqual(names(files), expected)
                self.assertEqual(len(files), 2 * len(expected))
                for name in expected:
                    self.assertIn(f"badges/{name}.svg", files)
                    self.assertIn(f"badges/{name}-dark.svg", files)
                    self.assertNotEqual(files[f"badges/{name}.svg"], files[f"badges/{name}-dark.svg"])
        self.assertEqual(badge_files(fixture(), cfg(consent={})), {})

    def test_missing_sections_never_publish_stale_derived_fields(self):
        self.assertEqual(badge_files(replace(fixture(), sections=frozenset()), cfg()), {})

    def test_lines_thresholds_choose_highest_milestone(self):
        for lines, expected in ((99_999, None), (100_000, "100k lines"), (999_999, "100k lines"),
                                (1_000_000, "1M lines"), (1_234_567, "1M lines"), (10_000_000, "10M lines")):
            with self.subTest(lines=lines):
                files = badge_files(replace(fixture(), total_lines=lines), cfg())
                if expected:
                    self.assertIn(expected.encode(), files["badges/milestone-lines.svg"])
                else:
                    self.assertNotIn("badges/milestone-lines.svg", files)

    def test_streak_milestone_uses_longest_even_after_pause(self):
        for longest, expected in ((6, None), (7, 7), (29, 7), (30, 30), (89, 30), (90, 90)):
            with self.subTest(longest=longest):
                files = badge_files(replace(fixture(), longest_streak=longest, streak=0), cfg())
                if expected:
                    self.assertIn(f"{expected}-day streak".encode(), files["badges/milestone-streak.svg"])
                else:
                    self.assertNotIn("badges/milestone-streak.svg", files)

    def test_polyglot_requires_five_languages_at_one_percent(self):
        card = fixture()
        self.assertIn(b"Polyglot \xc2\xb7 5 languages", badge_files(card, cfg())["badges/polyglot.svg"])
        four = replace(card, languages=card.languages[:4])
        self.assertNotIn("badges/polyglot.svg", badge_files(four, cfg()))
        slices = [data.LanguageSlice(str(i), n) for i, n in enumerate((96, 1, 1, 1, 1, .5))]
        files = badge_files(replace(card, languages=slices, language_total=100), cfg())
        self.assertIn(b"5 languages", files["badges/polyglot.svg"])
        self.assertNotIn("badges/polyglot.svg", badge_files(replace(card, language_total=0), cfg()))

    def test_multi_agent_requires_positive_lines_from_both_coding_agents(self):
        files = badge_files(fixture(), cfg())
        self.assertIn(b"Multi-agent \xc2\xb7 Claude Code + Codex", files["badges/multi-agent.svg"])
        for agents in ({"claude-code": {"lines_added": 1}},
                       {"claude-code": {"lines_added": 1}, "git": {"lines_added": 1}},
                       {"claude-code": {"lines_added": 1}, "codex": {"lines_added": 0}}):
            self.assertNotIn("badges/multi-agent.svg", badge_files(replace(fixture(), agent_totals=agents), cfg()))

    def test_stat_values_and_zero_tokens(self):
        files = badge_files(fixture(), cfg())
        self.assertIn(b"1,000 tokens", files["badges/tokens.svg"])
        self.assertIn(b"Python 40%", files["badges/language.svg"])
        self.assertIn(b"3-day streak", files["badges/streak.svg"])
        self.assertNotIn("badges/tokens.svg", badge_files(replace(fixture(), model_tokens={}, usage=[]), cfg()))
        self.assertNotIn("badges/language.svg", badge_files(replace(fixture(), languages=[]), cfg()))

    def test_percent_only_languages_need_no_totals_consent(self):
        card = data.card_data({"language_percentages": {"Python": 40, "Rust": 20, "Go": 20, "Shell": 10, "C": 10}},
                              "octo-cat", NOW, tz="UTC")
        files = badge_files(card, cfg(consent={"languages": True}))
        self.assertEqual(names(files), {"language", "polyglot"})
        self.assertIn(b"Python 40%", files["badges/language.svg"])

    def test_polyglot_rounded_up_shares_do_not_qualify_without_totals(self):
        aggregate = {"format": 1, "languages": {"Python": 96040, "Rust": 990, "Go": 990, "C": 990, "Shell": 990}}
        consent = {"languages": True}
        public = data.consented(aggregate, consent)
        self.assertEqual(public["language_percentages"], {"Python": 96.0, "Rust": 1.0, "Go": 1.0, "C": 1.0, "Shell": 1.0})
        self.assertEqual(set(public), {"format", "language_percentages"})
        for sources in ([public], [public, public]):
            with self.subTest(sources=len(sources)):
                card = data.card_data(data.merge(sources, now=NOW), "octo-cat", NOW, tz="UTC")
                files = badge_files(card, cfg(consent=consent))
                self.assertNotIn("badges/polyglot.svg", files)
                self.assertNotIn("badges/polyglot-dark.svg", files)

    def test_polyglot_exact_one_percent_requires_unrounded_counts(self):
        aggregate = {"format": 1, "languages": {"Python": 96000, "Rust": 1000, "Go": 1000, "C": 1000, "Shell": 1000}}
        for totals in (False, True):
            with self.subTest(totals=totals):
                consent = {"languages": True, "totals": totals}
                public = data.consented(aggregate, consent)
                card = data.card_data(data.merge([public], now=NOW), "octo-cat", NOW, tz="UTC")
                files = badge_files(card, cfg(consent=consent))
                for suffix in ("", "-dark"):
                    self.assertEqual(f"badges/polyglot{suffix}.svg" in files, totals)

    def test_polyglot_rounded_percentages_are_not_renormalized_at_threshold(self):
        # Rounded shares can sum below 100; normalizing 1.0 must not qualify it.
        card = data.card_data({"language_percentages": {"Python": 95.9, "Rust": 1, "Go": 1, "C": 1, "Shell": 1}},
                              "octo-cat", NOW, tz="UTC")
        self.assertNotIn("badges/polyglot.svg", badge_files(card, cfg(consent={"languages": True})))

    def test_polyglot_percent_only_machines_require_each_source_to_qualify(self):
        first = {"format": 1, "language_percentages": {"Python": 60, "Rust": 10, "Go": 10, "C": 10, "Shell": 10}}
        second = {"format": 1, "language_percentages": {"Python": 100}}
        card = data.card_data(data.merge([first, second], now=NOW), "octo-cat", NOW, tz="UTC")
        # Unknown machine weights cannot establish 1% globally for the other four.
        self.assertNotIn("badges/polyglot.svg", badge_files(card, cfg(consent={"languages": True})))

    def test_polyglot_strictly_above_one_percent_qualifies_without_totals(self):
        aggregate = {"format": 1, "languages": {"Python": 95600, "Rust": 1100, "Go": 1100, "C": 1100, "Shell": 1100}}
        consent = {"languages": True}
        public = data.consented(aggregate, consent)
        self.assertEqual(set(public), {"format", "language_percentages"})
        for sources in ([public], [public, public]):
            with self.subTest(sources=len(sources)):
                card = data.card_data(data.merge(sources, now=NOW), "octo-cat", NOW, tz="UTC")
                files = badge_files(card, cfg(consent=consent))
                for suffix in ("", "-dark"):
                    self.assertIn(b"5 languages", files[f"badges/polyglot{suffix}.svg"])
