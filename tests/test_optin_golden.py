"""Python-only snapshots for optional card lines; Worker fixtures stay unchanged."""
from dataclasses import replace
import hashlib
import unittest
import xml.etree.ElementTree as ET

from devcard import data, render

NOW = 1760000000
SNAPSHOTS = {
    "full-10": "169d570171548403e513dca89e42dd07bb83d11d05e12880def347bc3887b7c7",
    "full-01": "2f72047c0d6fc8a6dbe033e09e46db86fc743e80bdd5e76f3ed41f68cb23a70a",
    "full-11": "ce5d72c3e62385bfbdd4758b8baf07ac0eed0a536a7445a802087100e5dfc12d",
    "wide-10": "16ca37b8a20e0410caabf1b6e4fccde809aae52874c000e8e48cec71ed45cd31",
    "wide-01": "2ef70cd526f3af2d31934e86cd415e85fbc257ddb71d6a892ff9c54480eef6af",
    "wide-11": "dd3f01f3d786f28e7d54370af60285b89179fd872c5041c037790fc309e8f27b",
    "banner-10": "08cc5ec0d18059d03923052e1306581982e5196636f092968e76e479b1987d4a",
    "banner-01": "bdb74a253b2232b1274cc6e7cb5eb3f4a49832fad6af61a9cd0a799f5be4b630",
    "banner-11": "a634d51d967ca1da73466e21fec531b5c9eba0321358906cdcee1e211b8b5b9f",
    "half-10": "f281f1495d499186de9d4a24dd3ec36977fa80349cb06446b3c103647eb976c0",
    "half-01": "8b2c7659fb8fd2f8ca8408979c55311d3eed2ea0811465a9b24bdc0ee77ccb57",
    "half-11": "35085b8270b0806cd7b664721a61b186528ddf90c041f9f8c940ccf513995d42",
    "vertical-10": "1e9ee958f56374eaeea00e5f3725b194bb268463c60b510ccbdba0030378e2b2",
    "vertical-01": "dbab99ee4ef33661e2b04ab9e979d7c0893f1f084ac49bb16f5b8ae975c1ef00",
    "vertical-11": "81f26bec1a80c38c0b75f7f6d5ff79268f3ad564924c26e0f8b68df46f017faa",
}


def fixture():
    merged = {"languages": {}, "event_types": {}, "days": {}, "bytes": 0, "events": 0,
              "first_ts": None, "repo_count": 0, "updated_at": NOW,
              "agents": {"claude-code": {"lines_added": 62, "lines_removed": 0, "bytes_added": 0, "events": 1, "active_minutes": 1530},
                         "git": {"lines_added": 38, "lines_removed": 0, "bytes_added": 0, "events": 1, "active_minutes": 930}},
              "usage": [{"date": "2025-10-09", "agent": "claude", "model_family": "claude-sonnet",
                         "input_tokens": 1000000, "output_tokens": 200000, "cache_read_tokens": 0,
                         "cache_write_tokens": 0, "estimated_cost_usd": "34"}]}
    return data.card_data(merged, "octo-cat", NOW, tz="UTC")


class OptInGoldenTest(unittest.TestCase):
    def test_optin_snapshots_and_dimensions_for_every_layout(self):
        card = fixture()
        for layout in render.LAYOUTS:
            base = ET.fromstring(render.render(card, layout=layout, now=NOW))
            for agents, usage in ((True, False), (False, True), (True, True)):
                key = f"{layout}-{int(agents)}{int(usage)}"
                with self.subTest(key=key):
                    svg = render.render(replace(card, show_agents=agents, show_usage=usage), layout=layout, now=NOW)
                    self.assertEqual(hashlib.sha256(svg.encode()).hexdigest(), SNAPSHOTS[key])
                    root = ET.fromstring(svg)
                    self.assertEqual(float(root.attrib["height"]), float(base.attrib["height"]) + 22 * (agents + usage))
                    self.assertEqual(root.attrib["width"], base.attrib["width"])
                    if agents:
                        self.assertIn("Claude Code 62% · git 38% · 41h active (est.)", svg)
                    if usage:
                        self.assertIn("1.2M tokens · ~$34.00 API-equivalent", svg)

    def test_default_bytes_ignore_optional_data(self):
        card = fixture()
        for layout in render.LAYOUTS:
            self.assertEqual(render.render(card, layout=layout, now=NOW),
                             render.render(replace(card, agent_totals={}, usage=[]), layout=layout, now=NOW))

    def test_unknown_cost_propagates_and_svg_is_escaped(self):
        card = fixture()
        unknown = {**card.usage[0], "estimated_cost_usd": None}
        svg = render.render(replace(card, usage=[*card.usage, unknown], show_usage=True, github_user='a<&"'), now=NOW)
        ET.fromstring(svg)
        self.assertIn("— API-equivalent", svg)
        self.assertNotIn("~$", svg)
        self.assertIn("a&lt;&amp;&quot;", svg)

    def test_empty_optin_never_claims_zero_cost_or_active_time(self):
        svg = render.render(replace(fixture(), agent_totals={}, active_minutes=None, usage=[], show_agents=True, show_usage=True), now=NOW)
        self.assertIn("Agent attribution unavailable", svg)
        self.assertIn("0 tokens · — API-equivalent", svg)
        self.assertNotIn("active", svg)


if __name__ == "__main__":
    unittest.main()
