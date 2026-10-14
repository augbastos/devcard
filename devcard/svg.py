"""Shared SVG pieces: icons, colours, escaping, number formats, the language bar.

A port of worker/src/svg-utils.ts and worker/src/language-bar.ts. Output is
held byte-for-byte to the Worker's by tests/test_golden.py, which is why the
arithmetic below keeps JavaScript's operation order and goes through jsfmt.
"""
from datetime import datetime, timezone

from .jsfmt import en_us, js_len, js_round, js_slice, num, to_fixed

MONO = 'font-family="ui-monospace,SFMono-Regular,Consolas,monospace"'
SANS = "font-family=\"-apple-system,'Segoe UI',Roboto,'Helvetica Neue',sans-serif\""

LANGUAGE_COLORS = {
    "Python": "#3572A5", "JavaScript": "#f1e05a", "TypeScript": "#3178c6", "HTML": "#e34c26",
    "CSS": "#563d7c", "Rust": "#dea584", "PowerShell": "#012456", "SQL": "#336790",
    "Markdown": "#083fa1", "JSON": "#292929", "YAML": "#cb171e", "TOML": "#9c4221",
    "Shell": "#89e051", "Go": "#00add8", "Java": "#b07219", "C": "#555555", "C++": "#f34b7d",
    "Ruby": "#701516", "PHP": "#4f5d95",
}
NEUTRAL_LANGUAGE_COLOR = "#8b93a3"

KIND_ICONS = {
    "badge": "M0,-6 L1.8,-1.9 6,-1.9 2.7,0.9 3.7,5 0,2.4 -3.7,5 -2.7,0.9 -6,-1.9 -1.8,-1.9 Z",
    "certification": "M0,-5.5 A5.5,5.5 0 1 0 0.01,-5.5 Z M-2.6,-0.2 L-0.7,1.8 L2.8,-2 L1.8,-3 L-0.7,-0.3 L-1.6,-1.2 Z",
    "award": "M-4.5,-6 h9 v2.5 a4.5,4.5 0 0 1 -3.2,4.3 L1,3 h2 v2 h-6 v-2 h2 l-0.3,-2.2 A4.5,4.5 0 0 1 -4.5,-3.5 Z",
}
HEART_ICON = (
    "M0,4 C-4.6,0.6 -4.6,-3.4 -1.7,-3.4 C-0.6,-3.4 0,-2.5 0,-2.5 C0,-2.5 0.6,-3.4 1.7,-3.4 "
    "C4.6,-3.4 4.6,0.6 0,4 Z"
)
REPO_ICON = (
    "M0,-5 h7 a2,2 0 0 1 2,2 v8 h-9 a2,2 0 0 0 -2,2 v-10 a2,2 0 0 1 2,-2 Z "
    "M-2,7 h11 v3 h-9 a2,2 0 0 1 -2,-2 Z"
)
FLAME_ICON = (
    "M0.2,-7 C2.8,-4 4.6,-1.6 4.6,0.9 A4.7,4.7 0 0 1 -4.6,0.9 C-4.6,-0.9 -3.6,-2.4 -2.4,-3.7 "
    "C-2.1,-2.7 -1.5,-2 -0.6,-1.5 C-1,-3.4 -0.7,-5.2 0.2,-7 Z"
)


def escape_xml(value):
    """Every dynamic string in the card goes through here — it is strict XML."""
    return (
        str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def slice_label(s, other_word):
    return other_word if s.is_other else s.language


def slice_color(s):
    return NEUTRAL_LANGUAGE_COLOR if s.is_other else LANGUAGE_COLORS.get(s.language, NEUTRAL_LANGUAGE_COLOR)


def slice_title(s, other_word):
    if not s.is_other or not s.members:
        return slice_label(s, other_word)
    shown = ", ".join(s.members[:6])
    rest = len(s.members) - min(6, len(s.members))
    return f"{other_word}: {shown}{f' +{rest}' if rest > 0 else ''}"


def truncate(s, max_len):
    return js_slice(s, max(1, max_len - 1)) + "…" if js_len(s) > max_len else s


def _scaled(n, units, dec):
    for size, suffix in units:
        if n >= size:
            v = n / size
            text = to_fixed(v, 1).replace(".", dec) if v < 10 else str(js_round(v))
            return text + suffix
    return None


def fmt_count(n, dec):
    """12,837 → "12,837" · 171,340 → "171k" · 2,610,000 → "2.6m"."""
    if n < 100000:
        return en_us(n)
    scaled = _scaled(n, ((1e12, "t"), (1e9, "b"), (1e6, "m"), (1e3, "k")), dec)
    return scaled if scaled is not None else str(n)


def fmt_bytes(n, dec):
    scaled = _scaled(n, ((1e12, "tb"), (1e9, "gb"), (1e6, "mb"), (1e3, "kb")), dec)
    return scaled if scaled is not None else f"{n}b"


def iso_date(ts):
    """``new Date(ts * 1000).toISOString().slice(0, 10)`` — a UTC date."""
    return datetime.fromtimestamp(ts, timezone.utc).date().isoformat()


def fmt_age(updated_at, now):
    """"5min" / "3h" under a day, else the ISO date. None when never synced."""
    if not updated_at:
        return None
    diff = max(0, now - updated_at)
    if diff < 3600:
        return f"{max(1, js_round(diff / 60))}min"
    if diff < 86400:
        return f"{js_round(diff / 3600)}h"
    return iso_date(updated_at)


# -- language bar -------------------------------------------------------------

MIN_HIT_WIDTH = 3
TIP_H = 20
TIP_PAD = 9
TIP_CHAR = 6.15
TIP_GAP = 5


def language_bar_segments(slices, total_lines, geo, clip_id):
    """The visible bar: exact proportions, no minimum width, no tooltips."""
    x0, y, width, height = geo["x"], geo["y"], geo["width"], geo["height"]
    parts = [
        f'<clipPath id="{clip_id}"><rect x="{num(x0)}" y="{num(y)}" width="{num(width)}" height="{num(height)}" rx="{num(height / 2)}"/></clipPath>',
        f'<rect class="track" x="{num(x0)}" y="{num(y)}" width="{num(width)}" height="{num(height)}" rx="{num(height / 2)}"/>',
        f'<g clip-path="url(#{clip_id})">',
    ]
    x = x0
    for s in slices:
        w = (s.total / total_lines) * width if total_lines > 0 else 0
        parts.append(
            f'<rect x="{to_fixed(x, 2)}" y="{num(y)}" width="{to_fixed(w, 2)}" height="{num(height)}" fill="{slice_color(s)}"/>'
        )
        x += w
    parts.append("</g>")
    return "".join(parts)


def language_bar_hover(slices, total_lines, geo, other_word):
    """The hover layer — emitted last so its tooltips paint over everything."""
    if total_lines <= 0 or not slices:
        return ""
    widths = [(s.total / total_lines) * geo["width"] for s in slices]
    hit_widths = [max(w, MIN_HIT_WIDTH) for w in widths]
    overflow = _js_sum(hit_widths) - geo["width"]
    if overflow > 0:
        slack = [max(0, h - MIN_HIT_WIDTH) for h in hit_widths]
        total_slack = _js_sum(slack)
        if total_slack > 0:
            for i in range(len(hit_widths)):
                hit_widths[i] -= overflow * (slack[i] / total_slack)

    groups = []
    hit_x = geo["x"]
    for i, s in enumerate(slices):
        hit_w = hit_widths[i]
        pct = to_fixed((s.total / total_lines) * 100, 1)
        label = f"{slice_label(s, other_word)} {pct}%"
        tip_w = js_round(js_len(label) * TIP_CHAR) + TIP_PAD * 2
        tip_x = hit_x + hit_w / 2 - tip_w / 2
        tip_x = min(max(tip_x, geo["clampLeft"]), geo["clampRight"] - tip_w)
        tip_y = geo["y"] + geo["height"] + TIP_GAP
        groups.append(
            '<g class="lang">'
            f'<rect class="hit" x="{to_fixed(hit_x, 2)}" y="{num(geo["y"])}" width="{to_fixed(hit_w, 2)}" height="{num(geo["height"])}" aria-label="{escape_xml(label)}"/>'
            '<g class="tip">'
            f'<rect class="tipbg" x="{to_fixed(tip_x, 1)}" y="{num(tip_y)}" width="{num(tip_w)}" height="{TIP_H}" rx="6"/>'
            f'<circle cx="{to_fixed(tip_x + TIP_PAD + 3, 1)}" cy="{num(tip_y + TIP_H / 2)}" r="3.5" fill="{slice_color(s)}"/>'
            f'<text class="tiptx" x="{to_fixed(tip_x + TIP_PAD + 12, 1)}" y="{num(tip_y + TIP_H / 2 + 3.8)}" '
            "font-family=\"-apple-system,'Segoe UI',Roboto,sans-serif\" font-size=\"11\">"
            f"{escape_xml(label)}</text>"
            "</g>"
            "</g>"
        )
        hit_x += hit_w
    return f'<g class="langhover">{"".join(groups)}</g>'


def _js_sum(values):
    """``values.reduce((a, b) => a + b, 0)`` — left to right, like the original."""
    total = 0
    for v in values:
        total += v
    return total
