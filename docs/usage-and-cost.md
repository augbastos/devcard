# Local agent usage and estimated cost

`hook/devcard_usage.py` reads local Claude Code and Codex JSONL transcripts.
It uses Python's standard library and adds usage tables to the existing local
SQLite database. It makes no network requests. `devcard publish` scans before
aggregation (after the publish debounce); `devcard render` also scans before
aggregation. `devcard serve` scans an existing database once at startup before
opening its read-only HTTP views. Restart it to import newer transcript usage;
Refresh reads newer database writes. Set `"usage": false` to skip scanning.
Errors and incomplete-scan diagnostics go to local `errors.log`, with structural
codes instead of transcript text or paths. A failed scan does not stop publishing.
The capture hot path, Worker and D1 do not consume usage.

## What is read

The caller supplies transcript paths explicitly. `discover_usage_paths(root,
agent=...)` recursively discovers JSONL files beneath that explicit root,
including Claude's nested subagent transcripts. It does not discover home
directories automatically or read `.env` files. Schedule discovery and scanning
in the background, outside the per-tool capture hook.

- Claude: only `assistant` records with `message.usage` are counted. The global
  local identity is an HMAC of the tuple `("claude", message.id, requestId)`.
  Later revisions replace the complete token vector, including decreases,
  while preserving the first observed date. Older timestamped copies cannot
  overwrite a newer revision. The same call copied to another transcript is
  counted once. A message without a request ID uses a message-only fallback;
  this produces a local diagnostic pending identity validation.
  a unique observed full identity validates and promotes that fallback. Several
  request IDs for that message make further fallback records ambiguous and
  produce an incomplete-scan diagnostic. Positive usage without a message ID
  also produces an incomplete-scan diagnostic.
- Codex: `token_usage_record.payload.usage` is preferred and deduplicated
  globally by HMAC of `("codex", response_id)`. `turn_token_usage` and
  `thread_token_usage` are not extra billable tokens. The preceding
  `turn_context.payload.model` provides the model.
- Older Codex transcripts: count positive differences of cumulative
  `token_count.info.total_token_usage`, never the cumulative snapshots
  themselves. Repeated snapshots contribute nothing, and `info: null` is
  ignored. `last_token_usage` is used only to validate an initial baseline,
  never repeatedly added. The first total is counted only when a zero baseline
  can be verified (zero total, matching response coverage, or equality to the
  first call's last usage). Otherwise it becomes a baseline and the scanner
  reports incompleteness instead of assigning historic tokens to that day.
  Counter decreases start a new baseline and emit a reset diagnostic.
  An explicit fork requires an independent baseline, and a session-identity
  change restarts parser state instead of subtracting unrelated counters.

In mixed Codex files, legacy deltas before response records remain counted.
Subsequent snapshots are reconciled against response tokens already observed
since the last baseline. Missing response coverage contributes only the
uncovered delta and produces a diagnostic. A response may precede its next
snapshot; equality is not required during an active append.
If a late response has a verifiable cumulative endpoint matching the latest
snapshot, it replaces that snapshot's covered tokens atomically. A local
numeric reconciliation prevents a copied transcript from restoring those
tokens. Older overlapping endpoints without an identifiable interval produce
an incomplete-scan diagnostic and do not add the same tokens again.

Each file has a hashed local identity, byte cursor, generation, boundary
fingerprints and numeric parser state. Scans freeze the source size and stop
after the last complete line; an unfinished line stays in the source file for
the next scan. Complete malformed or oversized lines are diagnosed without
storing their text. Truncation, file replacement, and changed committed
boundaries start another generation and reprocess idempotently using stable
call identities. If a rotated Codex segment omits
its session header, its previously verified hashed session identity is retained
until another explicit header replaces it; counters and model context restart
and the initial baseline is untrusted. Old calls are retained: removing a
transcript does not remove already recorded usage.
Cursor changes, call revisions, diagnostics and aggregate adjustments share
one SQLite transaction. A failure rolls them all back. Savepoints preserve a
transaction already owned by the caller.

## What stays on the machine

The SQLite usage tables store a random local HMAC salt, hashed file/call/message
identities, byte offsets, generations, numeric state, allowlisted exact models,
timestamps, token categories, local diagnostics and price provenance. Raw
paths, file names, project names, session/request/response IDs, message text,
prompts, code, branches and unfinished JSONL tails are not persisted by this
module. Do not publish the database or its salt.

`export_usage()` constructs each record from this exact allowlist:

```json
{
  "date": "2026-10-13",
  "agent": "claude",
  "model_family": "claude-sonnet",
  "input_tokens": 1000,
  "output_tokens": 1000,
  "cache_read_tokens": 5000,
  "cache_write_tokens": 3500,
  "estimated_cost_usd": "0.036"
}
```

The numbers above are synthetic. Allowed agents are `claude` and `codex`.
Allowed families are `claude-sonnet`, `claude-opus`, `claude-haiku`, `gpt`, `o`
and `unknown`. Exact model names and cache-write TTLs stay local. Unrecognized
model strings are discarded locally and map to `unknown`; they cannot become
public identifiers. Export rejects invalid enums, dates, counts and costs.
Tests inspect serialized bytes as well as the local database for private
sentinels. `devcard publish` includes this projection in the machine JSON only when
`card.show_usage` is on (default off); machine merges sum matching
day/agent/family buckets and propagate null costs. The scanner itself does not
upload anything, and with the line off the usage aggregates never leave the machine.

## How cost is estimated

**API-equivalent cost (estimate at bundled API rates; not your subscription bill)**

This estimates the value of logged text tokens at the bundled API rates.
It does not estimate a subscription charge, prove savings, or convert a
subscription usage meter. Additional services, taxes, batch discounts, service
tiers, promotional credits and private contracts are outside its basis.

`devcard/prices.json` is an offline versioned table with schema version, table
version, verification date, currency, calculation policy, explicit aliases
and source provenance. Only the cited Sonnet 4.5 example
rates are seeded, in USD per million tokens: input 3, output 15, cache read
0.30, cache write 5 minutes 3.75, and cache write 1 hour 6.
The example is from
[Anthropic's prompt-caching reference](https://github.com/anthropics/skills/blob/main/skills/claude-api/shared/prompt-caching.md?plain=1).
The source has not been pinned to an upstream revision or hash;
those provenance fields are explicitly `null`. This is a small hand-curated
example, not a complete LiteLLM or ccusage price snapshot. Other listed models
have unknown rates, including every bundled Codex model.

The table restricts the seeded example to input contexts of at most 200,000
tokens; larger contexts have no bundled rate schedule. This is a conservative
estimation boundary, not a claim that all context sizes have the same price.
The calculator supports explicit complete rate schedules for context tiers.
Select the tier using all input categories for each individual call before
aggregating; do not apply a tier to a whole day's token total.

Each call is calculated with `Decimal`, without rounding through a float:

```text
sum(category_tokens * category_USD_per_million) / 1,000,000
```

Token categories are disjoint:

- Claude's normal input, cache read and cache creation are separate. Cache
  creation's total is split into its observed 5-minute and 1-hour categories;
  the total is not charged again. Missing or inconsistent TTL detail makes
  the call's cost unknown.
- Codex's input includes cached input. Subtract cache read and cache write
  before exporting normal input, then charge each category once. Positive
  cache write needs a known cache-write rate. Reasoning output is already part
  of output and is not added again.

Unknown models, needed rates, TTLs or context tiers return `None`, exported
as JSON `null`, never a fabricated zero. If any call in a daily agent/family
bucket has unknown cost, that bucket's full cost stays `null`. A verified
zero-token call with a known rate schedule can cost the decimal string `"0"`.
Legacy snapshots may span several calls without identifiable per-call context.
Their cost stays unknown under context-dependent schedules. A reviewed custom
flat schedule can price the disjoint delta, since its linear cost equals the
sum of individual calls; bundled Codex rates remain unknown.

Scanning uses the bundled table only. Updating prices is an explicit local
maintenance action. `reprice_usage(conn, prices)` explicitly recalculates local
calls and aggregates atomically and updates stored price provenance; replacing
the JSON file alone does not silently reprice previously recorded calls.

## Local use

The package integration discovers `~/.claude/projects/**/*.jsonl`, plus
`~/.codex/sessions/**/*.jsonl` and `~/.codex/archived_sessions/**/*.jsonl`.
`CODEX_HOME` overrides the Codex root. Only JSONL transcripts are opened.
Each file's saved byte cursor avoids parsing unchanged content on reruns.
The configured IANA timezone applies to usage buckets; without one, usage
uses stable UTC buckets (code-activity days still use system-local time).
Changing the usage timezone requires an explicit local rebuild; a mismatch
is logged and previous aggregates remain available.

The caller passes its existing connection, explicit transcript paths and a
uniform timezone. UTC is the default. A database's timezone cannot silently
change between scans, since that would mix incompatible daily buckets.

```python
from datetime import timezone
from pathlib import Path
from devcard_usage import scan_usage, read_usage, export_usage

# conn is the application's existing local SQLite connection.
report = scan_usage([Path("transcript.jsonl")], conn,
                    agent="claude", tz=timezone.utc)
payload = export_usage(read_usage(conn))
# payload is bytes; this module does not send it anywhere.
```

`ensure_usage_schema(conn)` creates the local usage tables idempotently and
does not commit the caller's transaction. `scan_usage` commits when there is
no enclosing transaction; otherwise the caller must commit its own transaction.
`aggregate_usage` is also available for already-deduplicated calls in memory.
Use `ScanReport.incomplete` and the persistent `usage_diagnostics` table to
surface structural gaps; do not describe such results as complete accounting.

## Limits

- Log coverage, timing and identity quality determine accuracy. Missing logs,
  historical prefixes without a baseline, forks and resets are not repaired
  by inventing usage. Mixed coverage is reconciled numerically; logs with
  response records reordered behind their corresponding snapshots or forks
  with overlapping historical prefixes need additional producer-level
  evidence when cumulative endpoints cannot identify their coverage. Snapshot
  deltas without a session identity can only be deduplicated
  within their local file identity.
- File fingerprints detect normal truncation/replacement and changes at the
  committed prefix and boundary. In-place rewrites confined to the middle of
  a growing file cannot be established from these bounded fingerprints.
- Known exact models are an explicit allowlist, not arbitrary model-name
  prefixes. New spellings need review; internal calls can also differ from
  the preceding turn's advertised model.
- Positive Codex cache write is tested synthetically; actual producer behavior
  is not independently validated.
- No pinned ccusage comparison, CLI meter, dashboard or invoice comparison
  has been run. Comparisons need identical inputs, identity policy, rates and
  pricing basis; current aggregate output is not proof of equivalence.
- Public aggregates have no call identity and cannot deduplicate overlapping
  logs across machines. Each input set needs exclusive machine ownership.
- Usage aggregates are separate from code `edit`/`write` and git `diff` events.
  The legacy Worker has no usage ingestion or rendering contract.
