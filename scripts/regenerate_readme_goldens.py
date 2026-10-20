"""Regenerate Python full/wide references; leave legacy Worker SVGs untouched.

Run from the repository root: python scripts/regenerate_readme_goldens.py
"""
from dataclasses import replace
import hashlib
from pathlib import Path
import re
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from devcard import render  # noqa: E402
from tests.test_golden import GOLDEN, aggregate_for, card_for, python_golden_name  # noqa: E402
from tests.test_optin_golden import NOW, fixture  # noqa: E402


def main():
    count = 0
    with tempfile.TemporaryDirectory() as tmp:
        aggs = {name: aggregate_for(name, tmp) for name in GOLDEN["fixtures"]}
        for v in GOLDEN["variants"]:
            if v["layout"] not in ("full", "wide"):
                continue
            card = card_for(v["fixture"], v["lang"], aggs[v["fixture"]])
            svg = render.render(card, v["theme"], v["lang"], v["layout"],
                                now=GOLDEN["now"], all_langs=v.get("langs") == "all")
            path = ROOT / "tests" / "golden" / python_golden_name(v)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(svg + "\n", encoding="utf-8", newline="\n")
            count += 1
    path = ROOT / "tests" / "test_optin_golden.py"
    text = path.read_text(encoding="utf-8")
    for layout in ("full", "wide"):
        for agents, usage in ((True, False), (False, True), (True, True)):
            card = replace(fixture(), show_agents=agents, show_usage=usage)
            svg = render.render(card, layout=layout, now=NOW)
            key = f"{layout}-{int(agents)}{int(usage)}"
            digest = hashlib.sha256(svg.encode()).hexdigest()
            text = re.sub(rf'("{key}": ")[a-f0-9]+', rf'\g<1>{digest}', text)
    path.write_text(text, encoding="utf-8", newline="\n")
    print(f"Regenerated {count} README SVGs and 6 full/wide opt-in hashes.")


if __name__ == "__main__":
    main()
