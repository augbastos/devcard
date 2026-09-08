# Making it yours

MIT licensed, and built to be forked. There is no framework and no build step
for the card itself — the SVG is plain template strings.

| Want to change | Look in |
|---|---|
| Colours and themes | `worker/src/themes.ts` — a theme is a handful of hex values |
| Layout | `worker/src/render.ts` (`full`), `render-wide.ts`, `render-layouts.ts` |
| The split bar a README hovers | `worker/src/render-split.ts` |
| Language detection | `EXT_LANGUAGE` in `hook/devcard_lib.py` |
| Language colours | `LANGUAGE_COLORS` in `worker/src/svg-utils.ts` |
| Strings and locales | `STRINGS` in `worker/src/variants.ts` — a locale is ~1 line |

A new theme is about 20 lines of tokens. PRs welcome.

## Badges, certifications, awards

Manual, self-declared entries, rendered as pills with icons — star for a badge,
seal for a certification, trophy for an award:

```bash
cd worker
npx wrangler d1 execute devcard --remote --command \
  "INSERT INTO profile_entries (kind, label, detail, created_at) VALUES ('certification', 'AWS Cloud Practitioner', NULL, strftime('%s','now'))"
```

`kind` is one of `badge` | `certification` | `award`.

## Pinned repos

Up to three, each a linked box with a live star count:

```bash
npx wrangler d1 execute devcard --remote --command \
  "INSERT INTO pinned_repos (repo, note, position, created_at) VALUES ('wavr', 'privacy-first home presence', 1, strftime('%s','now'))"
```

`repo` must be a public repo under your GitHub account, `note` is an optional
one-liner, and the lowest `position` renders first.
