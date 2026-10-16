# Local scoring workbench (#87)

The workbench is a separately launched developer tool for inspecting and tuning
ratings against the configured real PostgreSQL database. It deliberately exposes
numeric scores and outcome-bearing evidence. It is absent from the consumer app:
there is no admin switch, public debug route, or workbench bundle in its frontend.

## Launch

From the repository root:

```bash
backend/.venv/bin/python backend/scripts/run_scoring_workbench.py
```

Open <http://127.0.0.1:8765/?date=2026-10-14>. The launcher changes to `backend/`
so the existing backend `.env` configuration is used. Use `--port 8766` if needed.
The process binds only `127.0.0.1`, disables forwarded-client interpretation, and
checks the client address, Host and Origin. It is not an authenticated remote admin
application and must not be deployed or forwarded as one.

Inspection transactions are PostgreSQL **READ ONLY / REPEATABLE READ**. They do
not collect new games, advance profiles, acknowledge games, materialize scores,
change source policies or activate a tuning configuration. Failed inspections
return generic database errors without credential/source-body exception details.

## Using it

1. Select an Eastern NBA day and evidence cutoff in UTC. The slate contains stored
   NBA observations known by that cutoff, with latest revisions selected before
   date filtering. Coverage is bounded to 32 games and can be incomplete; unfinished
   games skipped by the morning collector may have no evidence or observation.
   **Load stored games** reads existing data. **Fetch & verify this day** explicitly
   collects fresh evidence and refreshes proposed scores; see below.
2. Start with **Proposed score / 10**: this is the combined score being tuned.
   **Current app score / 10** is the eligible stored score that feeds consumer
   hints when disclosure rules allow. **Change vs. app** is proposed minus current
   app score, rather than a comparison against a recomputed baseline. The
   redundant baseline is tucked inside **Check current app calculation · technical
   details**. Ineligible stored ratings are only shown in that collapsed check;
   the current app score and difference are unavailable for those rows.
3. Select a game. The breakdown shows raw metrics, normalization scales,
   normalized values, configured and effective weights, and additive points out
   of ten. Supporting source plays are filterable by signal. Source fact UUID,
   provider endpoint, observation times, coverage errors and retained normalized
   evidence are available below the calculation.
4. Edit weights, scales or coarse-verdict thresholds and **Recalculate proposed scores**.
   The same evidence cutoff is used. Formula changes receive an experimental
   version name, and exports are disabled until the edited settings are compared.
5. Record your own rating and assessment. Drafts exist only in this tab. **Export
   review session** saves an explicit JSON artifact containing the report,
   configuration and annotations. Importing a review session restores notes and
   recomputes the report against the canonical database; it does not trust an
   imported file's claimed scores or evidence.
6. **Export formula settings** downloads the last compared configuration. Reviewed tuning
   files can be committed under `config/ranking/` with a new version name. There
   is no automatic adoption: the current producer and archived scores stay intact.

The versioned baseline file is `config/ranking/trajectory-baseline-v1.json`. This
is a preview configuration, not a second production scoring path. Tests establish
parity with current morning feature normalization and `postgame-v1` arithmetic.
A baseline change must use an explicit version and be reviewed separately from
production adoption.

## Current app model criteria

| Active signal | Measured definition | Scale for normalized 1 | Weight | Effective share |
| --- | --- | --- | --- | --- |
| Clutch time | Last five regulation minutes plus OT, within five points | 300,000 ms | 25 | 35.71% |
| Lead changes | Switch between the last non-tied leaders | 20 | 15 | 21.43% |
| Comeback | Eventual winner's largest observed deficit | 25 points | 20 | 28.57% |
| Overtime | Extra periods beyond four | 3 periods | 10 | 14.29% |

Normalization is `min(measured / scale, 1)`. Score is
`10 * sum(normalized * weight) / sum(active weights)`, rounded to four decimals.
The denominator is currently **70**, not 100: missing features are excluded.
Default verdict thresholds are 4 and 7. All scales, weights and verdict bands are
provisional; this tool makes their effects inspectable rather than calibrating
recommendation quality automatically.

**Not connected:** star power/availability; team strength and leaders facing each
other; standings, playoff and seeding stakes; rivalry/history; recent form/rest;
expected pregame closeness; historical rarity; and tactical/subjective game
quality. The v2 candidate now includes measured player production and extreme
game patterns; saved production ratings keep their original model. Favorites never enter canonical ratings.

The default proposed formula is the [schema-5 Star Power formula](STAR_POWER.md),
which adds permission-gated pre-tip ranking snapshots and actual participation to the [schema-4 game-record formula](GAME_RECORD_IMPORTANCE.md),
which retains the [v2 player/performance and pattern terms](SCORING_ENRICHMENT.md)
and adds the two game-supplied entering records. Restore default formula restores
its checked-in settings. The original baseline and schema-1/2/3/4 files remain supported.

## Score and contribution labels

The proposed score appears first in the slate and selected-game summary. Its
component total appears before detailed calculations: drama (clutch time, lead
changes, comeback and overtime), player-performance bonus and extreme-pattern
bonus, with cap/rounding adjustments. These components are in **game-score
points** and add up to the proposed score out of ten.

**Performance magnitude (0–1)** is a player's statistical magnitude under the
selected thresholds. It feeds the top-two-player bonus calculation; it is not
itself a game score. **Magnitude (0–1)** in stat/pattern tables likewise shows
progress between the start and full-credit settings. The UI exposes both these
thresholds and the conversion into game-score points. Verdict thresholds are
spelled out next to the proposed score and named in the settings controls.

Incomplete player coverage is explicitly labeled. Legacy schema-1 settings
clearly say the proposed score uses drama only, without the player/pattern
bonuses. Formula changes require recalculation; until then the displayed scores
use the last calculated settings. **Your target game score** records the reviewer's
assessment, separate from both calculated scores. API, config and exported report
keys retain their versioned names (`baseline`, `experiment`, `severity`, etc.) for
compatibility; those internal names are not the main UI labels.

## Artifact formats

- Legacy config: `schema_version: 1`, `version`, four `weights`, four `scales`,
  `medium_from`, `high_from`. Keys must match the supported signals exactly;
  weights are finite 0–1000, with a positive sum; scales are finite and positive.
- Enriched config: `schema_version: 2`, the same drama settings plus explicit
  `player` and `pattern` settings; see the linked v2 formula contract.
- Context config: `schema_version: 3`, the v2 settings plus explicit `context` settings; see [game importance](GAME_IMPORTANCE.md).
- Game-record config: `schema_version: 4`, v2 settings plus `importance`; it requires no season reconstruction.
- Star Power config: `schema_version: 5`, v4 settings plus explicit `star`; see [Star Power](STAR_POWER.md).
- Report: `schema_version: 1`, slate/cutoff timestamps, baseline/experiment
  configurations, missing criteria, and per-game saved/derived calculations,
  provenance, diagnostics and normalized evidence.
- Review session: `schema_version: 1`, `kind: "nba-scoring-review"`, `report`, and
  `reviews` keyed by canonical game UUID with `rating` (empty or 0–10) and `notes`.

These are explicit developer artifacts, not additional canonical persistence for
sports facts or profile state. Exports contain spoilers. All imported text is
rendered as text; original provider HTML, credentials and AI prompts are absent.

## Verification

Run `backend/.venv/bin/pytest -q backend/tests/test_workbench.py` for calculation
and route isolation tests. PostgreSQL tests additionally verify database-enforced
write rejection, evidence diagnostics and unchanged fact/score counts after
preview. Persistence fixtures must run against disposable local/CI PostgreSQL;
the running workbench itself reads the configured owner's database.

Verified October 15, 2026: **382 backend tests** passed on fresh local PostgreSQL;
two standalone DOM tests passed (preview/export and review import with score
recomputation). Hosted CI also runs the DOM tests using the existing frontend
jsdom dependency. Live owner-database inspection found six stored games and five
eligible ratings, all matching the recomputed baseline. Supporting clutch and
lead-change events reconcile to their measured totals; preview changed ratings
without changing canonical fact/score counts. Browser verification covered slate
selection, weight comparison/reset, source-event filtering and config export.
Automated browser file import was blocked by the extension's file URL access;
import logic was verified with synthetic DOM tests. [Sanitized evidence](evidence/workbench-2026-10-15.json)
contains checks/counts only, not the game ratings or retained provider evidence.


Label revision (#94): seven DOM tests and 13 focused backend tests passed. The
live October 14 workbench was checked against the configured DB: proposed/current
scores, signed change, collapsed calculation check, score components, verdict
bands and player magnitude explanations were visible. No scoring, config schema,
export key or consumer behavior changes are part of this revision.


The schema-3 [game-importance proposal](GAME_IMPORTANCE.md) adds reconstructed
2025–26 opening-day records, shared standings ranks and transparent matchup/race
heuristics. These are retrospective inputs collected now, not pre-tip observations.
Schemas 1/2 remain readable; current app scoring and spoiler gates are unchanged.


The default v4 now uses the two game-supplied records, shows the postgame-total
subtraction and omits ranks/race terms. See [game-record importance](GAME_RECORD_IMPORTANCE.md).
The v3 history mode is only selected by explicit old-config imports.

Schema 5 exposes ranked player participation, identity/source coverage, team/game
magnitudes and the additive bonus. It requires an approved snapshot actually known
before tipoff; importing a ranking now does not unlock historical games. All
controls and missing-data rules are documented in [Star Power](STAR_POWER.md).


## Fetch and verify a day (#100)

Use **Fetch & verify this day** beside **Load stored games**. Loading and formula
previews remain database-enforced read-only. Only the explicit fetch action writes
fresh evidence through the existing `MorningCollector` / `MorningStore` pipeline.
It uses reviewed ESPN/CBS registry policies and manual collection mode (which can
use verified disabled sources without enabling scheduling); it cannot approve a
source or change its retention policy.

The action checks one Eastern day, up to 20 games / 40 requests, with a three-minute
overall time limit. One run can execute per workbench process, with the existing
PostgreSQL sports lock also preventing simultaneous external collectors. Progress
is polled; the completed panel shows discovered matchups, pending/complete/incomplete
families, providers, errors, request/capture counts and the persisted run ID.
Partial collection can save good evidence independently of other games failing.
Provider access failures never establish a verified empty slate.

After collection finishes, the evidence cutoff moves to now and the proposed scores
are recalculated using the current edited settings. This neither archives current
app scores nor adopts the experimental formula. Existing drama/performance/pattern/
importance/Star Power rules still apply. Star Power requires an authorized snapshot
known before tipoff; collecting games does not import rankings.

The reused morning collector deliberately skips unfinished games. They appear in
the verification panel as pending, without invented zero ratings or live player
participation. Re-run after final; this action does not provide live-game scoring.
A repeated fetch deduplicates identical evidence through canonical capture hashes.

The local job status is bounded to the latest job and lost on server restart. A
refresh does not start another job. Durable captures, collection runs and health
remain in PostgreSQL; use Load stored games after interruption to inspect saved
evidence. Job IDs prevent another tab's later run from being mistaken for yours.
The explicit POST requires JSON and `X-Workbench-Action: collect-day`, in addition
to the existing loopback, Host and same-origin checks. No consumer routes exist.

Verified October 16, 2026: the real button found 12 ESPN matchups for October 16,
all pending, with one request, zero new evidence captures and a persisted run.
The browser showed pending coverage and advanced the cutoff before previewing.
Synthetic database tests separately verified complete evidence persistence,
replay deduplication and unchanged archived-score counts. All 13 DOM tests passed.
The full backend run had 458 passes and the existing intermittent macOS launcher
cleanup failure; that test passed on targeted rerun. Six operator unit scenarios
(including a later timeout/shutdown test) passed. See the
[sanitized verification record](evidence/workbench-fetch-2026-10-16.json).
