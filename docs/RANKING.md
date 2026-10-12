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
belong on a separate UI surface. Direct sorting helpers now reject inconsistent
versioned scores (including component arithmetic and timestamp mismatches)
instead of using their claimed values. Viewing-time candidates are validated
on construction and again at optimization, including zero-minute requests,
so a bypass of the archive/HTTP reader or later mutation cannot silently rank
corrupt evidence. These internal checks **do not** establish real-world source
trust, game finality, or permission to disclose outcome-dependent ordering.
Showing a postgame-ranked list can itself be a spoiler and still requires
explicit user consent at the API boundary.

`ranking_fields` turns a pregame score into `PREGAME_INTEREST`, or an internal
postgame score into a coarse `WATCHABILITY_VERDICT` and optional
`WATCHABILITY_REASON`, using explicit product-configurable `VerdictBands`.
The existing deterministic `project_game` is still required with the
requested disclosure layer. An internal numeric postgame quality score is
never a `GameField`.

The disclosure bridge also rejects inconsistent or tampered `VersionedScore`
evidence before projecting any field. It reuses the shared archive/ranker
integrity check for model version, component arithmetic, allowed signals,
provenance and timestamps, so direct callers cannot bypass those checks to
alter pregame interest or a spoiler-bearing coarse verdict/reason. This checks
internal consistency only: it does **not** establish real-world provider trust
or grant permission to disclose postgame information; `project_game` remains
the deterministic spoiler-policy gate.

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
time-budget selection. Archived component JSON must carry actual numeric values:
reader-side decoding preserves original JSON types, so numeric strings,
booleans and fractional weights cannot be normalized into otherwise plausible
score evidence before validation. These checks validate archive consistency, not source
trust, game-finality verification, authorization or a change to postgame
consent. Numeric scores remain internal.

**Write-side integrity (#10):** The ranking materialization service rejects
internally inconsistent evidence returned by an alternate feature reader, and
`SqlAlchemyRankingStore.archive` independently rejects such scores *before*
serializing their components or querying/inserting rows. Both reuse the same
version/signal/weight/arithmetic/timestamp consistency contract as the read
boundary. A well-formed change to an existing (game, kind, version, as-of)
snapshot still raises an append-only revision collision; an identical valid
replay remains idempotent. These guards do not establish whether the input
sports facts were genuinely observed from a licensed, trusted source.

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

## Frontend consent boundary (partial #10)

`frontend/src/watchability.ts` provides a deliberately unmounted request
helper for a future authenticated/profile-connected interface. It accepts a
server-projected PREGAME slate, validates 1–32 unique canonical game UUIDs and
requires per-action `consentToOutcomeRanking: true` before any HTTP call. It
sends only IDs, consent and uniform planned duration/budget. On return, its
strict response boundary accepts only `game_ids`, rejects extraneous
postgame fields, unknown and duplicate IDs, and maps selected UUIDs back to
allowlisted pregame card fields. HTTP error bodies are not surfaced.

This is **not** an active dashboard feature; no fixtures, passive rendering,
browser favorite teams, untrusted raw sports data or automatic pregame lists
may silently enter postgame ordering. It awaits backend-connected safe game
lists, profile authentication/authorization, a deliberate opt-in UI and
trusted real score evidence. Returning no scored games is normal until those
producer gaps close. Neither numeric score visibility nor result
acknowledgement is introduced by this client.
