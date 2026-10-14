"""Python-only snapshots for optional card lines; Worker fixtures stay unchanged."""
from dataclasses import replace
import hashlib
import unittest
import xml.etree.ElementTree as ET

from devcard import data, render

NOW = 1760000000
SNAPSHOTS = {
    "full-10": "7931099aded95711335cfb06c5be48cd87cc126d9fccc633644ba91e04d7113d",
    "full-01": "50237b5e08ed56c83748279baf403bb90c4c23a49ec6b6045ddefafacd03e250",
    "full-11": "f40fe68b02a0658ba0dfe56761ef5530cad402b3744a749c8b6b94adacbf7606",
    "wide-10": "03466390376e0fd8d7b0329e0607f69d6b2c703790bf6d7126e0a0fef63f1e9c",
    "wide-01": "9d6530a2b4585aa9e76bea66c63afceac18f8eca7a6f53d80bd0d1248e4dc60f",
    "wide-11": "12b7b415a3467ec69e549a474939a267614cf990d1990b0e6a4da53c6f06aee4",
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
