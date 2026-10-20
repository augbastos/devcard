# Stat and milestone badges

Badges are optional SVG files built locally from the same consented data as
your card. Both switches default to `false`. They are separate from the
existing `badges` list of manual pills on the card.

```bash
devcard badges --stats --milestones
devcard render --out preview
```

`devcard badges` shows the saved switches. `--no-stats` and `--no-milestones`
disable them independently. `devcard init` asks about each after the README
hover question; `init --yes` keeps both off. A switch never grants consent.
Grant only the categories you want to publish through `devcard privacy`.

Each eligible badge has `badges/<name>.svg` and `badges/<name>-dark.svg` on the
`devcard-data` branch after the next publish. The local render command writes
the same files without publishing. There are no requests to a badge service.

| File name | Required consent | Value |
|---|---|---|
| `lines` | `totals` | Total recorded lines added |
| `streak` | `activity` | The card's current day streak |
| `language` | `languages` | Top language and share of recorded language lines |
| `tokens` | `usage` | Input + output + cache read + cache write tokens |
| `milestone-lines` | `totals` | Highest reached: 100k, 1M or 10M lines added |
| `milestone-streak` | `activity` | Highest reached: 7, 30 or 90 consecutive days with positive lines |
| `polyglot` | `languages` | At least five languages, each with at least 1% of recorded language lines |
| `multi-agent` | `agents` | Both Claude Code and Codex have positive recorded lines added |

The first four need `stat_badges: true`; the last four need
`milestone_badges: true`. The tokens badge is omitted when tokens are zero,
and the language badge when no language data is available. A milestone below
its first threshold is omitted. Only the highest reached lines or streak
milestone is emitted, for example `1M lines` or `30-day streak`.

Streak milestones use the **longest** run in the published day window (the
last 126 days), including runs before a pause. They can disappear as those
days leave the window. This differs from the current streak on the card and
the stat badge. Polyglot counts all qualifying languages, including those
grouped under Other in the card legend. Multi-agent counts only the two
coding agents; git capture and unknown attribution do not qualify.

Polyglot uses unrounded counts when they are available: exactly 1.00% qualifies.
With languages consent alone, machine files contain percentages rounded to
one decimal place. A displayed 1.0% could mean less than 1%, so only values
strictly greater than 1.0% qualify in this case. These rounded percentages are
not normalized again for eligibility. When combining sources with rounded
percentages, a language must qualify in every contributing source, because
their absolute weights are unavailable. This conservative fallback may omit
a qualifying badge, but cannot promote a language just because of rounding.
The eligibility information is derived internally; published machine JSON
still contains only the already-consented percentages, with no extra fields
or absolute line counts.

Disabling a switch or revoking a category removes its badge files on the next
successful publish. Existing downloads and cached images may remain visible.

## Embed in a README

Replace `<owner>` and `<repo>` with your publication repository. Any of the
eight names above can replace `lines`:

```html
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/<owner>/<repo>/devcard-data/badges/lines-dark.svg">
  <img alt="devcard lines" src="https://raw.githubusercontent.com/<owner>/<repo>/devcard-data/badges/lines.svg">
</picture>
```

For a single light file:

```markdown
![devcard lines](https://raw.githubusercontent.com/<owner>/<repo>/devcard-data/badges/lines.svg)
```

Only embed badges that are eligible for your data and consents, to avoid
broken image links.
