# devcard worker

Backend for the live devcard: `POST /ingest` (used by the Claude Code hook) and
`GET /svg?user=augbastos` (the public embeddable card).

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
