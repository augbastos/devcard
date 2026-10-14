# Development and CI

## Running the tests

```bash
python -m unittest discover -s hook -p "test_*.py"    # hook, git integration, installer
python -m unittest discover -s tests -t .              # devcard package: renderer, publish, init
pipx run ruff==0.16.7 check .                          # Python lint (rules in ruff.toml)

cd worker
npm ci                                                 # the locked toolchain
npm run typecheck                                      # src and test
npm test                                               # Worker, in workerd + local D1
```

The Python side is standard library only, so there is nothing to install for it
(on Windows, `pip install tzdata` for the tests that render in a fixed timezone).
`python -m devcard ...` runs the command line from a checkout.

## Golden files

`tests/golden/` holds 46 SVGs rendered by the legacy Worker's TypeScript renderer,
and `tests/golden/fixtures.json` the events they were rendered from.
`worker/test/golden.test.ts` sends those events through the Worker's real
`/ingest` and renders every listed variant through `/svg` with the clock pinned;
`tests/test_golden.py` loads the same events into a real hook database and
renders them with `devcard/`. Both compare against the same files (the Python
side normalises whitespace; today the outputs are byte-identical).

So a change to either renderer fails a suite until the other matches or the files
are regenerated on purpose:

```bash
cd worker && npx vitest run test/golden.test.ts -u    # rewrite tests/golden/ from the Worker
```

Commit the regenerated files together with the matching change in `devcard/`.

The Worker suite runs inside workerd against a real local D1 through
[`@cloudflare/vitest-plugin`](https://developers.cloudflare.com/workers/testing/vitest-integration/),
so ingest, the unique index, the cache key, the split card's geometry and the
rollup rebuild are exercised by the engine production uses. It reads the
tracked `wrangler.example.jsonc`, with the token, username and timezone fixed in
`vitest.config.mts`: no Cloudflare account, secret or network access is
involved, and a local `.dev.vars` cannot change what a test sees. github.com is
stubbed at the outbound boundary; anything unexpected comes back as a 599.

The Python suite builds throwaway git repositories and runs real `git` against
them — the merge and hook-installation behaviour it pins is behaviour of git,
which a mock would only have agreed with. The installer is run end to end
against a fake Node/npm/Wrangler, which is how its ordering (every check before
any change, the Worker secret before its local copy) and its re-run path are
tested without an account.

Supported versions are defined once each: `MIN_PYTHON` in `install.py` (mirrored
by `devcard/cli.py` and `requires-python` in `pyproject.toml`) and `engines.node`
in `worker/package.json`. A test fails if CI's matrix, the README or those
mirrors stop matching them.

## What CI checks

| Workflow | Job | Why it exists |
|---|---|---|
| `ci` | `hook` | The hook, installer and `devcard` package suites on Ubuntu **and Windows**, Python 3.11 and 3.14. Windows differs for real: process detaching, drive-letter paths, ACLs instead of mode bits. |
| `ci` | `package` | `pipx install .`, then `devcard --version`, a render, and an import of every hook module the way the hooks run (`python -S`). |
| `ci` | `python lint` | Ruff's correctness rules and bugbear. |
| `ci` | `worker` | `npm ci`, typecheck, the workerd suite, and a `wrangler deploy --dry-run` bundle, on Node 22 and 24. |
| `ci` | `ci-ok` | The single check the ruleset requires from this workflow, so a matrix change never leaves a required check that no job reports. |
| `security` | `secrets` | Gitleaks over the whole history. |
| `security` | `dependencies` | Dependency review: a pull request adding a known-vulnerable package fails. |
| `security` | `codeql` | CodeQL for TypeScript, Python and the workflow files. |
| `scpe` / `scpe-seal` | `verify` | Fails a pull request that does not disclose AI use (Dependabot excepted); `scpe-seal` comments with the reason. Says nothing about whether the code works. |

The required checks on `main` are `ci-ok`, `secrets`, `dependencies` and `verify`.

How the workflows are kept safe:

- every `uses:` is a full commit SHA, with the release in a comment, and
  Dependabot updates both;
- the default token is read-only; a job asks for exactly the scope it uses;
- `persist-credentials: false` on every checkout;
- nothing from a pull request is interpolated into a shell script — values reach
  `run:` through environment variables;
- no job holding a write token runs contributor code: `codeql` checks it out
  only to analyse it, without building (`build-mode: none`), and `scpe-seal`
  never checks it out — it validates the pull request number from the artifact
  and posts SCPE's rendered comment as-is.

## The weekly README refresh

`.github/workflows/devcard-readme.yml` regenerates the hoverable card block in
the README. `main` only accepts pull requests, so the workflow opens one — or
updates the one already open — on the branch `bot/refresh-readme-card`, using
[peter-evans/create-pull-request](https://github.com/peter-evans/create-pull-request).
When the block has not changed, it does nothing.

It needs a GitHub App token rather than `GITHUB_TOKEN`, because GitHub does not
start workflows for events `GITHUB_TOKEN` causes: a pull request it opened would
never receive its required checks. To set it up once:

1. Create a GitHub App (Settings → Developer settings → GitHub Apps) with no
   webhook and two repository permissions: **Contents: read and write** and
   **Pull requests: read and write**. Install it on this repository only.
2. Create the environment `readme-bot` (Settings → Environments) with
   deployment branches limited to `main`. In it, store the App's Client ID as
   the **variable** `DEVCARD_BOT_CLIENT_ID` and a generated private key as the
   **secret** `DEVCARD_BOT_PRIVATE_KEY`. A workflow on any other branch cannot
   read them.

Until both exist, the workflow writes whether the README is stale to its run
summary and changes nothing. The token it mints is limited to those two
permissions on this repository and expires when the job ends.

## A trap worth knowing about

`wrangler deploy --dry-run` does not catch a Worker that fails at *startup*.
workerd validates every named export of the entrypoint module and rejects
anything that is not a handler, so exporting a plain constant from
`worker/src/index.ts` passes the typecheck, the test suite and `--dry-run`, and
then fails the deployed Worker with `Incorrect type for map entry`. That is why
shared constants live in `worker/src/variants.ts`, and why a `npm run dev` boot
check is worth running before a release.
