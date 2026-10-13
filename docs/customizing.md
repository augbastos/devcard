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

Changes show on the next publish; `devcard publish --force` to see them now.

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
