# devcard worker

The backend: `POST /ingest` (called by the local hook), `GET /svg` (the public
card), `GET /embed` (the hoverable README block), and a nightly cron that
rebuilds the rollups.

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
