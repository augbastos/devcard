# Hover, and how it reaches a GitHub README

README hover works with the [serverless card](serverless.md#readme-language-hover).
Enable it with `devcard readme --enable`, grant `languages` publication consent,
and put the devcard markers around your card in the publish repository's
default-branch `README.md`. No Worker is required.

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
measured against GitHub's rendered markdown in September 2026, not assumed.
GitHub's sanitizer and CSS are not a contract, so this is a snapshot:

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

`devcard publish` keeps the full card unchanged for normal embeds and writes
`lang/body.svg`, `lang/body-dark.svg`, language slices and end caps on the
`devcard-data` branch. The README contains one `<p>` with the body `<picture>`
at `width="100%"`, followed immediately by the left cap, per-language slices
and right cap. Every image uses `align="top"`, with no whitespace between tags.
Each slice's
`<img>` carries its own `title` with the language name and true share, and each
picture has a dark source. The language/Other grouping and colours reuse the
card's helpers. All image URLs point to `raw.githubusercontent.com`.

The body has no language bar; the legend moves up to close that space while
the heatmap, footer and other content remain. Its frame extends below the
viewBox, clipping away the bottom border and rounded bottom corners. The
34px strip supplies the bar, space around it, bottom border and corners.
Both rows share the 712px canvas, 28px padding, background, border and 14px
corner radius, so together they form one card.

The body fills the column and the strip's percentages sum to 100%. At an 830px
display width, both rows scale by 830/712 ≈ 1.166×, matching the former 480px
card at 560px. They scale together on narrower screens; no fixed pixel display
width is needed in the README.

`full` and `wide` support this split, including partial-consent cards with a
language section. Other layouts and cards without languages fall back to the
normal single-image embed, without per-language README tooltips or hover files.

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

Each slice is floored at 4px at the nominal 712px card width, paid for out of
the segments that have pixels to spare. Measured on the original Worker card: seven of its eighteen
languages draw thinner than that floor, five of them under a single pixel and
two under a tenth of one — Java at 0.09px, Ruby at 0.007px. A bar that draws
them honestly draws them invisible, and nothing can point at 0.007px. The
percentage in each tooltip is still the true share; only the pixels move, and
the largest language gives up around a point of the card's width to pay for it.

The single-image embed is still exactly proportional, and still works
everywhere. It just cannot hover.

## Using it

Hover defaults to off. `devcard init` asks separately after the consent questions,
default No; unattended setup can pass `--readme-hover`. For an existing setup:

```bash
devcard privacy --grant languages
devcard readme --enable
```

```html
<!-- devcard:start -->
Your existing card snippet goes here.
<!-- devcard:end -->
```

Run `devcard publish --force` to publish the images and fill the marked block.
Later publications update the images while you work. The widths and tooltip
text are HTML attributes, so refreshing those requires a README commit.
devcard makes `devcard: refresh language bar` only when the block changed and
more than 24 hours have passed since this machine's last successful README
update for the target. Both markers must exist; everything outside them and
the README's line endings are preserved.

If the default branch rejects the update, the card publication still succeeds.
A local log line reports the rejection, and README retries wait 24 hours,
including with `publish --force`. This can happen when branch protection
requires a pull request. Missing markers and invalid UTF-8 or non-regular
README files have separate local hints and are left untouched.

`devcard readme --disable` stops README updates; the next data publish removes
the hover images. Remove the marked block manually if needed. For details on
daily timing, independent machine state, stale slice URLs and retained history,
see [README language hover](serverless.md#readme-language-hover).
