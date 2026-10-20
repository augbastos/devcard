"""README sizing contract, independent of the generated visual references."""
from dataclasses import replace
import unittest
import xml.etree.ElementTree as ET

from devcard import config, data, render
from tests.test_models import fixture
from tests.test_readme_hover import Tags

NS = {"s": "http://www.w3.org/2000/svg"}


class ReadmeScaleTest(unittest.TestCase):
    def test_embed_fills_column_for_both_theme_sources(self):
        tags = Tags(config.embed_html("octo-cat/cards")).tags
        images = [attrs for tag, attrs in tags if tag == "img"]
        self.assertEqual(len(images), 1)
        self.assertEqual(images[0]["width"], "100%")
        self.assertTrue(images[0]["src"].endswith("/card.svg"))
        self.assertTrue(next(attrs for tag, attrs in tags if tag == "source")["srcset"].endswith("/card-dark.svg"))

    def test_full_wide_scale_matches_reference_with_optional_sections(self):
        base = fixture()
        for sections in (base.sections, frozenset({"languages"}), frozenset()):
            card = replace(base, sections=sections, show_agents=True, show_usage=True,
                           show_models=True, model_tokens={"gpt": 100})
            for layout in ("full", "wide"):
                for split in (False, True):
                    with self.subTest(sections=sections, layout=layout, split=split):
                        root = ET.fromstring(render.render(card, layout=layout, split=split))
                        self.assertEqual(root.get("width"), "712")
                        self.assertEqual(root.get("viewBox").split()[2], "712")
                        self.assertAlmostEqual((830 / 712) / (560 / 480), 1, delta=.05)
                        if "usage" in sections:
                            self.assertIsNotNone(root.find("s:g[@id='model-bar']", NS))

    def test_wrapped_pills_and_provenance_clear_footer(self):
        card = replace(fixture(), badges=[{"kind": "badge", "label": "A long badge label"}] * 8,
                       pins=[{"repo": "example", "note": "A repository", "stars": 1}] * 3)
        for layout in ("full", "wide"):
            for split in (False, True):
                root = ET.fromstring(render.render(card, layout=layout, split=split))
                divider = float(root.find("s:line", NS).get("y1"))
                pills = root.findall(".//s:rect[@class='pill']", NS)
                self.assertTrue(pills)
                for pill in pills:
                    top, bottom = float(pill.get("y")), float(pill.get("y")) + float(pill.get("height"))
                    self.assertTrue(bottom < divider or top > divider + 22)
                    self.assertLess(bottom, float(root.get("height")))
                for text in root.findall(".//s:text", NS):
                    self.assertLess(float(text.get("y")), float(root.get("height")))

    def test_base_height_and_side_by_side_content_with_unchanged_text_scale(self):
        for layout, height, headline_size in (("full", 280, "30"), ("wide", 322, "32")):
            card = replace(fixture(), languages=[data.LanguageSlice(f"Language{i}", 100) for i in range(7)],
                           total_lines=700)
            root = ET.fromstring(render.render(card, layout=layout))
            self.assertEqual(root.get("height"), str(height))
            headline = root.find(f"s:text[@font-size='{headline_size}']", NS)
            self.assertIsNotNone(headline)
            legend = root.find("s:circle[@r='4.5']", NS)
            cells = root.findall("s:rect[@class='heat0']", NS)
            self.assertTrue(cells)
            self.assertLess(float(legend.get("cx")), min(float(c.get("x")) for c in cells))
            self.assertGreater(float(legend.get("cy")), min(float(c.get("y")) for c in cells) - 12)
            self.assertLess(float(legend.get("cy")), max(float(c.get("y")) for c in cells))

    def test_expanded_legend_grows_below_heatmap_and_clears_footer(self):
        card = replace(fixture(), languages=[data.LanguageSlice(f"Language{i}", 100) for i in range(40)],
                       total_lines=4000, show_agents=True, show_usage=True, show_models=True,
                       model_tokens={"gpt": 100})
        for layout in ("full", "wide"):
            for split in (False, True):
                root = ET.fromstring(render.render(card, layout=layout, split=split, all_langs=True))
                self.assertEqual(len(root.findall("s:circle[@r='4.5']", NS)), 40)
                labels = root.findall("s:text[@class='txt'][@font-size='12.5']", NS)
                divider = float(root.find("s:line", NS).get("y1"))
                self.assertLess(max(float(n.get("y")) for n in labels), divider)
                model = root.find("s:g[@id='model-bar']/s:text", NS)
                self.assertLess(float(model.get("y")), float(root.get("height")))

    def test_large_localized_footer_wraps_without_overlapping_stats(self):
        card = replace(fixture(), total_actions=12345678, total_commits=12345678,
                       total_events=123456789, first_ts=1750000000, updated_at=1760000000)
        for layout in ("full", "wide"):
            for lang in ("en", "pt", "es"):
                root = ET.fromstring(render.render(card, layout=layout, lang=lang, static=True))
                divider = float(root.find("s:line", NS).get("y1"))
                prov = [n for n in root.findall("s:text[@class='faint']", NS)
                        if float(n.get("y")) > divider][0]
                self.assertEqual(float(prov.get("y")), divider + 40)
                self.assertLess(float(prov.get("y")), float(root.get("height")))


if __name__ == "__main__":
    unittest.main()
