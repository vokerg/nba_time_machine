# Morning evidence to watchability (#10)

The morning collector and ranking processor are separate operator steps:

```text
ESPN/CBS response -> policy-limited normalized capture + temporal evidence
  -> revalidated complete trajectory -> versioned features
  -> existing hidden score archive -> explicit hint -> spoiler policy -> coarse verdict
```

The `raw_captures` table holds normalized JSON for these sources, rather than the
original response body. Retained play identities, clocks, scores, player stats,
coverage errors and observation times are the reproducible building blocks.
Provider HTML/JSON/prose is not archived beyond the permitted normalized fields.

## Operation

From `backend/`, with the intended database configured and reviewed sources synced:

```bash
.venv/bin/python scripts/collect_nba_morning.py --date 2026-10-14 --write --manual
.venv/bin/python scripts/process_nba_evidence.py --date 2026-10-14 --as-of 2026-10-15T04:00:00Z
.venv/bin/python scripts/process_nba_evidence.py --date 2026-10-14 --as-of 2026-10-15T04:00:00Z --write
```

Use an explicit as-of instant at or after evidence observation; the timestamp above
is illustrative. `--game-id UUID` can replace `--date`. The processor fetches
nothing. Default mode checks stored evidence without writing. Write mode stores
features and scores atomically per game, using the sports advisory lock and
locking source registry rows against policy changes. Games commit independently.
Date batches are capped at 20 games. No scheduler or source activation is added.

Output contains counts, never scores or source bodies. Exit 2 means unavailable or
failed stored games. Zero games is not proof of a verified empty slate. Pending
games skipped by collection have no evidence fact and are absent from processor
counts; inspect the collector report for full discovery/coverage.

## First feature version

`morning-trajectory-v1` defines measured metrics and normalized 0–1 inputs:

| Metric | Definition | Normalization |
| --- | --- | --- |
| Clutch milliseconds | Last five regulation minutes plus all OT, within five points | Divide by 300,000, cap at 1 |
| Lead changes | Last non-tied leader switches; A → tie → B counts once | Divide by 20, cap at 1 |
| Winner's maximum deficit | Largest observed deficit of the eventual winner | Divide by 25, cap at 1 |
| Overtime periods | Validated period count minus four | Divide by 3, cap at 1 |

Each score holds until the next play in that period. No interpolation, repair or
provider mixing occurs. Zero means measured absence; unavailable trajectory data
produces no score. Box failure alone does not invalidate a complete trajectory,
subject to the collector's existing participant reconciliation checks.

The existing `postgame-v1` weighted formula uses these four signals, renormalizing
over their weights. Individual performance, rarity and subjective quality are
omitted, not assigned zero. Normalization and verdict bands are provisional and
uncalibrated, including for preseason. This is a first trajectory-based rating,
not a claim of recommendation quality.

## Provenance, finality and revisions

Each `ranking.features.morning-trajectory-v1` temporal fact stores metrics,
normalized values, derivation version, input fact UUID and actual processing
timestamp. Deterministic features inherit the input observation/availability;
`processed_at` separately records computation time. This permits reproducible
as-of calculations without claiming the producer ran earlier. Score components
reference the original evidence UUID and feature version; that evidence links to
the registry source and provider ID.

The producer verifies the canonical game mapping and latest NBA observation,
requires a matching final state, scores/tip/timestamps, and reruns validation.
Conflicting same-time observations/facts, expired facts, revoked source policies,
missing tips, pending states and partial traces produce no score. It does not
resurrect older clean evidence or mix providers to hide a problematic revision.

Scoring eligibility begins when we observed a validated final state, using the
later observation/availability time. Actual tip, publication and actual final
timestamps stay unknown and unchanged in sports tables. Morning-after data never
creates historical pregame knowledge.

Same input/version/as-of replay is idempotent. Changed inputs at the same score
snapshot cause a revision collision: use a later as-of snapshot or a new version,
never overwrite history. Archived reads rederive morning components from the
latest eligible input at the profile cursor. Corrections, partial revisions or
source revocation withhold an old rating until a valid replacement is archived.
Historical cursors can still read the earlier evidence state.

## Existing disclosure boundaries

Ordinary cards and pregame interest do not expose these scores. Explicit per-game
watchability requests can show the existing coarse verdict. No reason producer
is added. Numeric ratings, metrics, components and results never enter the public
watchability response or AI context.

Outcome-based list ordering still requires consent and a historically observed
pregame slate. Morning evidence does not establish that slate; replay/observed
views still cannot request ranked picks. Per-game hints can use the archive
without broadening ordering permissions. Pregame feature production, calibration,
richer signals and scheduling remain separate work.

## Verification

Synthetic tests cover corrections, incomplete traces, ties, comeback, clutch
intervals, OT, independent box coverage, historical visibility, idempotence,
source revocation and coarse HTTP disclosure. Persistence tests require disposable
local/CI PostgreSQL, never the owner's Neon database.

Verified October 15, 2026: all **366 backend tests passed** on a fresh disposable
PostgreSQL database. The real October 14 slate yielded six persisted final-game
evidence records, five feature bundles, five archived ratings and five coarse
HTTP verdicts. Immediate processor replay left five bundles/scores. The partial
PHX–SAS trajectory stayed unscored; its CBS fallback returned 301. DEN–LAC was
unfinished and had no stored evidence. [Sanitized run evidence](evidence/morning-ranking-2026-10-14.json)
contains counts and health, no numeric ratings or original response bodies. No
owner Neon writes or scheduling activation were performed.
