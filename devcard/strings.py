"""Card wording per language. A port of STRINGS in worker/src/variants.ts.

`updatedOn` is new here and has no Worker counterpart: a published card is a
static file, so "updated 5min ago" would be frozen into it and turn false within
minutes. The static card states the date instead (see render.provenance).
"""

STRINGS = {
    "en": {
        "lines": "lines written", "edits": "code edits", "commits": "commits", "repos": "repos",
        "since": "tracking since", "events": "events", "dayStreak": "day streak", "streakAbbr": "d",
        "updatedAgo": "updated {X} ago", "updatedOn": "updated {X}", "dec": ".", "other": "other",
        "locale": "en",
    },
    "pt": {
        "lines": "linhas escritas", "edits": "edições de código", "commits": "commits",
        "repos": "repos", "since": "medindo desde", "events": "eventos",
        "dayStreak": "dias seguidos", "streakAbbr": "d", "updatedAgo": "atualizado há {X}",
        "updatedOn": "atualizado em {X}", "dec": ",", "other": "outras", "locale": "pt",
    },
    "es": {
        "lines": "líneas escritas", "edits": "ediciones de código", "commits": "commits",
        "repos": "repos", "since": "midiendo desde", "events": "eventos",
        "dayStreak": "días seguidos", "streakAbbr": "d", "updatedAgo": "actualizado hace {X}",
        "updatedOn": "actualizado el {X}", "dec": ",", "other": "otras", "locale": "es",
    },
}
DEFAULT_LANG = "en"

# What `Intl.DateTimeFormat(locale, { month: "short" })` prints, so the heatmap's
# month labels match the Worker's without an ICU dependency.
MONTHS = {
    "en": ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"),
    "pt": ("jan.", "fev.", "mar.", "abr.", "mai.", "jun.", "jul.", "ago.", "set.", "out.", "nov.", "dez."),
    "es": ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sept", "oct", "nov", "dic"),
}


def lang_name(name):
    return name if name in STRINGS else DEFAULT_LANG
