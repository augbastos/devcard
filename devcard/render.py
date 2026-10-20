"""The card layouts. A port of worker/src/render.ts, render-wide.ts and render-layouts.ts.

Pure: (CardData, theme, strings, now) in, SVG text out. `now` is a parameter
rather than read from the clock so that a render is reproducible — the golden
tests depend on it.

Full/wide use a 712px README canvas; the legacy Worker keeps its geometry.
`static=True` is another deliberate difference from the Worker. A published
card is a file that sits unchanged until the next publish, so the Worker's
"updated 5min ago" would be baked in and soon false; a static card says
"updated 2025-10-09" instead. `static=False` retains the Worker's relative
timestamps, which the golden tests also cover.
"""
import math
from decimal import Decimal, localcontext
import re

from .data import NAMED_LANGUAGES, with_other_bucket
from .jsfmt import en_us, js_len, js_round, num, to_fixed
from .strings import STRINGS, lang_name
from .svg import (
    FLAME_ICON,
    HEART_ICON,
    KIND_ICONS,
    MONO,
    REPO_ICON,
    SANS,
    escape_xml,
    fmt_age,
    fmt_bytes,
    fmt_count,
    iso_date,
    language_bar_hover,
    language_bar_segments,
    model_slices,
    slice_color,
    slice_label,
    slice_title,
    truncate,
)
from .themes import THEMES, css_for, theme_name

LAYOUTS = ("full", "wide", "banner", "half", "vertical")
# At an 830px README column, design units scale almost exactly as 480px at 560px.
README_WIDTH = 712


def split_supported(data, layout="full"):
    """Only full/wide cards with a language section have a README strip."""
    return layout in ("full", "wide") and "languages" in data.sections


def render(data, theme="default", lang="en", layout="full", now=0, all_langs=False, static=False, split=False):
    """Render a variant, optionally extending it with agent and usage estimates.

    Unknown variant names fall back. `theme` accepts a name or palette dict.
    Without opt-in flags the base layout's bytes are returned unchanged.

    `split=True` moves the language bar to the README's separate bottom strip.
    Unsupported layouts or cards without languages retain the normal embed.
    """
    split = split and split_supported(data, layout)
    svg = _render_base(data, theme, lang, layout, now, all_langs, static, split)
    lines = []
    if data.show_agents and "agents" in data.sections:
        totals = sorted(data.agent_totals.items(), key=lambda r: (-r[1]["lines_added"], r[0]))
        total = sum(row["lines_added"] for _, row in totals)
        labels = {"claude-code": "Claude Code", "codex": "Codex", "git": "git", "unknown": "Unknown"}
        line = (" · ".join(f"{labels[agent]} {js_round(row['lines_added'] / total * 100)}%"
                           for agent, row in totals if row["lines_added"])
                if total else "Agent attribution unavailable")
        if data.active_minutes is not None:
            duration = (f"{data.active_minutes:g}min" if data.active_minutes < 60
                        else f"{data.active_minutes / 60:.1f}".removesuffix(".0") + "h")
            line += f" · {duration} active (est.)"
        lines.append(line)
    if data.show_usage and "usage" in data.sections:
        tokens = sum(sum(row[name] for name in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens"))
                     for row in data.usage)
        costs = [row["estimated_cost_usd"] for row in data.usage]
        with localcontext() as ctx:
            ctx.prec = 80
            cost = None if not costs or any(c is None for c in costs) else sum(map(Decimal, costs), Decimal(0))
        price = "—" if cost is None else f"~${cost:.2f}"
        lines.append(f"{fmt_count(tokens, '.').upper()} tokens · {price} API-equivalent")
    models = (model_slices(data.model_tokens)
              if data.show_models and "usage" in data.sections and layout in ("full", "wide") else [])
    if not lines and not models:
        return svg  # Defaults retain the original bytes for every layout.
    root = re.search(r'width="([\d.]+)" height="([\d.]+)" viewBox="0 0 [\d.]+ [\d.]+"', svg)
    width, height = map(float, root.groups())
    model_svg, model_height = "", 0
    if models:
        palette = theme if isinstance(theme, dict) else THEMES[theme_name(theme)]
        pad = 28 if layout == "wide" or split else 24
        model_svg, model_height = _model_bar(models, pad, height + 22 * len(lines), width - 2 * pad,
                                             palette["base"]["mut"])
    new_height = height + 22 * len(lines) + model_height
    svg = svg[:root.start()] + (f'width="{num(width)}" height="{num(new_height)}" '
                                f'viewBox="0 0 {num(width)} {num(new_height)}"') + svg[root.end():]
    frame_extra = 14 if split else -1
    svg = svg.replace(f'height="{num(height + frame_extra)}" rx=',
                      f'height="{num(new_height + frame_extra)}" rx=', 1)
    extra = "".join(
        f'<text class="mut" x="24" y="{num(height + 13 + i * 22)}" {SANS} font-size="10">'
        f'<title>{escape_xml("Share of recorded lines added; activity estimate (concurrent agents counted independently): " + line if data.show_agents and "agents" in data.sections and i == 0 else line + " (estimate; not your subscription bill)")}</title>'
        f'{escape_xml(truncate(line, int((width - 48) / 5.5)))}</text>'
        for i, line in enumerate(lines)
    )
    return svg.replace("</svg>", extra + model_svg + "</svg>")


def _model_bar(slices, pad, top, width, neutral):
    """A thin token-share bar and a short, wrapping family legend."""
    y, x = top + 5, pad
    parts = ['<g id="model-bar">',
             f'<clipPath id="model-clip"><rect x="{num(pad)}" y="{num(y)}" '
             f'width="{num(width)}" height="6" rx="3"/></clipPath>', '<g clip-path="url(#model-clip)">']
    labels = []
    for label, colour, share in slices:
        text = f"{label} {js_round(share * 100)}%"
        fill = f'class="mut" fill="{neutral}"' if label == "Other" else f'fill="{colour}"'
        parts.append(f'<rect x="{to_fixed(x, 2)}" y="{num(y)}" width="{to_fixed(width * share, 2)}" '
                     f'height="6" {fill}><title>{escape_xml(text)}</title></rect>')
        x += width * share
        labels.append(text)
    parts.append("</g>")
    rows = [""]
    for label in labels:
        candidate = f"{rows[-1]} · {label}" if rows[-1] else label
        if js_len(candidate) * 5.5 > width and rows[-1]:
            rows.append(label)
        else:
            rows[-1] = candidate
    for i, row in enumerate(rows):
        parts.append(f'<text class="mut" x="{num(pad)}" y="{num(top + 26 + i * 16)}" '
                     f'{SANS} font-size="10">{escape_xml(row)}</text>')
    parts.append("</g>")
    return "".join(parts), 36 + (len(rows) - 1) * 16


def _render_base(data, theme="default", lang="en", layout="full", now=0, all_langs=False, static=False, split=False):
    """Render one variant. Unknown names fall back, as the Worker's query params do.

    `theme` is a theme name or a palette dict as themes.theme_pair returns.
    """
    t = STRINGS[lang_name(lang)]
    tokens = theme if isinstance(theme, dict) else THEMES[theme_name(theme)]
    if not {"languages", "activity", "totals", "repo_count"} <= data.sections:
        return render_sections(data, tokens, t, layout, now, static, split)
    if layout == "wide":
        return render_wide(data, tokens, t, now, all_langs, static, split)
    if layout == "banner":
        return render_banner(data, tokens, t)
    if layout == "half":
        return render_half(data, tokens, t)
    if layout == "vertical":
        return render_vertical(data, tokens, t)
    return render_full(data, tokens, t, now, all_langs, static, split)


def render_sections(data, theme, t, layout, now, static, split=False):
    """Existing card primitives, stacked without gaps for missing sections.

    The complete card keeps its dedicated render path.
    Presence comes from the aggregate, never from a consent check in the SVG.
    """
    W = {"wide": README_WIDTH, "banner": 840, "half": 420, "vertical": 320}.get(layout, README_WIDTH)
    PAD, y = 24, 84
    if split:
        W, PAD = WIDE_W, WIDE_PAD
    inner = W - PAD * 2
    user = escape_xml(data.github_user)
    avatar = (f'<clipPath id="av"><circle cx="42" cy="36" r="17"/></clipPath>'
              f'<image href="{escape_xml(data.avatar)}" x="25" y="19" width="34" height="34" clip-path="url(#av)"/>'
              if data.avatar else
              f'<circle class="pill" cx="42" cy="36" r="17"/><text class="mut" x="42" y="41" {SANS} '
              f'font-size="14" text-anchor="middle">{_initial(data)}</text>')
    parts = [avatar, f'<text class="txt" x="68" y="32" {SANS} font-size="15" font-weight="700">devcard</text>',
             f'<text class="mut" x="68" y="50" {MONO} font-size="12">@{escape_xml(truncate(data.github_user, 28 if W < 480 else 39))}</text>']

    def line(text, cls="mut", size=12):
        nonlocal y
        parts.append(f'<text class="{cls}" x="{PAD}" y="{y}" {MONO} font-size="{size}">{escape_xml(text)}</text>')
        y += 22

    if "repo_count" in data.sections:
        parts.append(f'<a href="https://github.com/{user}?tab=repositories" target="_blank">'
                     f'<text class="link" x="{W - PAD}" y="32" {MONO} font-size="12" text-anchor="end">'
                     f'{data.repo_count} {escape_xml(t["repos"])} →</text></a>')
    if "totals" in data.sections:
        parts.append(f'<text class="txt" x="{PAD}" y="{y}" {MONO} font-size="18">'
                     f'{fmt_count(data.total_lines, t["dec"])}<tspan class="mut" {SANS} font-size="12">'
                     f' {escape_xml(t["lines"])} ({fmt_bytes(data.total_bytes, t["dec"])})</tspan></text>')
        y += 22
        line(f'{data.total_actions} {t["edits"]} · {data.total_commits} {t["commits"]}')
    if "languages" in data.sections:
        total = data.language_total
        geo = {"x": PAD, "y": y - 4, "width": inner, "height": 12,
               "clampLeft": PAD, "clampRight": W - PAD}
        if not split:
            parts.append(language_bar_segments(data.languages, total, geo, "barclip"))
            y += 30
        for s in with_other_bucket(data.languages):
            pct = to_fixed(s.total / total * 100, 1) if total else "0.0"
            parts.append(f'<circle cx="{PAD + 5}" cy="{y - 4}" r="4.5" fill="{slice_color(s)}"/>')
            parts.append(f'<text class="txt" x="{PAD + 17}" y="{y}" {SANS} font-size="12.5">'
                         f'{escape_xml(slice_label(s, t["other"]))}<tspan class="mut" {MONO}> {pct}%</tspan></text>')
            y += 22
        y += 10
    if "activity" in data.sections:
        line(f'{data.streak} {t["dayStreak"]}')
        heat, height = render_heatmap(data, PAD, y - 6, 8, 2)
        parts.append(heat)
        y += height + 18
    # Manually configured profile decoration is independent of collected stats.
    pills = _Pills(PAD, W - PAD, y)
    _add_pills(pills, data)
    for pin in data.pins:
        pills.add(pin["repo"], REPO_ICON,
                  href=f'https://github.com/{user}/{escape_xml(pin["repo"])}')
    if pills.parts:
        parts.extend(pills.parts)
        y += (pills.row + 1) * 28
    prov = provenance(data, t, now, static)
    if prov:
        # Separate provenance parts on narrow cards instead of clipping text.
        for part in prov.split(" · "):
            line(part, "faint", 9.5)
    H = max(72, y + 2)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
            f'role="img" aria-label="devcard {user}">\n'
            f'<style>{css_for(theme)}</style>\n'
            f'<rect class="bg brd" x="0.5" y="0.5" width="{W - 1}" height="{H + 14 if split else H - 1}" rx="14" stroke-width="1"/>\n'
            + "\n".join(parts) + "\n</svg>")


def provenance(data, t, now, static):
    """"tracking since … · N events · updated …" — the footer's fine print."""
    since = iso_date(data.first_ts) if data.first_ts else None
    parts = []
    if since:
        parts += [f"{t['since']} {since}", f"{en_us(data.total_events)} {t['events']}"]
    if static:
        if data.updated_at:
            parts.append(t["updatedOn"].replace("{X}", iso_date(data.updated_at)))
    else:
        age = fmt_age(data.updated_at, now)
        if age:
            parts.append(t["updatedAgo"].replace("{X}", age))
    return " · ".join(parts)


def _initial(data):
    return escape_xml(data.github_user[:1].upper())


def render_heatmap(data, x0, top, cell, gap, *, label_h=12, label_size=8.5, radius=2):
    step = cell + gap
    marks = "".join(
        f'<text class="faint" x="{num(x0 + w * step)}" y="{num(top + label_h - 4)}" {MONO} font-size="{num(label_size)}">{escape_xml(label)}</text>'
        for w, label in data.month_marks
    )
    cells = []
    for w, week in enumerate(data.heat_weeks):
        for d, c in enumerate(week):
            cells.append(
                f'<rect class="heat{c.level}" x="{num(x0 + w * step)}" y="{num(top + label_h + d * step)}" '
                f'width="{num(cell)}" height="{num(cell)}" rx="{num(radius)}"><title>{c.day}: {c.lines}</title></rect>'
            )
    return marks + "".join(cells), label_h + 7 * step - gap


def streak_block(data, t, right_x, base_y):
    cls = "accent" if data.streak >= 7 else "mut"
    flame = f'<path class="{cls}" d="{FLAME_ICON}" transform="translate({num(right_x - 8)},{num(base_y - 8)}) scale(1.15)"/>'
    number = (
        f'<text class="txt" x="{num(right_x - 20)}" y="{num(base_y)}" {MONO} font-size="26" '
        f'font-weight="700" text-anchor="end">{data.streak}</text>'
    )
    label = (
        f'<text class="mut" x="{num(right_x)}" y="{num(base_y + 16)}" {SANS} font-size="10.5" '
        f'text-anchor="end">{escape_xml(t["dayStreak"])}</text>'
    )
    return flame + number + label


class _Pills:
    """Badge pills laid out left to right, wrapping at `right`."""

    def __init__(self, left, right, top):
        self.left, self.right, self.top = left, right, top
        self.x, self.row, self.parts = left, 0, []

    def add(self, label, icon, cls="pill", icon_cls="mut", href=None):
        icon_space = 16 if icon else 0
        w = js_round(js_len(label) * 6.2) + 20 + icon_space
        if self.x + w > self.right:
            self.row += 1
            self.x = self.left
        y = self.top + self.row * 28
        icon_svg = (
            f'<path class="{icon_cls}" d="{icon}" transform="translate({num(self.x + 14)},{num(y + 10.5)}) scale(0.95)"/>'
            if icon else ""
        )
        pill = (
            f'<rect class="{cls}" x="{num(self.x)}" y="{num(y)}" width="{num(w)}" height="21" rx="10.5"/>'
            + icon_svg
            + f'<text class="mut" x="{num(self.x + 10 + icon_space)}" y="{num(y + 14.5)}" {SANS} font-size="11">{escape_xml(label)}</text>'
        )
        if href:
            pill = f'<a href="{href}" target="_blank">{pill}</a>'
        self.parts.append(pill)
        self.x += w + 8


def _add_pills(pills, data):
    if data.sponsorable:
        pills.add("Sponsor", HEART_ICON, cls="pill-sp", icon_cls="heart",
                  href=f"https://github.com/sponsors/{escape_xml(data.github_user)}")
    for b in data.badges:
        pills.add(b["label"], KIND_ICONS.get(b["kind"], KIND_ICONS["badge"]))


def _compact_footer(data, t, pad, width, y, now, static, size):
    """Keep stats and provenance on one line when they fit at the existing scale."""
    stats = []
    if data.total_actions > 0:
        stats.append((data.total_actions, t["edits"]))
    stats.append((data.total_commits, t["commits"]))
    parts, x = [], pad
    for i, (n, label) in enumerate(stats):
        prefix = " · " if i else ""
        parts.append(
            f'<text x="{num(x)}" y="{num(y)}" font-size="{num(size)}">'
            f'<tspan class="mut" {SANS}>{prefix}</tspan>'
            f'<tspan class="txt" {MONO} font-weight="700">{n}</tspan>'
            f'<tspan class="mut" {SANS}> {escape_xml(label)}</tspan></text>'
        )
        x += (len(str(n)) * .62 + len(label + prefix + " ") * .57) * size
    prov = provenance(data, t, now, static)
    if prov:
        # Monospace fine print is predictable; leave a little extra breathing room.
        inline = x + 18 + len(prov) * 9.5 * .62 <= width - pad
        if not inline:
            y += 18
        parts.append(f'<text class="faint" x="{width - pad}" y="{num(y)}" {MONO} '
                     f'font-size="9.5" text-anchor="end">{escape_xml(("· " if inline else "") + prov)}</text>')
    return "".join(parts), y


def render_full(data, theme, t, now=0, all_langs=False, static=False, split=False, *, _wide=False):
    # Both the normal card and the README body use the same design scale.
    W, PAD = README_WIDTH, WIDE_PAD if split or _wide else 24
    user = escape_xml(data.github_user)
    if data.avatar:
        avatar = (
            '<clipPath id="av"><circle cx="42" cy="36" r="17"/></clipPath>\n'
            f'  <image href="{escape_xml(data.avatar)}" x="25" y="19" width="34" height="34" clip-path="url(#av)" preserveAspectRatio="xMidYMid slice"/>\n'
            '  <circle class="avbrd" cx="42" cy="36" r="17" fill="none" stroke-width="1.5"/>'
        )
    else:
        avatar = (
            f'<circle class="pill" cx="42" cy="36" r="17"/><text class="mut" x="42" y="41" {SANS} '
            f'font-size="14" text-anchor="middle">{_initial(data)}</text>'
        )
    head_x = 68

    bar_y, bar_h, bar_w = 110, 14 if _wide else 12, W - PAD * 2
    legend_slices = data.languages if all_langs else with_other_bucket(data.languages, NAMED_LANGUAGES)
    slices = data.languages
    geo = {"x": PAD, "y": bar_y, "width": bar_w, "height": bar_h, "clampLeft": PAD, "clampRight": W - PAD}

    # Share the middle band: two legend columns on the left, 16 weeks on the right.
    heat_top = 116 if split else 140
    cell, gap = (13, 3) if _wide else (8, 2)
    grid_w = 16 * (cell + gap) - gap
    heat_x = W - PAD - grid_w
    legend_top, row_h = heat_top + 14, 22 if _wide else 21
    columns = 2
    per_column = -(-len(legend_slices) // columns) or 1
    col_w = (heat_x - PAD - 24) / columns
    col_x = [PAD + i * col_w for i in range(columns)]
    rows = []
    for i, s in enumerate(legend_slices):
        pct = to_fixed((s.total / data.total_lines) * 100, 1) if data.total_lines > 0 else "0.0"
        column = i // per_column
        cx = col_x[column] if column < len(col_x) else col_x[1]
        y = legend_top + (i % per_column) * row_h
        rows.append(
            f'<circle cx="{num(cx + 5)}" cy="{num(y - 4)}" r="4.5" fill="{slice_color(s)}"/>'
            f'<text class="txt" x="{num(cx + 17)}" y="{num(y)}" {SANS} font-size="12.5">{escape_xml(truncate(slice_label(s, t["other"]), min(16, math.floor((col_w - 65) / 7))))}'
            f'<tspan class="mut" {MONO} font-size="11.5"> {pct}%</tspan></text>'
        )
    legend = "\n  ".join(rows)
    legend_bottom = legend_top if not legend_slices else legend_top + (per_column - 1) * row_h

    heat_svg, heat_h = render_heatmap(data, heat_x, heat_top, cell, gap,
                                    **({"label_h": 13, "label_size": 9, "radius": 2.5} if _wide else {}))
    heat_bottom = heat_top + heat_h

    pinned, pinned_bottom = "", max(heat_bottom, legend_bottom + 3)
    if data.pins:
        pin_top, box_h, pin_gap = pinned_bottom + 16, 42, 10
        box_w = (bar_w - pin_gap * (len(data.pins) - 1)) / len(data.pins)
        boxes = []
        for i, p in enumerate(data.pins):
            bx = PAD + i * (box_w + pin_gap)
            star = f"★ {p['stars']}" if p.get("stars") is not None else ""
            note = truncate(p.get("note") or "", math.floor(box_w / 6.2) - (js_len(star) + 2 if star else 0))
            sub = "  ".join(x for x in (star, note) if x)
            boxes.append(
                f'<a href="https://github.com/{user}/{escape_xml(p["repo"])}" target="_blank">'
                f'<rect class="pill" x="{to_fixed(bx, 1)}" y="{num(pin_top)}" width="{to_fixed(box_w, 1)}" height="{box_h}" rx="8"/>'
                f'<path class="mut" d="{REPO_ICON}" transform="translate({to_fixed(bx + 14, 1)},{num(pin_top + 16)}) scale(0.9)"/>'
                f'<text class="txt" x="{to_fixed(bx + 28, 1)}" y="{num(pin_top + 18)}" {SANS} font-size="12" font-weight="700">{escape_xml(truncate(p["repo"], math.floor(box_w / 7.5)))}</text>'
                f'<text class="mut" x="{to_fixed(bx + 10, 1)}" y="{num(pin_top + 33)}" {SANS} font-size="10.5">{escape_xml(sub)}</text>'
                "</a>"
            )
        pinned = "\n  ".join(boxes)
        pinned_bottom = pin_top + box_h

    div_y = pinned_bottom + 16
    footer, foot_y = _compact_footer(data, t, PAD, W, div_y + 22, now, static, 12.5 if _wide else 12)

    pills = _Pills(PAD, W - PAD, foot_y + 18)
    _add_pills(pills, data)
    rows_used = pills.row + 1 if pills.parts else 0
    H = pills.top + (rows_used * 28 if rows_used > 0 else 0) + 4

    return f"""<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{W}" height="{num(H)}" viewBox="0 0 {W} {num(H)}" role="img" aria-label="devcard {user}">
  <style>{css_for(theme)}</style>
  <rect class="bg brd" x="0.5" y="0.5" width="{W - 1}" height="{num(H + 14 if split else H - 1)}" rx="14" stroke-width="1"/>

  {_wide_header(data, t) if _wide else avatar}
  {"" if _wide else f'''<g>
  <text class="txt" x="{head_x}" y="32" {SANS} font-size="15" font-weight="700">devcard</text>
  <text class="mut" x="{head_x}" y="48" {MONO} font-size="12">@{user}</text>
  <circle class="live" cx="{head_x + 66}" cy="27.5" r="4">
    <animate attributeName="opacity" values="1;0.35;1" dur="2.4s" repeatCount="indefinite"/>
  </circle>
  <a href="https://github.com/{user}?tab=repositories" target="_blank">
    <text class="link" x="{W - PAD}" y="36" {MONO} font-size="12" text-anchor="end">{data.repo_count} {escape_xml(t["repos"])} →</text>
  </a>
  </g>'''}

  {_wide_headline(data, t) if _wide else f'''<text class="txt" x="{PAD}" y="90" {MONO} font-size="30" font-weight="700">{fmt_count(data.total_lines, t["dec"])}<tspan class="mut" {SANS} font-size="12" font-weight="400"> {escape_xml(t["lines"])}</tspan><tspan class="faint" {MONO} font-size="11" font-weight="400"> ({fmt_bytes(data.total_bytes, t["dec"])})</tspan></text>
  {streak_block(data, t, W - PAD, 90)}'''}

  {"" if split else language_bar_segments(slices, data.total_lines, geo, "barclip")}

  {legend}

  {heat_svg}

  {pinned}

  <line class="brd" x1="{PAD}" y1="{num(div_y)}" x2="{W - PAD}" y2="{num(div_y)}" stroke-width="1"/>
  {footer}
  {(chr(10) + "  ").join(pills.parts)}
  {"" if split else language_bar_hover(slices, data.total_lines, geo, t["other"])}
</svg>""".replace("\n  \n", "\n\n")


# -- wide -----------------------------------------------------------------------

WIDE_W = README_WIDTH
WIDE_PAD = 28
WIDE_INNER = WIDE_W - WIDE_PAD * 2


def _wide_header(data, t):
    W, PAD = WIDE_W, WIDE_PAD
    user = escape_xml(data.github_user)
    if data.avatar:
        avatar = (
            f'<clipPath id="wav"><circle cx="{PAD + 21}" cy="40" r="21"/></clipPath>\n'
            f'  <image href="{escape_xml(data.avatar)}" x="{PAD}" y="19" width="42" height="42" clip-path="url(#wav)" preserveAspectRatio="xMidYMid slice"/>\n'
            f'  <circle class="avbrd" cx="{PAD + 21}" cy="40" r="21" fill="none" stroke-width="1.5"/>'
        )
    else:
        avatar = (
            f'<circle class="pill" cx="{PAD + 21}" cy="40" r="21"/><text class="mut" x="{PAD + 21}" y="46" {SANS} '
            f'font-size="17" text-anchor="middle">{_initial(data)}</text>'
        )
    text_x = PAD + 54
    return f"""{avatar}
  <text class="txt" x="{text_x}" y="35" {SANS} font-size="16" font-weight="700">devcard</text>
  <text class="mut" x="{text_x}" y="53" {MONO} font-size="12.5">@{user}</text>
  <circle class="live" cx="{text_x + 72}" cy="30" r="4">
    <animate attributeName="opacity" values="1;0.35;1" dur="2.4s" repeatCount="indefinite"/>
  </circle>
  <a href="https://github.com/{user}?tab=repositories" target="_blank">
    <text class="link" x="{W - PAD}" y="35" {MONO} font-size="12.5" text-anchor="end">{data.repo_count} {escape_xml(t["repos"])} →</text>
  </a>"""


def _wide_headline(data, t):
    W, PAD, y = WIDE_W, WIDE_PAD, 90
    cls = "accent" if data.streak >= 7 else "mut"
    return f"""<text class="txt" x="{PAD}" y="{y}" {MONO} font-size="32" font-weight="700">{fmt_count(data.total_lines, t["dec"])}<tspan class="mut" {SANS} font-size="13" font-weight="400"> {escape_xml(t["lines"])}</tspan><tspan class="faint" {MONO} font-size="11.5" font-weight="400"> ({fmt_bytes(data.total_bytes, t["dec"])})</tspan></text>
  <path class="{cls}" d="{FLAME_ICON}" transform="translate({W - PAD - 8},{y - 9}) scale(1.15)"/>
  <text class="txt" x="{W - PAD - 22}" y="{y}" {MONO} font-size="27" font-weight="700" text-anchor="end">{data.streak}</text>
  <text class="mut" x="{W - PAD}" y="{y + 17}" {SANS} font-size="10.5" text-anchor="end">{escape_xml(t["dayStreak"])}</text>"""


def render_wide(data, theme, t, now=0, all_langs=False, static=False, split=False):
    return render_full(data, theme, t, now, all_langs, static, split, _wide=True)


# -- banner, half, vertical -------------------------------------------------------

def _mini_bar(data, x0, y, width, height, other="other"):
    if data.total_lines <= 0:
        return f'<rect class="track" x="{num(x0)}" y="{num(y)}" width="{num(width)}" height="{num(height)}" rx="{num(height / 2)}"/>'
    parts = [
        f'<clipPath id="minibar"><rect x="{num(x0)}" y="{num(y)}" width="{num(width)}" height="{num(height)}" rx="{num(height / 2)}"/></clipPath>',
        f'<rect class="track" x="{num(x0)}" y="{num(y)}" width="{num(width)}" height="{num(height)}" rx="{num(height / 2)}"/>',
        '<g clip-path="url(#minibar)">',
    ]
    x = x0
    for s in with_other_bucket(data.languages, NAMED_LANGUAGES):
        w = (s.total / data.total_lines) * width
        parts.append(
            f'<rect x="{to_fixed(x, 2)}" y="{num(y)}" width="{to_fixed(w, 2)}" height="{num(height)}" fill="{slice_color(s)}">'
            f"<title>{escape_xml(slice_title(s, other))}</title></rect>"
        )
        x += w
    parts.append("</g>")
    return "".join(parts)


def _flame(data, cx, cy, scale):
    cls = "accent" if data.streak >= 7 else "mut"
    return f'<path class="{cls}" d="{FLAME_ICON}" transform="translate({num(cx)},{num(cy)}) scale({num(scale)})"/>'


def _avatar_circle(data, cx, cy, r, clip_id):
    if data.avatar:
        return (
            f'<clipPath id="{clip_id}"><circle cx="{num(cx)}" cy="{num(cy)}" r="{num(r)}"/></clipPath>\n'
            f'  <image href="{escape_xml(data.avatar)}" x="{num(cx - r)}" y="{num(cy - r)}" width="{num(r * 2)}" height="{num(r * 2)}" clip-path="url(#{clip_id})" preserveAspectRatio="xMidYMid slice"/>\n'
            f'  <circle class="avbrd" cx="{num(cx)}" cy="{num(cy)}" r="{num(r)}" fill="none" stroke-width="1.2"/>'
        )
    return (
        f'<circle class="pill" cx="{num(cx)}" cy="{num(cy)}" r="{num(r)}"/><text class="mut" x="{num(cx)}" y="{num(cy + 4)}" '
        f'{SANS} font-size="{num(r * 0.8)}" text-anchor="middle">{_initial(data)}</text>'
    )


def render_banner(data, theme, t):
    W, H, PAD = 480, 72, 16
    user = escape_xml(data.github_user)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-label="devcard {user}">
  <style>{css_for(theme)}</style>
  <rect class="bg brd" x="0.5" y="0.5" width="{W - 1}" height="{H - 1}" rx="12" stroke-width="1"/>
  {_avatar_circle(data, PAD + 14, 27, 14, "avb")}
  <text class="txt" x="{PAD + 36}" y="31" {MONO} font-size="13" font-weight="700">@{user}</text>
  <circle class="live" cx="{PAD + 36 + js_len(data.github_user) * 8 + 16}" cy="26.5" r="3.5">
    <animate attributeName="opacity" values="1;0.35;1" dur="2.4s" repeatCount="indefinite"/>
  </circle>
  <text x="{W - PAD}" y="31" text-anchor="end" font-size="13"><tspan class="txt" {MONO} font-weight="700">{fmt_count(data.total_lines, t["dec"])}</tspan><tspan class="mut" {SANS} font-size="11"> {escape_xml(t["lines"])}</tspan><tspan {MONO} font-size="13" font-weight="700" class="txt">  {data.streak}</tspan><tspan class="mut" {SANS} font-size="11">{escape_xml(t["streakAbbr"])}</tspan></text>
  {_flame(data, W - PAD - 118 - len(str(data.streak)) * 8, 26, 0.8)}
  {_mini_bar(data, PAD, 46, W - PAD * 2, 8)}
</svg>"""


def _stats_row(data, t, x):
    commits = (
        f'<tspan class="txt" {MONO} font-weight="700">{data.total_commits}</tspan>'
        f'<tspan class="mut" {SANS}> {escape_xml(t["commits"])}</tspan>'
    )
    edits = (
        f'<tspan class="txt" {MONO} font-weight="700">{data.total_actions}</tspan>'
        f'<tspan class="mut" {SANS}> {escape_xml(t["edits"])}</tspan><tspan {MONO}>   </tspan>'
        if data.total_actions > 0 else ""
    )
    return f'<text x="{num(x)}" y="134" font-size="11.5">{edits}{commits}</text>'


def render_half(data, theme, t):
    W, H, PAD = 480, 152, 20
    user = escape_xml(data.github_user)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-label="devcard {user}">
  <style>{css_for(theme)}</style>
  <rect class="bg brd" x="0.5" y="0.5" width="{W - 1}" height="{H - 1}" rx="12" stroke-width="1"/>
  {_avatar_circle(data, PAD + 15, 30, 15, "avh")}
  <text class="txt" x="{PAD + 40}" y="27" {SANS} font-size="13.5" font-weight="700">devcard</text>
  <text class="mut" x="{PAD + 40}" y="41" {MONO} font-size="11">@{user}</text>
  <a href="https://github.com/{user}?tab=repositories" target="_blank">
    <text class="link" x="{W - PAD}" y="31" {MONO} font-size="11.5" text-anchor="end">{data.repo_count} {escape_xml(t["repos"])} →</text>
  </a>
  <text class="txt" x="{PAD}" y="86" {MONO} font-size="24" font-weight="700">{fmt_count(data.total_lines, t["dec"])}<tspan class="mut" {SANS} font-size="11.5" font-weight="400"> {escape_xml(t["lines"])}</tspan></text>
  {_mini_bar(data, PAD, 100, W - PAD * 2, 10)}
  {_stats_row(data, t, PAD)}
  {_flame(data, W - PAD - 44 - len(str(data.streak)) * 7, 129, 0.75)}
  <text x="{W - PAD}" y="134" text-anchor="end" font-size="11.5"><tspan class="txt" {MONO} font-weight="700">{data.streak}</tspan><tspan class="mut" {SANS}> {escape_xml(t["dayStreak"])}</tspan></text>
</svg>"""


def render_vertical(data, theme, t):
    W, PAD = 280, 18
    top_langs = with_other_bucket(data.languages, NAMED_LANGUAGES)[:3]
    legend_top, row_h = 158, 20
    rows = []
    for i, s in enumerate(top_langs):
        pct = to_fixed((s.total / data.total_lines) * 100, 1) if data.total_lines > 0 else "0.0"
        y = legend_top + i * row_h
        rows.append(
            f'<circle cx="{PAD + 5}" cy="{num(y - 4)}" r="4" fill="{slice_color(s)}"/>'
            f'<text class="txt" x="{PAD + 16}" y="{num(y)}" {SANS} font-size="12">{escape_xml(truncate(slice_label(s, t["other"]), 14))}</text>'
            f'<text class="mut" x="{W - PAD}" y="{num(y)}" {MONO} font-size="11" text-anchor="end">{pct}%</text>'
        )
    legend = "\n  ".join(rows)
    legend_bottom = legend_top if not top_langs else legend_top + (len(top_langs) - 1) * row_h
    stat_y = legend_bottom + 26
    H = stat_y + 40
    user = escape_xml(data.github_user)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-label="devcard {user}">
  <style>{css_for(theme)}</style>
  <rect class="bg brd" x="0.5" y="0.5" width="{W - 1}" height="{H - 1}" rx="14" stroke-width="1"/>
  {_avatar_circle(data, W / 2, 40, 22, "avv")}
  <text class="txt" x="{num(W / 2)}" y="80" {MONO} font-size="13" font-weight="700" text-anchor="middle">@{user}</text>
  <text class="txt" x="{num(W / 2)}" y="112" {MONO} font-size="24" font-weight="700" text-anchor="middle">{fmt_count(data.total_lines, t["dec"])}</text>
  <text class="mut" x="{num(W / 2)}" y="128" {SANS} font-size="10.5" text-anchor="middle">{escape_xml(t["lines"])}</text>
  {_mini_bar(data, PAD, 138, W - PAD * 2, 8)}
  {legend}
  {_flame(data, PAD + 8, stat_y - 4, 0.8)}
  <text x="{PAD + 20}" y="{stat_y}" font-size="12"><tspan class="txt" {MONO} font-weight="700">{data.streak}</tspan><tspan class="mut" {SANS} font-size="10.5"> {escape_xml(t["dayStreak"])}</tspan></text>
  <a href="https://github.com/{user}?tab=repositories" target="_blank">
    <text class="link" x="{W - PAD}" y="{stat_y}" {MONO} font-size="11" text-anchor="end">{data.repo_count} {escape_xml(t["repos"])} →</text>
  </a>
</svg>"""
