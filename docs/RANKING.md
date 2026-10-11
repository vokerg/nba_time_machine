# Versioned recommendation core (Issue #10)

The first ranking slice lives under
`backend/src/nba_time_machine/ranking/`. It is a deterministic input-to-score
layer, **not** a source of authorized game facts or a public recommendation
endpoint. No provider feature extraction or production calibration is claimed.

## Two disjoint score families

- `score_pregame(..., tip_at, as_of)` accepts only `PregameSignal`
  observations, each carrying normalized value, source reference, observed
  and available timestamps. Both evidence timestamps and the score snapshot
  must strictly predate tipoff, and evidence must be known at `as_of`.
- `score_postgame(..., final_at, as_of)` accepts only `PostgameSignal`
  observations. Finalization and both evidence times must be known by
  `as_of`; outcome-derived evidence cannot be dated before the trusted final.
- Weights and the distinct model version strings are explicit in
  `scoring.py`. Scores lie in [0, 10], with a trace of signals, weights,
  contributions, source identity and source timestamps. Missing signals are
  excluded, not replaced by fabricated current-season estimates.
- Score values and components are internal. They must **never** be passed
  directly to a public response or AI context without the spoiler policy.

## Recommendation and disclosure

`rank_pregame` and `rank_postgame` reject mixed score kinds and return
UUIDs only. `recommend_for_budget` solves a bounded 0/1 viewing-time knapsack,
comparing rich hidden postgame scores but returning only selected game IDs.
Neither ranking nor budget selection accepts favorite-team inputs; favorites
belong on a separate UI surface. Showing a postgame-ranked list can itself be
a spoiler and requires explicit user consent in the eventual API.

`ranking_fields` turns a pregame score into `PREGAME_INTEREST`, or an internal
postgame score into a coarse `WATCHABILITY_VERDICT` and optional
`WATCHABILITY_REASON`, using explicit product-configurable `VerdictBands`.
The existing deterministic `project_game` is still required with the
requested disclosure layer. An internal numeric postgame quality score is
never a `GameField`.

## Archived score integrity (Issue #10 follow-up)

At the archive read and consent-gated selection boundaries, a versioned score
is discarded unless its value exactly matches the deterministic weighted
calculation from its attached components. Every component must have a unique
signal in the declared score family, the expected model weight and rounded
contribution, a finite normalized input in [0, 1], a nonblank source
reference and timestamps no later than its score snapshot. The score kind
and version must also agree. Invalid newest snapshots are **withheld**,
never silently replaced by older values. If a score repository supplies more
than one row for a requested game, the recommendation service withholds that
game entirely (including when one row is corrupt), rather than choosing a
first result based on unspecified repository order. This also applies to
time-budget selection. These checks validate archive consistency, not source
trust, game-finality verification, authorization or a change to postgame
consent. Numeric scores remain internal.

## Verification and known gaps

Unit tests cover historical backfills, tip boundaries, invalid evidence,
family separation, extraordinary surprise games, provenance/versions, hidden
postgame score disclosure, deterministic time-budget optimization and ordering
independent of favorite teams. Run `cd backend && pytest -q tests/test_ranking.py`.

The ranking core now includes PostgreSQL `recommendation_scores`, an append-only
archive of independently versioned `pregame` and `postgame` scores. Each row
contains an as-of timestamp, score value and per-signal source/timestamp
provenance. Replaying identical evidence is idempotent; changing an already
archived score with the same (game, kind, version, as-of) is rejected. The
`0006_recommendation_scores` migration and PostgreSQL integration test cover
this contract. These DB rows are internal and must never be serialized directly
into a spoiler-safe response.

This is a bounded initial slice of #10. Remaining: connect trusted as-of structured fact extraction;
provide an explicitly gated recommendation application/API service; use
historical games to tune normalization, thresholds and weights. This
implementation does not claim real-life ranking quality or frontend wiring.


## Explicit, cursor-scoped recommendation endpoint (PR #33)

`POST /profiles/{profile_id}/recommendations/watchability` is the
**only** HTTP entry point for postgame score-based ordering. A request must
include `candidate_game_ids` (1–32 distinct canonical game UUIDs) and
`consent_to_outcome_ranking: true`. Missing/false consent returns HTTP
403 **before** accessing the profile timeline or score archive. GET is not
supported. The consent is specific to this request, not an implicit setting,
and does not acknowledge a game or move the media cursor.

Example request (the UUIDs are illustrative, not actual scheduled games):

```json
{
  "candidate_game_ids": [
    "11111111-1111-4111-8111-111111111111",
    "22222222-2222-4222-8222-222222222222"
  ],
  "consent_to_outcome_ranking": true,
  "budget_minutes": 120,
  "planned_minutes_per_game": 60
}
```

The response contains **only** `game_ids`, never score values, components,
models, reasons, source metadata, scores, standings, or a surprise indicator.
A ranked game's presence and position can itself reveal outcome-dependent
information; the endpoint is explicitly opt-in and must not power an
unconsented dashboard sort or a general-media surface.

Only archived `postgame-v1` scores with `as_of <= persisted time_cursor`
are eligible. Querying picks the latest such snapshot per requested game and
rejects malformed, temporally inconsistent components instead of falling
back to older evidence. The service independently checks score family, model
version, trusted component observation timestamps and membership in the
requested UUID set. No current-world/default-now substitution is permitted.
Games with no eligible archived postgame score are omitted; **absence is not
evidence of poor watchability**. The client should build its candidate set from
the separate safe historical game list; this route does not independently
prove that each submitted UUID belonged to that list.

A time budget uses a **uniform user-planned allocation** per game rather than
the actual game or highlight duration (which could leak outcomes). Both
optimization and unbudgeted ordering operate on internal scores; the response
still contains UUIDs only. Favorite teams are not accepted as ranking input.

This is a bounded application-boundary slice; it is not a live recommendation
quality claim. The first structured sports provider does not yet expose the
trusted feature history required to populate meaningful production scoring,
so an empty response is normal on unscored data. Real provider normalization,
historical calibration, verdict integration into the game-disclosure service,
frontend consent UX and authenticated profile ownership remain future work.
Profile UUIDs are presently **opaque state keys, not authenticated accounts**;
the caller must not mistake this endpoint's consent check for user login or
authorization.
