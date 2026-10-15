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
2. Compare **Saved**, **Baseline** and **Preview** ratings. A saved row marked `*`
   is withheld because it is invalid or no longer matches eligible evidence.
   Withheld evidence never becomes a zero score or an experimental rating.
3. Select a game. The breakdown shows raw metrics, normalization scales,
   normalized values, configured and effective weights, and additive points out
   of ten. Supporting source plays are filterable by signal. Source fact UUID,
   provider endpoint, observation times, coverage errors and retained normalized
   evidence are available below the calculation.
4. Edit weights, scales or coarse-verdict thresholds and **Compare preview**.
   The same evidence cutoff is used. Formula changes receive an experimental
   version name, and exports are disabled until the edited settings are compared.
5. Record your own rating and assessment. Drafts exist only in this tab. **Export
   review session** saves an explicit JSON artifact containing the report,
   configuration and annotations. Importing a review session restores notes and
   recomputes the report against the canonical database; it does not trust an
   imported file's claimed scores or evidence.
6. **Export config** downloads the last compared configuration. Reviewed tuning
   files can be committed under `config/ranking/` with a new version name. There
   is no automatic adoption: the current producer and archived scores stay intact.

The versioned baseline file is `config/ranking/trajectory-baseline-v1.json`. This
is a preview configuration, not a second production scoring path. Tests establish
parity with current morning feature normalization and `postgame-v1` arithmetic.
A baseline change must use an explicit version and be reviewed separately from
production adoption.

## Current criteria

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
expected pregame closeness; exceptional individual performance; historical rarity;
and tactical/subjective game quality. Retained player boxes alone do not imply a
performance feature exists. Favorites never enter canonical ratings.

## Artifact formats

- Config: `schema_version: 1`, `version`, four `weights`, four `scales`,
  `medium_from`, `high_from`. Keys must match the supported signals exactly;
  weights are finite 0–1000, with a positive sum; scales are finite and positive.
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
