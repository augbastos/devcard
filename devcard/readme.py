"""Static README hover pieces, ported from the legacy Worker's render-split.

GitHub cannot hover inside SVG-in-img. Adjacent images with HTML titles can;
their percentage widths and labels must be refreshed along with the data.
"""
from . import config
from .data import with_other_bucket
from .jsfmt import js_round, num, to_fixed
from .render import README_WIDTH, WIDE_PAD, split_supported
from .strings import STRINGS, lang_name
from .svg import escape_xml, slice_color, slice_title

START = "<!-- devcard:start -->"
END = "<!-- devcard:end -->"
WIDTH = README_WIDTH
PAD = WIDE_PAD
INNER = WIDTH - 2 * PAD
STRIP_HEIGHT = 34
BAR_HEIGHT = 14
CORNER = 14
PERCENT_UNITS = 1_000_000


def enabled(cfg):
    return cfg.get("readme_hover") is True and config.consents(cfg)["languages"]


def strip_layout(card):
    """Integer ten-thousandths of a percent, including both end caps.

    Use the card legend's Other bucket. Like the Worker, give small targets
    four pixels, paid for from larger slices; titles always state true shares.
    The right cap absorbs rounding so the row is exactly 100% wide.
    """
    slices = with_other_bucket(card.languages)
    left = js_round(PAD / WIDTH * PERCENT_UNITS)
    if card.language_total <= 0 or not slices:
        return left, [], PERCENT_UNITS - left
    floor = min(4, INNER / len(slices))
    widths = [max(s.total / card.language_total * INNER, floor) for s in slices]
    overflow = sum(widths) - INNER
    slack = [max(0, w - floor) for w in widths]
    total_slack = sum(slack)
    if overflow > 0 and total_slack > 0:
        widths = [w - overflow * room / total_slack for w, room in zip(widths, slack, strict=True)]
    slots = [(s, js_round(w / WIDTH * PERCENT_UNITS), s.total / card.language_total)
             for s, w in zip(slices, widths, strict=True)]
    return left, slots, max(0, PERCENT_UNITS - left - sum(units for _, units, _ in slots))


def _piece(theme, units, s=None, end=None, side=None):
    width = max(0.01, WIDTH * units / PERCENT_UNITS)
    w = num(round(width, 6))
    palette = theme["base"]
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{STRIP_HEIGHT}" '
             f'viewBox="0 0 {w} {STRIP_HEIGHT}">']
    if side:
        x = 0.5 if side == "left" else -CORNER
        parts.append(f'<rect x="{x}" y="{-CORNER}" width="{num(round(width + CORNER - 0.5, 6))}" '
                     f'height="{STRIP_HEIGHT - 0.5 + CORNER}" rx="{CORNER}" '
                     f'fill="{palette["bg"]}" stroke="{palette["brd"]}"/>')
    else:
        parts.extend([f'<rect width="{w}" height="{STRIP_HEIGHT}" fill="{palette["bg"]}"/>',
                      f'<rect y="{STRIP_HEIGHT - 1}" width="{w}" height="1" fill="{palette["brd"]}"/>'])
        if s:
            radius = min(BAR_HEIGHT / 2, width / 2) if end else 0
            x = -BAR_HEIGHT if end == "right" else 0
            bar_width = width if end == "both" else width + BAR_HEIGHT
            parts.append(f'<rect x="{x}" y="6" width="{num(round(bar_width, 6))}" height="{BAR_HEIGHT}" '
                         f'rx="{num(round(radius, 6))}" fill="{slice_color(s)}"/>')
    return "".join(parts) + "</svg>"


def slice_files(card, light, dark):
    """All hover SVGs for a fresh data-branch tree; no stale slices carried over."""
    left, slots, right = strip_layout(card)
    files = {}
    for suffix, theme in (("", light), ("-dark", dark)):
        for side, units in (("left", left), ("right", right)):
            files[f"lang/cap-{side}{suffix}.svg"] = _piece(theme, units, side=side).encode("utf-8")
        for i, (s, units, _share) in enumerate(slots):
            end = "both" if len(slots) == 1 else "left" if i == 0 else "right" if i == len(slots) - 1 else None
            files[f"lang/{i}{suffix}.svg"] = _piece(theme, units, s, end).encode("utf-8")
    return files


def _picture(repo, name, units, title="", alt=""):
    light = escape_xml(config.raw_url(repo, f"lang/{name}.svg"))
    dark = escape_xml(config.raw_url(repo, f"lang/{name}-dark.svg"))
    title_attr = f' title="{escape_xml(title)}"' if title else ""
    return ('<picture><source media="(prefers-color-scheme: dark)" '
            f'srcset="{dark}"><img src="{light}" width="{num(units / 10000)}%" '
            f'align="top"{title_attr} alt="{escape_xml(alt or title)}"></picture>')


def build_block(repo, card, lang="en", layout="full"):
    """One visual card: a flat-bottom body followed by its gap-free strip.

    Other layouts and cards without languages retain the single-image embed.
    """
    if not split_supported(card, layout):
        return config.embed_html(repo)
    left, slots, right = strip_layout(card)
    other = STRINGS[lang_name(lang)]["other"]
    pieces = [_picture(repo, "body", PERCENT_UNITS, alt=f"devcard — {card.github_user}'s coding stats"),
              _picture(repo, "cap-left", left)]
    for i, (s, units, share) in enumerate(slots):
        title = f"{slice_title(s, other)} {to_fixed(share * 100, 1)}%"
        pieces.append(_picture(repo, str(i), units, title))
    pieces.append(_picture(repo, "cap-right", right))
    return "<p>" + "".join(pieces) + "</p>"


def replace_block(readme, block):
    """Replace only the marker contents, preserving LF/CRLF everywhere.

    Shared with scripts/refresh_readme.py, the optional legacy Worker client.
    """
    start, end = readme.find(START), readme.find(END)
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"markers not found: the README needs {START} and {END} around the card")
    newline = "\r\n" if "\r\n" in readme else "\n"
    block = block.replace("\r\n", "\n").replace("\n", newline)
    return readme[:start + len(START)] + newline + block + newline + readme[end:]
