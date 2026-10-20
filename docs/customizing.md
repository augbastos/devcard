# Making it yours

MIT licensed, and built to be forked. There is no framework and no build step
for the card itself — the SVG is plain template strings.

## Settings

`~/.claude/devcard/config.json`, written by `devcard init`:

```json
{
  "github_user": "octo-cat",
  "repo": "octo-cat/octo-cat",
  "remote": "",
  "layout": "full",
  "theme": "default",
  "lang": "en",
  "timezone": "",
  "avatar": true,
  "usage": true,
  "card": {"show_agents": false, "show_usage": false, "show_models": false},
  "stat_badges": false,
  "milestone_badges": false,
  "badges": [{"kind": "certification", "label": "AWS Cloud Practitioner"}],
  "pins": [{"repo": "my-project", "note": "what it does, in a line"}]
}
```

| Key | Values |
|---|---|
| `layout` | `full` (480 wide), `wide` (840), `banner` (480×72), `half` (480×152), `vertical` (280) |
| `theme` | `default` (published as its light and dark halves), `dark`, `light`, `gentle`, `cyberpunk`, `terminal` |
| `lang` | `en`, `pt`, `es` |
| `timezone` | An IANA zone such as `Europe/Dublin`; empty means this machine's local time |
| `badges` | Up to 8 pills. `kind` is `badge`, `certification` or `award` (star, seal, trophy) |
| `pins` | Up to 3 linked boxes for repositories under your account. No star count: that would need the GitHub API at every publish |
| `remote` | A git URL to push to instead of `https://github.com/<repo>.git`, e.g. SSH |
| `usage` | Default `true`; `false` skips transcript discovery/scanning. Previously stored aggregates are retained and still published. |
| `card.show_agents` | Default `false`; show each agent's percentage of recorded lines added and estimated active hours. Concurrent agents are counted independently. |
| `card.show_usage` | Default `false`; show recorded tokens and an approximate API-equivalent USD estimate. Unknown or partially priced totals show “—”. |
| `card.show_models` | Default `false`; thin token-share bar and family legend on full/wide cards, including README hover bodies. Requires usage consent and positive tokens. |
| `stat_badges` | Default `false`; write eligible lines, streak, language and tokens SVG badges. Each needs its category consent. |
| `milestone_badges` | Default `false`; write eligible lines/streak milestones, polyglot and multi-agent badges. See [badges](badges.md). |

Changes show on the next publish; `devcard publish --force` to see them now.

Both optional lines extend the Python card's height in every layout. With
both off, output keeps the original golden SVG bytes. They do not change the
legacy Worker. Usage is published in machine JSON regardless of display flags;
turning scanning off does not erase previously stored data.

The model bar sums input, output, cache read and cache write tokens, just like
the usage line. It appears directly below that line when both are enabled,
or on its own when `show_usage` is off. Families below 1% fold into Other;
unknown models also appear as Other. Opus, Sonnet and Haiku use terracotta
shades, GPT and o-series use green, and Other uses the theme's neutral grey.
Banner, half and vertical layouts skip the model bar and keep their existing
output. All three display toggles require their matching consent categories;
none authorizes publication on its own.

`devcard badges --stats/--no-stats --milestones/--no-milestones` controls the
two independent badge switches locally. The manual `badges` list keeps its
existing meaning. `devcard render --out DIR` also writes eligible badge SVGs.

## Changing the card itself

| Want to change | Look in |
|---|---|
| Colours and themes | `devcard/themes.py` — a theme is a handful of hex values |
| Layout | `devcard/render.py` |
| Language detection | `EXT_LANGUAGE` in `hook/devcard_lib.py` |
| Language colours | `LANGUAGE_COLORS` in `devcard/svg.py` |
| Strings and locales | `devcard/strings.py` — a locale is a few lines, plus its month names |

The Python renderer is held byte for byte to golden files made by the legacy
Worker's renderer (`tests/golden/`), so a deliberate change to the look is made
in both, or the golden files are regenerated from the Worker and the difference
documented. See [development](development.md#golden-files).

## The legacy Worker

On the Worker, the same things live in `worker/src/` (`themes.ts`, `render*.ts`,
`svg-utils.ts`, `variants.ts`), and badges and pinned repos are rows in D1:

```bash
cd worker
npx wrangler d1 execute devcard --remote --command \
  "INSERT INTO profile_entries (kind, label, detail, created_at) VALUES ('certification', 'AWS Cloud Practitioner', NULL, strftime('%s','now'))"
npx wrangler d1 execute devcard --remote --command \
  "INSERT INTO pinned_repos (repo, note, position, created_at) VALUES ('my-project', 'what it does, in a line', 1, strftime('%s','now'))"
```
