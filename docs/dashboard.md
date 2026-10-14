# Local dashboard

From a checkout, start the read-only dashboard with Python 3.11 or newer:

```sh
python -m devcard serve
# With the package installed and dashboard assets included:
devcard serve --port 47811
```

Open `http://127.0.0.1:47811/` in a browser. Stop the server with Ctrl+C.
The default port is **47811**; `--port` chooses a different port. There is no
host option: the server binds only to IPv4 loopback, `127.0.0.1`. A port already
in use is an error; sockets are never shared through `SO_REUSEADDR` or
`SO_REUSEPORT`. On Windows the socket also uses `SO_EXCLUSIVEADDRUSE`.
The command prints the actual port when `--port 0` asks the OS for a free one.

The dashboard works without `devcard init`, GitHub, internet access or a
publishing configuration. It reads the same local `events.db` as the hooks.
An absent database produces an empty dashboard; viewing it never creates a
database or installation identity. A database error is displayed as an error,
rather than silently shown as zero activity. Refresh reads new hook writes.

## Views and counting

- All-time lines added, bytes added, streak and recorded local repository count.
- Language proportions by lines added.
- A 16-week Monday-first heatmap, using the existing card's levels and streak.
  Select a day to inspect its language totals. Commit-only days extend the
  streak even when they add no lines.
- Daily lines-added chart and a table of lines added/removed and bytes per
  language, with inclusive From/To dates. Large ranges draw the latest 366
  days; the table and export retain the entire selected range.
- Per-agent totals when the events table has an `agent` column. Missing or
  empty attribution becomes `unknown`; attribution is a heuristic.
- Tokens per agent/model and **API-equivalent cost (estimate; not your
  subscription bill)**. No price is invented. Missing prices show
  “Unavailable,” including groups where only some rows have a price.
- A live local card preview from the existing Python renderer, without avatar
  downloads, configured badges or pins. Light/dark follows the OS preference.

All totals are for this machine. Published cards can include multiple
machines; no peer state is fetched by the dashboard. Repository count is the
number of rows in local `known_repos`, not a refreshed GitHub repository total.
The database's project keys are never selected or exposed in responses.
Edit/write actions and commit diffs remain separate counts; capture one mode
per machine to avoid recording the same lines twice. Lines use the same
language totals as the renderer; days include unclassified events such as
commits. Day boundaries follow the saved IANA timezone, or system-local time
when none is configured.

Active time and an hours-only sessions timeline are deferred: M1 has no
session/time tables, and M3 does not infer time or modify hook capture.
Missing agent/usage data is shown explicitly, rather than estimated.

## JSON API and exports

All endpoints are GET-only (HEAD is also supported). They return aggregate
numbers and labels, never event records, file paths or project names.

| Endpoint | Response |
| --- | --- |
| `/api/summary` | Object with `totals`, `streak`, `languages`, `heatmap`, `today`, `timezone`, `first_ts`. |
| `/api/days?from=2025-01-01&to=2025-01-31` | Array of `{day, language, lines_added, lines_removed, bytes_added, events}`. `language` can be null. Defaults to the heatmap start through today. |
| `/api/agents` | Array of `{agent, lines_added, lines_removed, bytes_added, events}`; empty without the optional column. |
| `/api/usage` | Array per agent/model with input/output/cache/reasoning/total token counts and nullable `cost_usd`; empty without a recognized optional table. |
| `/api/card.svg?theme=light` | Local rendered SVG; `theme` accepts `light` and `dark`. |
| `/api/export.json` | `{summary, days, agents, usage, cost_label}`; defaults to the full local history. |
| `/api/export.csv` | Daily language rows with the same six fields as `/api/days`; defaults to the full local history. |

Exports accept the same optional `from`/`to` parameters. The page's export
links follow its selected range. Summary, agents and usage in the JSON export
remain all-time, even when its daily rows are filtered. An unfiltered export's
daily totals reproduce the local event aggregates. CSV language labels that
start with spreadsheet formula characters are prefixed with an apostrophe;
JSON preserves the original labels.

Dates must be canonical `YYYY-MM-DD`, with `from <= to`. Duplicate parameters
and unrecognized parameters return 400. Unknown routes return 404. Unavailable
local data returns 503 without leaking paths or SQL error text.

### Optional usage schema contract

M4's final schema is not present in the M1 base. The dashboard recognizes, in
priority order, `usage`, `usage_events`, `usage_daily`, or `daily_usage`. Only
one is read, to avoid counting raw rows and rollups together. That table must
have `agent`, `model`, and at least one recognized token column:

- `input_tokens`, `output_tokens`, `total_tokens`, `reasoning_output_tokens`.
- `cached_input_tokens` or `cache_read_input_tokens`.
- `cache_write_input_tokens` or `cache_creation_input_tokens`.
- Optional `cost_usd` or `estimated_cost_usd`, already computed by the producer.

`total_tokens` is preferred when recorded. Otherwise it is input + output +
cache write. Claude-style `cache_read_input_tokens` is added because it is
separate from uncached input. Codex-style `cached_input_tokens` and reasoning
output are subsets and are not added again. Missing token columns contribute
zero. An unrelated table is ignored; malformed recognized data produces an
error. The final M4 integration should confirm these field meanings.

## Local privacy boundary

SQLite is opened with URI `mode=ro` and `PRAGMA query_only`, with a new
connection and consistent transaction snapshot for each API response.
There are no writes, schema migrations, hook changes, publishers or outbound
network clients in this server. The single HTML, CSS and JS files use system
fonts, no CDN, telemetry or external assets. The browser makes same-origin
requests only. Static routes are an explicit allowlist, never directory serving.

The server requires a single Host header for `127.0.0.1` or `localhost` with
its actual port. Foreign hosts, duplicate/missing Host headers, absolute
remote request URLs and foreign Origin headers are refused. It supplies no
CORS allowance and uses a restrictive Content Security Policy, `no-store`,
`nosniff`, a no-referrer policy and no framing. Request strings are not logged.
Loopback protects access from other machines; other programs/users on the
same machine can access local aggregate data while the server runs.

## Integration and verification

Before shipping a wheel, include the three dashboard assets as package data:

```toml
[tool.setuptools.package-data]
devcard = ["dashboard/*.html", "dashboard/*.css", "dashboard/*.js"]
```

Verify the built wheel contains them. The current M1 packaging configuration
does not explicitly include non-Python assets; checkout serving does not have
that limitation. This is an integration prerequisite, not a runtime dependency.

```sh
python -m unittest discover -s hook -p "test_*.py" -v
python -m unittest discover -s tests -t . -v
```

`tests/test_serve.py` runs a real exclusive loopback listener against a
temporary SQLite fixture. It covers aggregate parity, date ranges, optional
schemas, exports, read-only access, new hook writes, fresh installations,
renderer reuse, Host/Origin guards and static route boundaries.
