"""README sizing contract, independent of the generated visual references."""
from dataclasses import replace
import unittest
import xml.etree.ElementTree as ET

from devcard import config, render
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

    def test_wide_wrapped_pills_and_provenance_clear_footer(self):
        card = replace(fixture(), badges=[{"kind": "badge", "label": "A long badge label"}] * 8,
                       pins=[{"repo": "example", "note": "A repository", "stars": 1}] * 3)
        for split in (False, True):
            root = ET.fromstring(render.render(card, layout="wide", split=split))
            divider = root.find("s:line", NS)
            pills = root.findall(".//s:rect[@class='pill']", NS)
            self.assertTrue(pills)
            for pill in pills:
                self.assertLess(float(pill.get("y")) + float(pill.get("height")), float(divider.get("y1")))
            for text in root.findall("s:text", NS):
                self.assertLess(float(text.get("y")), float(root.get("height")))


if __name__ == "__main__":
    unittest.main()
