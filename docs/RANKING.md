# Versioned recommendation core (Issue #10)

The first ranking slice lives under
\`backend/src/nba_time_machine/ranking/\`. It is a deterministic input-to-score
layer, **not** a source of authorized game facts or a public recommendation
endpoint. No provider feature extraction or production calibration is claimed.

## Two disjoint score families

- \`score_pregame(..., tip_at, as_of)\` accepts only \`PregameSignal\`
  observations, each carrying normalized value, source reference, observed
  and available timestamps. Both evidence timestamps and the score snapshot
  must strictly predate tipoff, and evidence must be known at \`as_of\`.
- \`score_postgame(..., final_at, as_of)\` accepts only \`PostgameSignal\`
  observations. Finalization and both evidence times must be known by
  \`as_of\`; outcome-derived evidence cannot be dated before the trusted final.
- Weights and the distinct model version strings are explicit in
  \`scoring.py\`. Scores lie in [0, 10], with a trace of signals, weights,
  contributions, source identity and source timestamps. Missing signals are
  excluded, not replaced by fabricated current-season estimates.
- Score values and components are internal. They must **never** be passed
  directly to a public response or AI context without the spoiler policy.

## Recommendation and disclosure

\`rank_pregame\` and \`rank_postgame\` reject mixed score kinds and return
UUIDs only. \`recommend_for_budget\` solves a bounded 0/1 viewing-time knapsack,
comparing rich hidden postgame scores but returning only selected game IDs.
Neither ranking nor budget selection accepts favorite-team inputs; favorites
belong on a separate UI surface. Showing a postgame-ranked list can itself be
a spoiler and requires explicit user consent in the eventual API.

\`ranking_fields\` turns a pregame score into \`PREGAME_INTEREST\`, or an internal
postgame score into a coarse \`WATCHABILITY_VERDICT\` and optional
\`WATCHABILITY_REASON\`, using explicit product-configurable \`VerdictBands\`.
The existing deterministic \`project_game\` is still required with the
requested disclosure layer. An internal numeric postgame quality score is
never a \`GameField\`.

## Verification and known gaps

Unit tests cover historical backfills, tip boundaries, invalid evidence,
family separation, extraordinary surprise games, provenance/versions, hidden
postgame score disclosure, deterministic time-budget optimization and ordering
independent of favorite teams. Run \`cd backend && pytest -q tests/test_ranking.py\`.

This is a bounded initial slice of #10. Remaining: persist versioned scoring
snapshots and provenance; connect trusted as-of structured fact extraction;
provide an explicitly gated recommendation application/API service; use
historical games to tune normalization, thresholds and weights. This
implementation does not claim real-life ranking quality or frontend wiring.
