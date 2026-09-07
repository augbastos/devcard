# devcard worker

Backend for the live devcard: `POST /ingest` (used by the Claude Code hook) and
`GET /svg?user=augbastos` (the public embeddable card).

## Working on it

```bash
npm ci                # pinned toolchain — do this before anything else
npm run dev           # wrangler dev (add --remote for the real D1)
npm run typecheck     # tsc over src and test
npm test              # vitest inside workerd, against a local D1
npm run deploy        # wrangler deploy
```

`npm test` needs no Cloudflare account, no secret and no network: it runs in
workerd through `@cloudflare/vitest-pool-workers`, and outbound calls to
github.com are answered by a stub declared in `vitest.config.mts`.

## Schema and migrations

`schema.sql` is the whole schema for a **new** database and is what `setup.py`
applies. `migrations/` upgrades a database that already exists — run each file
once, in order:

```bash
npx wrangler d1 execute devcard --remote --file migrations/0001_event_source_id.sql
```

A test (`test/migration.test.ts`) applies the migration to a pre-migration
database and asserts the result is column-for-column and index-for-index
identical to a database built from `schema.sql`, so the two paths cannot drift
apart silently.

`rebuild-rollups.sql` is the manual equivalent of the nightly cron: it
recomputes every rollup from `events`. It is idempotent and safe to run at any
time.

## Adding a badge, certification, or award

These are manual, unverified entries — edit or add them any time with:

```
npx wrangler d1 execute devcard --remote --command "INSERT INTO profile_entries (kind, label, detail, created_at) VALUES ('<kind>', '<label>', '<detail-or-NULL>', strftime('%s','now'))"
```

- `kind`: one of `badge`, `certification`, `award`
- `label`: short text shown on the card (e.g. `AWS Certified Cloud Practitioner`)
- `detail`: optional longer text, or `NULL`

## Embedding the card

```html
<img src="https://card.devcard.workers.dev/svg?user=augbastos" alt="devcard" />
```
