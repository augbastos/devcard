# Development and CI

## Running the tests

```bash
python scripts/run_tests.py                            # all Python modules, parallel processes
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

CI runs the Python modules in separate processes, up to the CPU count in the
same job. Each module keeps its existing fixtures and assertions; temporary
repositories and databases are independent, HTTP tests use ephemeral ports,
and process-local mocks cannot leak into another module. The runner prints
per-module elapsed time and fails if any module fails or cannot start. Use
`python scripts/run_tests.py --jobs 1` for a sequential timing comparison.
The OS/runtime matrix and the `ci-ok` aggregate stay unchanged. Dependency
caches use the pinned CI requirements and the Worker's npm lockfile; only
superseded pull-request runs are cancelled.

## Golden files

`tests/golden/` holds the original 46 SVGs rendered by the legacy Worker's TypeScript renderer,
and `tests/golden/fixtures.json` the events they were rendered from.
`worker/test/golden.test.ts` sends those events through the Worker's real
`/ingest` and renders every listed variant through `/svg` with the clock pinned;
`tests/test_golden.py` loads the same events into a real hook database and
renders them with `devcard/`. Compact Python layouts still compare against the
same files (normalising whitespace). Python `full` and `wide` now use a 712px
README canvas and compare against separately generated SVGs in
`tests/golden/readme/`. The original files remain the Worker's references.

Regenerate references deliberately after a renderer change:

```bash
cd worker && npx vitest run test/golden.test.ts -u    # rewrite tests/golden/ from the Worker
python scripts/regenerate_readme_goldens.py          # from repo root: Python full/wide + opt-in hashes
```

Include regenerated files together with the matching renderer change. The
Python generator leaves all legacy references untouched.

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
which a mock would only have agreed with. Publishing uses temporary bare
repositories; hook integration covers merges, worktrees, `core.hooksPath`,
husky and paths with spaces. The installer is run end to end
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

The workflows define `ci-ok`, `secrets` and `dependencies` as required checks.

How the workflows are kept safe:

- every `uses:` is a full commit SHA, with the release in a comment, and
  Dependabot updates both;
- the default token is read-only; a job asks for exactly the scope it uses;
- `persist-credentials: false` on every checkout;
- nothing from a pull request is interpolated into a shell script — values reach
  `run:` through environment variables;
- no job holding a write token runs contributor code: `codeql` checks it out
  only to analyse it, without building (`build-mode: none`).

## The README card block

The README hover block is refreshed by `devcard publish` on the maintainer's
machine (opt-in `readme_hover`, at most one README commit a day; see
[docs/hover-in-a-readme.md](hover-in-a-readme.md)). The former weekly
`devcard-readme.yml` workflow, which regenerated the block from the legacy
Worker, was retired once the README stopped embedding Worker images.

## A trap worth knowing about

`wrangler deploy --dry-run` does not catch a Worker that fails at *startup*.
workerd validates every named export of the entrypoint module and rejects
anything that is not a handler, so exporting a plain constant from
`worker/src/index.ts` passes the typecheck, the test suite and `--dry-run`, and
then fails the deployed Worker with `Incorrect type for map entry`. That is why
shared constants live in `worker/src/variants.ts`, and why a `npm run dev` boot
check is worth running before a release.
