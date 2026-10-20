"""Small local SVG badges derived only from opted-in, consented card data."""
from . import config
from .jsfmt import js_round
from .svg import escape_xml, fmt_count

BADGE_NAMES = ("lines", "streak", "language", "tokens", "milestone-lines", "milestone-streak", "polyglot", "multi-agent")


def badge_svg(label: str, value: str, colour: str, dark: bool) -> str:
    """A 20px two-block shield, sized with a fixed character-width estimate."""
    left, right = len(label) * 7 + 12, len(value) * 7 + 12
    width = left + right
    accessible = escape_xml(f"{label}: {value}")
    # Keep the label's familiar grey; a dark variant has a lighter border and
    # no light-theme gradient, so either file is readable on its background.
    border = "#8b93a3" if dark else "#000000"
    opacity = ".18" if dark else ".12"
    gradient = "" if dark else (
        '<linearGradient id="shine" x2="0" y2="100%"><stop offset="0" stop-color="#fff" stop-opacity=".1"/>'
        '<stop offset="1" stop-opacity=".1"/></linearGradient>'
    )
    overlay = "" if dark else f'<rect width="{width}" height="20" fill="url(#shine)"/>'
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="20" '
        f'viewBox="0 0 {width} 20" role="img" aria-label="{accessible}">'
        f'<title>{accessible}</title><defs><clipPath id="badge-clip"><rect width="{width}" height="20" rx="3"/>'
        f'</clipPath>{gradient}</defs><g clip-path="url(#badge-clip)">'
        f'<rect width="{left}" height="20" fill="#555"/>'
        f'<rect x="{left}" width="{right}" height="20" fill="{escape_xml(colour)}"/>{overlay}</g>'
        f'<rect x=".5" y=".5" width="{width - 1}" height="19" rx="3" fill="none" '
        f'stroke="{border}" stroke-opacity="{opacity}"/>'
        '<g fill="#fff" text-anchor="middle" font-family="Verdana,DejaVu Sans,sans-serif" font-size="11">'
        f'<text x="{left / 2:g}" y="14">{escape_xml(label)}</text>'
        f'<text x="{left + right / 2:g}" y="14">{escape_xml(value)}</text></g></svg>'
    )


def badge_files(card, cfg) -> dict[str, bytes]:
    """Only the fixed badge names, gated by both their switch and category."""
    allowed = config.consents(cfg)
    stats = cfg.get("stat_badges") is True
    milestones = cfg.get("milestone_badges") is True
    files = {}

    def add(name, category, value, colour, enabled):
        if not enabled or not allowed[category] or category not in card.sections:
            return
        for dark in (False, True):
            suffix = "-dark" if dark else ""
            files[f"badges/{name}{suffix}.svg"] = badge_svg("devcard", value, colour, dark).encode("utf-8")

    add("lines", "totals", f"{fmt_count(card.total_lines, '.')} lines", "#3572A5", stats)
    add("streak", "activity", f"{card.streak}-day streak", "#B45309", stats)
    if card.languages and card.language_total > 0:
        top = card.languages[0]
        add("language", "languages", f"{top.language} {js_round(top.total / card.language_total * 100)}%",
            "#52637A", stats)
        eligible = card.polyglot_eligible_languages
        count = sum((s.total * 100 >= card.language_total if eligible is None else s.language in eligible)
                    for s in card.languages if not s.is_other)
        if count >= 5:
            add("polyglot", "languages", f"Polyglot · {count} languages", "#6F42A1", milestones)
    tokens = sum(card.model_tokens.values())
    if tokens > 0:
        add("tokens", "usage", f"{fmt_count(tokens, '.').upper()} tokens", "#0B7A5F", stats)
    for threshold, label in ((10_000_000, "10M lines"), (1_000_000, "1M lines"), (100_000, "100k lines")):
        if card.total_lines >= threshold:
            add("milestone-lines", "totals", label, "#3572A5", milestones)
            break
    for threshold in (90, 30, 7):
        if card.longest_streak >= threshold:
            add("milestone-streak", "activity", f"{threshold}-day streak", "#B45309", milestones)
            break
    if all(card.agent_totals.get(agent, {}).get("lines_added", 0) > 0 for agent in ("claude-code", "codex")):
        add("multi-agent", "agents", "Multi-agent · Claude Code + Codex", "#7C4A32", milestones)
    return files
