<h1 align="center">devcard</h1>

<p align="center">
  <strong>An embeddable dev stats card built from your real AI-assisted coding activity — rendered on your machine, published to your own repository.</strong>
</p>

<p align="center">
  <a href="https://github.com/augbastos/devcard/actions/workflows/ci.yml"><img src="https://github.com/augbastos/devcard/actions/workflows/ci.yml/badge.svg" alt="ci" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="license: MIT" /></a>
  <img src="https://img.shields.io/badge/Python-3776AB?logo=python&logoColor=white" alt="Python" />
</p>

<!-- devcard:start -->
<picture><source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/augbastos/augbastos/devcard-data/card-dark.svg"><img src="https://raw.githubusercontent.com/augbastos/augbastos/devcard-data/card.svg" width="100%" alt="devcard — augbastos's coding stats, published from the devcard-data branch"></picture>
<!-- devcard:end -->

<p align="center"><em>↑ The maintainer's card, published by <code>devcard publish</code> to the <code>devcard-data</code> branch of the maintainer's profile repository.</em></p>

devcard shows **what came out of your coding sessions**. A hook records the edits
your agent makes — or, for any other tool, each commit — and your machine turns
that into a card.

Your machine renders the card and commits it to a branch of a public repository
you choose. No server, cloud account, cloud database, token or Node is needed:
the runtime is Python. Capture works offline and never blocks your session.

The card embeds anywhere an image works, with light and dark files for GitHub's
themes and English, Portuguese and Spanish text. It republishes at most every
15 minutes while you work; GitHub's raw-file caching adds up to five minutes.
See [publishing and freshness](docs/serverless.md).

## Get one

Python 3.11+, git, [pipx](https://pipx.pypa.io), and the
[GitHub CLI](https://cli.github.com) logged in (`gh auth login`). The repository
you publish to must exist and be public — your profile repository
(`<you>/<you>`) is the usual choice. devcard never creates one.

```bash
pipx install git+https://github.com/augbastos/devcard
devcard init
```

`init` checks the prerequisites, installs **one** capture hook, asks which
repository to publish to, and asks yes/no for each publication category
(default **No**). It publishes only if you authorize at least one category,
and prints a light/dark embed snippet that fills your README column.
[Embed example and commands](docs/serverless.md#commands) ·
[Card sizing](docs/customizing.md#settings)

With consent, the hooks publish by themselves. `devcard publish --force` publishes
now; `devcard render --out DIR` writes this machine's card locally without
publishing anything. On a second machine, install devcard and run `devcard init`
with the same repository — each machine publishes only its own numbers, and the
card adds them up ([details](docs/serverless.md#several-machines)).

## Choose what becomes public

**Code, file names, paths and project names never leave your machine.** Nothing
devcard publishes has a field that could hold one. Activity metadata becomes
public only with explicit consent. Six independent categories start disabled:
`languages`, `activity`, `totals`, `repo_count`, `agents` and `usage`.
Private repository counting needs an additional opt-in; roots of unknown
visibility never replace the public count.

Review grants with `devcard privacy`; change them with `--grant <category>` or
`--revoke <category>`. Card display toggles do not authorize publication or hide
consented machine JSON from readers. Each optional line requires both its
category consent and its display toggle.

`--yes` accepts setup defaults; it grants **no** consent. An old config without
`consent` pauses new publication until you review these choices through `init`
or `privacy`. No authorized category means `publish` refuses. The renderer omits
missing sections instead of displaying zero placeholders.

Revocation saves the denial locally and removes that category from every
machine's published JSON. `devcard unpublish` disables future automatic
publication on this machine and removes the verified devcard-owned branch.
Stop or revoke other machines too: their saved grants can publish again.

GitHub may keep old raw files cached or accessible by commit hash for a while
after revocation or unpublish. Neither command erases copies others downloaded.
`devcard serve` binds to `127.0.0.1` and keeps showing everything locally without
publication consent. See the [category table, CLI examples and removal
rules](docs/privacy-and-security.md#consent-review-and-removal).

## Works with your agent

Pick **one** capture mode per machine; running both would count the same lines
twice.

- **`claude`** records each edit through a Claude Code hook.
- **`git`** records real diff stats per commit, covering any tool that commits
  through git without a per-tool integration.

See [capture setup and counting rules](docs/counting.md), including agent
attribution, estimated active time, merge commits and multi-machine counts.

## Optional extras

- [Customize](docs/customizing.md) layouts, themes, language, timezone, badges
  and pinned repositories.
- [Local dashboard](docs/dashboard.md): daily tokens by agent/model family and
  API-equivalent cost estimates. Unknown prices stay unavailable; estimates are
  not subscription bills. [Scanning and usage privacy](docs/usage-and-cost.md).
- [Agent and usage card lines](docs/customizing.md#settings), plus model-family
  token shares on full/wide cards. All display toggles default off and require
  the corresponding consent.
- [Stat and milestone SVG badges](docs/badges.md) for light/dark README embeds;
  both switches default off.
- [Per-language README tooltips](docs/serverless.md#readme-language-hover):
  opt-in, daily-refreshed labels on full/wide cards, requiring language consent
  and a separate commit to your README's default branch.

## Built to be checked

CI tests Python 3.11 and 3.14 on Linux and Windows, using real SQLite and git,
renderer golden files and a pipx install. Tests need no account, secret or
network. See [development and CI](docs/development.md) and [supply-chain
checks](docs/privacy-and-security.md#supply-chain). The only runtime dependency
is `tzdata` on Windows.

## The legacy Worker

The Cloudflare Worker + D1 path remains for existing installations; the
serverless card is the recommended install. The Worker needs Python 3.11+,
Node 22+, npm, git and a Cloudflare account.
[Its setup](docs/manual-setup.md) · [its hover trick](docs/hover-in-a-readme.md) ·
[its retention notes](docs/retention.md) · [worker/README.md](worker/README.md)

## Going deeper

[Known limitations](docs/limitations.md) explains where counts fall short or
double-count. [The serverless guide](docs/serverless.md) covers file locations,
publishing, authentication and several machines.

---

Built by [Augusto Bastos](https://github.com/augbastos) · MIT
