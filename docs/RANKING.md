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
The optimizer uses canonical UUIDs to break equal-utility subset ties, then
orders the selected games by **descending hidden watchability** (equal scores
use canonical UUIDs), matching the unbudgeted recommendation semantics.
The returned IDs remain the only output; score values and utility are not
exposed to callers or the HTTP response.
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

This is a bounded initial slice of #10. Remaining: produce trusted as-of structured features and use historical
games to tune normalization, thresholds and weights. The connected API and
frontend described below do not establish real-life ranking quality.


## Explicit, cursor-scoped recommendation endpoint (PR #33)

`POST /profiles/{profile_id}/recommendations/watchability` is the
**only** HTTP entry point for postgame score-based ordering. A request must
include `slate_date` (the NBA/Eastern YYYY-MM-DD date used for the safe
historical game-list query), `candidate_game_ids` (1–32 distinct canonical
game UUIDs), and `consent_to_outcome_ranking: true`. Missing/false consent returns HTTP
403 **before** accessing the profile timeline or score archive. GET is not
supported. The consent is specific to this request, not an implicit setting,
and does not acknowledge a game or move the media cursor.

Example request (the UUIDs are illustrative, not actual scheduled games):

```json
{
  "slate_date": "2026-05-04",
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
evidence of poor watchability**. Before querying any postgame score, the
server reconstructs the requested NBA/Eastern `slate_date` through the
**trusted, profile-scoped PREGAME game-list service**. Every submitted UUID
must belong to that server-projected list; a client-supplied UUID or a
client's claim to have previously fetched the list is not sufficient.
Off-slate candidates fail the entire request with HTTP 403 rather than
revealing a partial ranking. If the persisted cursor changes between the
timeline read and safe-list reconstruction, the request fails closed with
HTTP 409; the client must refresh the safe slate. The service also rereads
the persisted cursor **after** the score archive query and returns HTTP 409
when an in-flight timeline advance is detected; the timeline repository
refreshes a previously cached ORM row on repeated reads. This is a
defensive recheck under PostgreSQL READ COMMITTED, **not** an atomic lock
against an advance after the final read. An absent or malformed
`slate_date` is rejected with HTTP 422. Missing/false consent still returns
403 **before either the safe game list or the score archive is consulted**.
This ties ordering to a date and to historically visible games, but is not
user authentication; profile ownership remains a separate prerequisite.

A time budget uses a **uniform user-planned allocation** per game rather than
the actual game or highlight duration (which could leak outcomes). Both
optimization and unbudgeted ordering operate on internal scores; the response
still contains UUIDs only. Favorite teams are not accepted as ranking input.

This is a bounded application-boundary slice; it is not a live recommendation
quality claim. The first structured sports provider does not yet expose the
trusted feature history required to populate meaningful production scoring,
so an empty response is normal on unscored data. Real provider normalization, historical calibration and authenticated profile
ownership remain future work. Verdict integration and frontend consent are
described below.
Profile UUIDs are presently **opaque state keys, not authenticated accounts**;
the caller must not mistake this endpoint's consent check for user login or
authorization.

## Frontend consent boundary (#10)

`frontend/src/watchability.ts` validates backend-projected PREGAME slates,
1–32 unique canonical UUIDs and per-action `consentToOutcomeRanking: true`
before any HTTP call. It sends the NBA/Eastern date, IDs, consent and uniform
planned allocations. Its strict response boundary accepts only `game_ids`,
rejects extraneous postgame fields, unknown and duplicate IDs, and maps picks
back to allowlisted pregame card fields. HTTP error bodies are not surfaced.
`BackendClient.recommend` connects this helper through the same-origin proxy.
No fixtures, favorites or raw sports payloads enter the ranking path.

## Connected viewing guide and archived verdicts (#10)

The backend-connected UI now offers explicit postgame ordering on **Historically observed pregame** slates only. It requires a fresh
consent checkbox for each request and uses the strict client response boundary
through the same-origin `/api` proxy. Replay and observed/backfill slates are not
submitted to the historical recommendation API. The ordinary game list and
pregame guide retain their existing order; favorite teams never enter requests.
Picks are cleared when the cursor, date or schedule view changes, and stale in-flight responses are discarded. No eligible picks can mean
missing score evidence, never a poor-quality verdict. The UI has no time-budget
controls; the internal/API budget optimizer remains available to existing callers.
An unavailable per-game verdict does not show a Why action.

Explicit watchability/why reads now consult the newest eligible archived
`postgame-v1` score at the persisted cursor. Ordinary pregame/card reads and full
reveals do not read the score archive. The service rejects duplicate, corrupt,
wrong-family and future score evidence and projects only a coarse verdict through
`project_game`. Missing evidence replaces any snapshot hint with no verdict.
Reasons are not fabricated from components: WHY remains a separately requested
layer but has no reason until a trusted explanation producer is implemented.
Hints never acknowledge a game or advance the cursor.

Coarse bands are tunable via `RANKING_VERDICT_MEDIUM_FROM` (default 4),
`RANKING_VERDICT_HIGH_FROM` (7), `RANKING_VERDICT_LOW_LABEL` (Lower priority),
`RANKING_VERDICT_MEDIUM_LABEL` (Worth considering), and
`RANKING_VERDICT_HIGH_LABEL` (Worth watching). Defaults are provisional product
configuration, not calibrated NBA predictions; invalid bands fail configuration.

The separate [morning ranking processor](MORNING_RANKING_PIPELINE.md) now produces
four measured trajectory signals and archives hidden scores for per-game hints.
It does not manufacture pregame observations for ranked slate picks.

Issue #10 remains open: the current TheSportsDB importer does not produce vetted
ranking features or trusted final timestamps, so imported games normally have
no scores. Historical feature production, source approval history, calibration
against actual games and trusted reason production remain outstanding. Profile
UUIDs remain opaque state keys rather than authenticated user accounts.

The local workbench also offers a [v2 entertainment candidate](SCORING_ENRICHMENT.md)
with measured player production and extreme-game-pattern bonuses. These
read-only experiments preserve `postgame-v1` and public disclosure contracts;
no historical rarity percentile or pregame context is inferred.
