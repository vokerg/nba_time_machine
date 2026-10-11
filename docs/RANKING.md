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

This is the foundational scoring slice of #10. Remaining: connect trusted as-of structured fact extraction;
provide an explicitly gated recommendation application/API service; use
historical games to tune normalization, thresholds and weights. This
implementation does not claim real-life ranking quality or frontend wiring.


## Trusted temporal-fact evidence reader (second #10 slice)

`SqlAlchemyRankingEvidenceRepository` in `ranking/evidence.py` provides
internal `pregame(game_id, as_of=...)` and `postgame(game_id, as_of=...)`
methods, returning a `VersionedScore` or `None` when trust is insufficient.
The caller supplies a canonical game UUID and an as-of moment, **not** a
client-claimed tip, finish time, source timestamp, normalized signal, or
postgame disclosure preference. The repository first finds the latest
historically knowable NBA game observation, then validates its status.
A pregame score requires a scheduled observation known strictly before
the trusted scheduled tip and an as-of cursor earlier than that tip.
Postgame requires a latest `final` observation with an explicit,
trustworthy `final_at` no later than the observed/available timestamps.
TheSportsDB's current final observations have no `final_at`; these
correctly yield no postgame score until evidence quality improves.

Only carefully curated `TemporalFactRecord` rows with
`subject_type="game"`, canonical `game_id`, and an exact signal name
`ranking.pregame.<PregameSignal.value>` or
`ranking.postgame.<PostgameSignal.value>` are read. A trusted normalizer
must write `value={"normalized_value": 0.0..1.0}`, original `source_id`,
`observed_at`, `available_at`, `valid_from` and optional `valid_to`.
That number represents a **normalized feature**, never a game score.
Historical reads require both observation and availability no later than
the requested as-of time and fact validity covering that moment.
The newest knowable revision per signal wins; a malformed revision masks
older values instead of resurrecting stale evidence. Missing or invalid
features are omitted; no current records, other leagues, title text, winner,
margin or final score are silently converted to interest/entertainment.
Each score component refers back to its persisted source and fact UUID.

These records are **not** automatically generated by TheSportsDB ingestion.
Live-normalizer work must define, vet and test quantitative derivation for each
signal separately before emitting facts. The evidence reader returns
internal scores only and does not archive them or provide any public endpoint.
In particular, postgame order and time-budget choices remain unavailable
from public APIs without explicit informed opt-in and policy-gated
disclosure. No favorite-team weighting or media-cursor changes occur.

PostgreSQL integration tests:
`cd backend && pytest -q tests/integration/test_ranking_evidence.py`.
They cover delayed/backfilled signals, tip boundaries, correction of
scheduled status, malformed revisions, finalization trust, pre-final and
future postgame facts, and non-NBA identities. The prior pending
recommendation application/UI API, richer feature producers, calibration
and live Neon validation remain part of parent #10 or follow-up work.
