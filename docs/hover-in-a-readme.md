# Hover, and how it reaches a GitHub README

The card's language bar names the language under the pointer. Getting that to
work inside a README meant giving up the idea that a card is one image. This
file records the measurements behind that, so the next person does not have to
re-derive them.

## Two kinds of hover

**Where the SVG is a document** — the card's URL opened directly, or embedded
with `<object data="…" type="image/svg+xml">` — the card carries its own hover
layer. Every language gets an invisible target at least 3px wide, paid for out
of the segments that have pixels to spare, so the targets tile the bar exactly
and never overlap. The drawn bar is untouched and stays exactly proportional.

**Inside a GitHub README** none of that is reachable, and the card gets there
another way.

## Why the obvious approaches fail

GitHub renders an embed through an `<img>`, and browsers put SVG-in-`<img>` in
secure static mode: no pointer event reaches the document. Every element that
could carry the interaction instead is removed by GitHub's HTML sanitizer —
measured against GitHub's own markdown renderer, not assumed:

| | in a README |
|---|---|
| `<object>`, `<embed>`, `<iframe>` | stripped |
| inline `<svg>`, `<style>` | stripped |
| `<map>` / `<area>` (image map) | stripped |
| `usemap` on `<img>` | kept, but its `<map>` is gone, so it does nothing |
| `title` on `<img>` | **kept** — and it is a real tooltip |
| `<details>` / `<summary>` | **kept**, including images inside |

Declarative animation *does* run in secure static mode, which is why the live
dot pulses in a README while hover does nothing.

## The shape that works

A `title` names a whole image, so one image can only ever have one tooltip. The
bar therefore has to stop being part of the same image as the rest of the card.

`?part=` serves the wide card as a body, two end caps and one slice per
language. The README tiles them into a row, and each slice carries its own
`title`. Point at Ruby's sliver and it says Ruby.

Three measurements on a rendered README fixed the geometry:

- Adjacent `<img>` tags with **no whitespace between them** tile with a gap of
  exactly 0, and percentage widths span the column exactly. A newline between
  two tags becomes a space, and a space becomes a visible seam — which is why
  the generated block is one long line.
- `align="left"` stacks rows with no vertical gap, but GitHub's CSS gives
  `img[align=left]` a `padding-right: 20px`, which blows a horizontal row apart.
  `align="top"` stacks with no gap and adds no padding, so every piece uses it.
- A paragraph always reserves a 24px line box, so a row of short images leaves
  ~12px of slack **after** it. That is why the bar is the card's last row: the
  slack falls below the card, where nothing shows it. Anywhere else it would
  open a gap inside the card on a narrow column.

Widths travel as integer ten-thousandths of a percent. Summing rounded floats
drifted to 100.00000000000001, and a total a hair over 100% wraps the last slice
onto its own line — the one failure here that looks broken rather than merely
imprecise.

## The price

Each slice is floored at 4px, paid for out of the segments that have pixels to
spare. Without it, on a real account, eight languages sit under a pixel and
three under a tenth of one: a bar that draws them honestly draws them invisible,
and nothing can point at 0.03px. The percentage in each tooltip is the true
share; only the pixels move. On the card in this repository's README, the
largest language gives up about 1.2 points of the card's width for it.

The single-image embed is still exactly proportional, and still works
everywhere. It just cannot hover.

## Using it

Ask the Worker for the block and paste it between two markers:

```bash
curl https://<your-worker-url>/embed?user=<you>
```

```html
<!-- devcard:start -->
…the block…
<!-- devcard:end -->
```

The widths and the tooltip text are HTML attributes, so they live in your README
and cannot follow your data on their own.
[`.github/workflows/devcard-readme.yml`](../.github/workflows/devcard-readme.yml)
regenerates them weekly with
[`scripts/refresh_readme.py`](../scripts/refresh_readme.py).

Weekly rather than daily because every slice's pixels are fetched live on each
view: what drifts between runs is only the proportions and the percentages, and
a language mix does not move far in a week. If the card is unreachable, the
script leaves the last good block in place rather than emptying the README.
