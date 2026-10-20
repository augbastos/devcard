"""Opt-in model-family token shares; the default card remains unchanged."""
from dataclasses import replace
import unittest
import xml.etree.ElementTree as ET

from devcard import data, render, svg
from devcard.themes import theme_pair

NOW = 1760000000
NS = {"s": "http://www.w3.org/2000/svg"}


def fixture():
    return data.card_data({"languages": {"Python": 100}, "lines": 100, "days": {},
                           "repo_count": 0, "usage": []}, "octo-cat", NOW, tz="UTC")


class ModelBarTest(unittest.TestCase):
    def test_slices_fold_small_families_and_sort_by_share(self):
        slices = svg.model_slices({"claude-opus": 9800, "claude-sonnet": 100,
                                   "claude-haiku": 49, "gpt": 1, "unknown": 50})
        self.assertEqual([label for label, _, _ in slices], ["Opus", "Other", "Sonnet"])
        self.assertAlmostEqual(sum(share for _, _, share in slices), 1)
        self.assertAlmostEqual(slices[1][2], .01)
        self.assertEqual(svg.model_slices({"gpt": 0}), [])

    def test_palette_and_allowlist(self):
        slices = svg.model_slices(dict.fromkeys(("claude-opus", "claude-sonnet", "claude-haiku", "gpt", "o"), 10))
        self.assertEqual({label: colour for label, colour, _ in slices},
                         {"Opus": "#C15F3C", "Sonnet": "#D97757", "Haiku": "#E9A27F",
                          "GPT": "#10A37F", "o-series": "#0B7A5F"})
        self.assertEqual(svg.model_slices({"private-model-name": 10})[0][0], "Other")

    def test_bar_requires_toggle_usage_and_positive_tokens(self):
        card = replace(fixture(), model_tokens={"claude-opus": 100})
        base = render.render(card)
        self.assertNotIn('id="model-bar"', base)
        enabled = replace(card, show_models=True)
        self.assertIn('id="model-bar"', render.render(enabled))
        self.assertEqual(render.render(replace(enabled, model_tokens={})), base)
        self.assertEqual(render.render(replace(enabled, model_tokens={"gpt": 0})), base)
        denied = replace(enabled, sections=card.sections - {"usage"})
        self.assertEqual(render.render(denied), render.render(replace(denied, show_models=False)))

    def test_legend_and_layouts_in_both_themes_and_split_body(self):
        card = replace(fixture(), show_models=True, show_usage=True,
                       model_tokens={"claude-opus": 52, "claude-sonnet": 31, "gpt": 17})
        for layout in ("full", "wide"):
            for theme in theme_pair("default"):
                for split in (False, True):
                    with self.subTest(layout=layout, theme=theme, split=split):
                        text = render.render(card, layout=layout, theme=theme, split=split)
                        root = ET.fromstring(text)
                        bar = root.find("s:g[@id='model-bar']", NS)
                        self.assertIsNotNone(bar)
                        self.assertIn("Opus 52% · Sonnet 31% · GPT 17%", text)
                        self.assertEqual(len(bar.findall(".//s:rect[s:title]", NS)), 3)
                        self.assertGreater(text.index('id="model-bar"'), text.index("API-equivalent"))
                        self.assertGreater(float(root.attrib["height"]), float(bar.find("s:text", NS).attrib["y"]))

    def test_single_family_full_width_and_neutral_uses_theme(self):
        card = replace(fixture(), show_models=True, model_tokens={"claude-opus": 1})
        root = ET.fromstring(render.render(card))
        segment = root.find("s:g[@id='model-bar']/s:g/s:rect", NS)
        self.assertEqual(float(segment.attrib["width"]), float(root.attrib["width"]) - 48)
        self.assertIn("Opus 100%", ET.tostring(root, encoding="unicode"))
        for theme in theme_pair("default"):
            text = render.render(replace(card, model_tokens={"unknown": 1}), theme=theme)
            self.assertIn(f'fill="{theme["base"]["mut"]}"', text)

    def test_compact_layouts_skip_bar_without_changing_bytes(self):
        card = replace(fixture(), model_tokens={"gpt": 100})
        for layout in ("banner", "half", "vertical"):
            self.assertEqual(render.render(replace(card, show_models=True), layout=layout),
                             render.render(card, layout=layout))
