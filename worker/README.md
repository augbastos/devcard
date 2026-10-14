# devcard worker

> **Legacy.** The recommended devcard no longer needs this Worker: the card is
> rendered by the `devcard` Python package and published to a branch of your own
> repository (see [docs/serverless.md](../docs/serverless.md)). This directory
> stays, tested and deployable, until the existing Worker card is migrated. Its
> renderer also produces the golden SVGs the Python renderer is held to
> (`test/golden.test.ts` → `../tests/golden/`).

Temporary compatibility redirect, approved for three months: `GET /svg` returns
301 to `devcard-data/card.svg` on raw.githubusercontent.com (`theme=dark` selects
`card-dark.svg`), cached for one hour. Other query parameters are ignored.
`GET /`, `/embed` (including subpaths), and `.html` routes redirect to
https://github.com/augbastos/devcard. At `RETIRE_AT` (2027-01-14 00:00 UTC),
`/svg` starts returning 410 Gone. HEAD follows the same status and headers.
`POST /ingest`, its fail-closed authentication, and the nightly rollup rebuild
remain unchanged, including after that date. Retained renderers and golden
tests use a test-only rendering harness instead of the public routes.

## Working on it

```bash
npm ci                # the locked toolchain — do this before anything else
npm run typecheck     # tsc over src and test
npm test              # Vitest inside workerd, against a local D1
npm run dev           # wrangler dev — needs wrangler.jsonc (below)
npm run deploy        # wrangler deploy
```

`npm test` needs no Cloudflare account, no secret and no network: it runs in
workerd through `@cloudflare/vitest-plugin`, reads the tracked
`wrangler.example.jsonc`, and answers outbound calls to github.com from a stub in
`vitest.config.mts`.

## Configuration

`wrangler.example.jsonc` is the tracked template. `python install.py` renders it
into `wrangler.jsonc` — gitignored — with your D1 database id, GitHub username
and timezone. To do it by hand, copy the template and replace those three
values. `INGEST_TOKEN` is a secret, never a var:
`npx wrangler secret put INGEST_TOKEN`.

## Schema and migrations

`schema.sql` is the whole schema for a **new** database and is what `install.py`
applies. `migrations/` upgrades a database that already exists — run each file
once, in order, together with the deploy that needs it:

```bash
npx wrangler d1 execute devcard --remote --file migrations/0001_event_source_id.sql
```

A test (`test/migration.test.ts`) applies the migration to a pre-migration
database and asserts the result is column-for-column and index-for-index
identical to a database built from `schema.sql`, so the two paths cannot drift
apart silently.

`rebuild-rollups.sql` recomputes every rollup from `events` by hand. The nightly
cron does the same job exactly; the SQL file has to take the timezone as a
literal offset — its header explains when that is inexact. It is idempotent.

## Adding a badge, certification, or award

Manual, self-declared entries:

```bash
npx wrangler d1 execute devcard --remote --command "INSERT INTO profile_entries (kind, label, detail, created_at) VALUES ('<kind>', '<label>', NULL, strftime('%s','now'))"
```

- `kind`: one of `badge`, `certification`, `award`
- `label`: short text shown on the card

More in [docs/customizing.md](../docs/customizing.md).

## Embedding the card

```html
<img src="https://<your-worker-url>/svg?user=<you>" alt="devcard" />
```
