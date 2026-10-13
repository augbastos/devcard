"""Palettes. A port of worker/src/themes.ts — keep the two in step.

`default` is light with an automatic dark override (prefers-color-scheme); the
named themes are single-look on purpose.
"""

TOKEN_KEYS = (
    "bg", "brd", "txt", "mut", "faint", "track", "sep", "pill", "pillStroke", "pillSp",
    "pillSpStroke", "heart", "link", "avbrd", "accent", "live", "heat",
)


def _tokens(*values):
    return dict(zip(TOKEN_KEYS, values, strict=True))


DEFAULT_LIGHT = _tokens(
    "#ffffff", "#d8dce4", "#1b1f27", "#6b7280", "#9aa1ac", "#edeff4", "#ffffff", "#f2f4f8",
    "#d8dce4", "#fff0f3", "#f1b8c4", "#d1355f", "#0969da", "#d8dce4", "#e8590c", "#3fb950",
    ("#ebedf0", "#9be9a8", "#40c463", "#30a14e", "#216e39"),
)
DEFAULT_DARK = _tokens(
    "#0f1117", "#262b38", "#e6e9f0", "#8b93a3", "#5b6270", "#1e2230", "#0f1117", "#171a24",
    "#262b38", "#2a1620", "#6e2a3d", "#f47892", "#58a6ff", "#262b38", "#ff922b", "#3fb950",
    ("#161b22", "#0e4429", "#006d32", "#26a641", "#39d353"),
)
DARK = _tokens(
    "#11131a", "#262b3a", "#eef0f5", "#9098ab", "#5c6478", "#1c2029", "#11131a", "#191d27",
    "#262b3a", "#2b1922", "#7a3349", "#f2789a", "#6cb6ff", "#262b3a", "#ff9d4d", "#3fd67a",
    ("#171c22", "#0f3d29", "#0e6b3a", "#22a355", "#52e08a"),
)
LIGHT = _tokens(
    "#fdfbf7", "#ddd5c8", "#211d17", "#6b6255", "#9a917f", "#efe9df", "#fdfbf7", "#f5f1e9",
    "#ddd5c8", "#fdeef1", "#eab8c4", "#c93762", "#1b6fc9", "#ddd5c8", "#d9600c", "#2ea043",
    ("#e8ecdf", "#9fe9a3", "#4cc463", "#2fa14e", "#1f6e39"),
)
GENTLE = _tokens(
    "#fdf2f0", "#e8c9d1", "#4a1f3d", "#8a5468", "#b98a9c", "#f2dde1", "#fdf2f0", "#f8e6ea",
    "#e8c9d1", "#ffe3ee", "#ef93bd", "#d6316f", "#7d4fa0", "#e8c9d1", "#e2795f", "#7cc48f",
    ("#f6dfe4", "#edc0cd", "#df8fab", "#c14f83", "#8f1457"),
)
CYBERPUNK = _tokens(
    "#0a0818", "#33224f", "#ece8ff", "#9b8fc0", "#5f5480", "#190f34", "#0a0818", "#170f2c",
    "#3a2960", "#2a0f2e", "#ff2fa8", "#ff3f8f", "#22d3ee", "#33224f", "#e2ff26", "#00ff9d",
    ("#150c2a", "#301a52", "#5c2a8a", "#a52bc4", "#ff33d6"),
)
TERMINAL = _tokens(
    "#061309", "#1c4526", "#39ff6a", "#1fbf55", "#0f6f34", "#0d2415", "#061309", "#0b2013",
    "#1c4526", "#2b1d06", "#b8860b", "#ffb000", "#4dffa3", "#1c4526", "#ffb000", "#33ff66",
    ("#0a1f10", "#134f26", "#1f8f3f", "#39cc5c", "#7dffa8"),
)

THEMES = {
    "default": {"base": DEFAULT_LIGHT, "dark": DEFAULT_DARK},
    "dark": {"base": DARK},
    "light": {"base": LIGHT},
    "gentle": {"base": GENTLE},
    "cyberpunk": {"base": CYBERPUNK},
    "terminal": {"base": TERMINAL},
}
DEFAULT_THEME = "default"

LANGUAGE_HOVER_CSS = (
    ".hit{fill:transparent;pointer-events:all}"
    ".tip{opacity:0;pointer-events:none;transition:opacity .12s ease-out}"
    ".hit:hover+.tip{opacity:1}"
)


def theme_name(name):
    return name if name in THEMES else DEFAULT_THEME


def _token_css(k):
    return (
        f".bg{{fill:{k['bg']}}}.brd{{stroke:{k['brd']}}}.txt{{fill:{k['txt']}}}"
        f".mut{{fill:{k['mut']}}}.faint{{fill:{k['faint']}}}"
        f".track{{fill:{k['track']}}}.sep{{fill:{k['sep']}}}"
        f".pill{{fill:{k['pill']};stroke:{k['pillStroke']}}}"
        f".pill-sp{{fill:{k['pillSp']};stroke:{k['pillSpStroke']}}}.heart{{fill:{k['heart']}}}"
        f".link{{fill:{k['link']}}}.avbrd{{stroke:{k['avbrd']}}}.accent{{fill:{k['accent']}}}"
        f".live{{fill:{k['live']}}}"
        f".tipbg{{fill:{k['pill']};stroke:{k['pillStroke']}}}.tiptx{{fill:{k['txt']}}}"
        + "".join(f".heat{i}{{fill:{c}}}" for i, c in enumerate(k["heat"]))
    )


def css_for(theme):
    css = _token_css(theme["base"])
    if theme.get("dark"):
        css += f"@media(prefers-color-scheme:dark){{{_token_css(theme['dark'])}}}"
    return css + LANGUAGE_HOVER_CSS
