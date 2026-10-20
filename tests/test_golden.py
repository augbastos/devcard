"""The Python renderer against deliberately generated golden SVGs.

worker/test/golden.test.ts sends each fixture's events through the Worker's real
/ingest, renders every listed variant through /svg with the clock pinned, and
writes tests/golden/. This test puts the same events into a real hook database
(hook/devcard_lib.init_db), builds the rollups with devcard.data, renders with
devcard.render, and compares. Full/wide now use Python-generated readme/ goldens;
the original Worker references remain untouched for its historical geometry.
Whitespace is normalised; nothing else is.
"""
import json
import os
import re
import tempfile
import unittest

from devcard import config, data, render
from devcard._hook import lib

GOLDEN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "golden")
with open(os.path.join(GOLDEN_DIR, "fixtures.json"), encoding="utf-8") as _f:
    GOLDEN = json.load(_f)


def golden_name(v):
    return f"{v['fixture']}/{v['layout']}-{v['theme']}-{v['lang']}{'-all' if v.get('langs') == 'all' else ''}.svg"


def python_golden_name(v):
    name = golden_name(v)
    return f"readme/{name}" if v["layout"] in ("full", "wide") else name


def normalise(svg):
    return re.sub(r"\s+", " ", svg).strip()


def build_db(path, events):
    """A hook database holding `events`, with a project path the card must never see."""
    conn = lib.init_db(path)
    for e in events:
        lib.insert_event(conn, {**e, "project_key": "/home/someone/secret-client-project",
                                "source_id": "goldenfixture"})
    return conn


def aggregate_for(name, tmp):
    fixture = GOLDEN["fixtures"][name]
    conn = build_db(os.path.join(tmp, f"{name}.db"), fixture["events"])
    try:
        agg = data.aggregate(conn, GOLDEN["now"], tz=GOLDEN["timezone"], repo_count=fixture["repo_count"],
                             consent=config.FULL_CONSENT)
    finally:
        conn.close()
    # The Worker stamps updated_at when the repo count arrives; a fixture with
    # no sync has none.
    agg["updated_at"] = fixture["updated_at"]
    return agg


def card_for(name, locale, agg):
    fixture = GOLDEN["fixtures"][name]
    return data.card_data(
        data.merge([agg]), GOLDEN["github_user"], GOLDEN["now"], locale=locale, tz=GOLDEN["timezone"],
        avatar=GOLDEN["avatar"], badges=fixture.get("badges", ()), pins=fixture.get("pins", ()),
    )


class GoldenTest(unittest.TestCase):
    def test_every_variant_matches_its_renderer_reference(self):
        self.assertGreater(len(GOLDEN["variants"]), 40)
        with tempfile.TemporaryDirectory() as tmp:
            aggs = {name: aggregate_for(name, tmp) for name in GOLDEN["fixtures"]}
            for v in GOLDEN["variants"]:
                name = python_golden_name(v)
                with self.subTest(name):
                    card = card_for(v["fixture"], v["lang"], aggs[v["fixture"]])
                    got = render.render(card, v["theme"], v["lang"], v["layout"], now=GOLDEN["now"],
                                        all_langs=v.get("langs") == "all")
                    with open(os.path.join(GOLDEN_DIR, name), encoding="utf-8") as f:
                        want = f.read()
                    self.assertEqual(normalise(got), normalise(want))

    def test_the_project_path_never_reaches_the_card(self):
        with tempfile.TemporaryDirectory() as tmp:
            card = card_for("rich", "en", aggregate_for("rich", tmp))
            for layout in render.LAYOUTS:
                svg = render.render(card, layout=layout, now=GOLDEN["now"])
                self.assertNotIn("secret-client-project", svg)


if __name__ == "__main__":
    unittest.main()
