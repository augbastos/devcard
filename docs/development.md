# Running the tests

```bash
python -m unittest discover -s hook -p "test_*.py"    # hook + git integration
cd worker && npm ci && npm run typecheck && npm test  # Worker, workerd + local D1
```

The Worker suite runs inside workerd against a real local D1 through
[`@cloudflare/vitest-pool-workers`](https://developers.cloudflare.com/workers/testing/vitest-integration/),
so ingest, the unique index, the cache key, the split card's geometry and the
rollup rebuild are exercised by the engine production uses. No Cloudflare
account, secret or network access is involved; github.com is stubbed at the
outbound boundary.

The Python suite builds throwaway git repositories and runs real `git` against
them — the merge and hook-installation behaviour it pins is behaviour of git,
which a mock would only have agreed with.

[`.github/workflows/ci.yml`](../.github/workflows/ci.yml) runs both on every
pull request and on `master`, with the hook suite on Python 3.9, 3.11 and 3.13.
The `scpe` workflows next to it check that a pull request discloses AI use; they
say nothing about whether the code works.

## A trap worth knowing about

`wrangler deploy --dry-run` does not catch a Worker that fails at *startup*.
workerd validates every named export of the entrypoint module and rejects
anything that is not a handler, so exporting a plain constant from
`worker/src/index.ts` passes the typecheck, passes the test suite, passes
`--dry-run`, and then fails the deployed Worker with `Incorrect type for map
entry`. That is why shared constants live in `worker/src/variants.ts`, and why
a `wrangler dev` boot check is worth running before a release.
