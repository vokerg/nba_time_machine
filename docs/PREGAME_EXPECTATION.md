# Shared pregame expectation (#10)

The fan guide shows one **pregame expectation**, ranked roster names and
entering season records. Formula accordions, ranks, model metadata, confidence
and missing-input paragraphs belong in admin tooling, not consumer cards. It reuses the existing workbench formulas; it does not claim a calibrated prediction of winning,
closeness or entertainment. The weak-team floor can produce zero with valid data.
Missing or insufficient records produce no score, never zero.

## One calculation, two uses

`ranking.pregame.record_preview` owns the existing settings and arithmetic.
The workbench imports it; it is no longer a separate implementation.

For each team, smoothed win rate is `(wins + 5) / (earlier games + 10)`.
Strength ramps from zero at .500 to one at .750. The smaller of the two strengths
is multiplied by sample confidence: the smaller games-played count divided by
20, capped at one. Both teams need at least three earlier games for a record-strength bonus.
Validated entering W–L records still appear before that minimum is reached.

`pregame-records-v1` displays ten times that magnitude, on a 0–10 scale.
With pre-tip stars, `pregame-context-v2` combines available component ratings
using their existing maximum bonuses as weights: records 2, stars 1.5. A stars-only
expectation remains available when preseason records are ineligible; no missing
record term is imputed as zero.
The exact existing workbench bonus, up to **2 points**, also enters the new
production `postgame-records-v2` model: legacy trajectory/drama score plus the
shared matchup bonus, capped at ten. The model and source fact reference are
archived in the existing immutable recommendation-score table. Reprocessing via
**Fetch games & update ratings** appends a new snapshot; reads never write one.
There is no new persistence path or provider request.

Old v1 snapshots are never rewritten. A currently valid records-equipped game
needs its new v2 snapshot before its overall rating is displayed; a stale v1
snapshot is not presented as the new model. Where record context is unavailable,
the existing v1 trajectory model remains available and is labeled by its version.
Zero record strength with valid inputs still produces v2. Favorite teams never
enter either formula. Fan breakdown contributions are proportionally reduced when
the ten-point cap applies, so their displayed points add to the displayed rating.
The workbench retains its existing explicit cap adjustment.

## Reconstructed versus genuinely known before tip

The available source is validated ESPN **completed-game** records, with that
specific game's result removed by the existing `game_record_context`. Summary and
scoreboard claims must agree. Supported records cover the 2025–26 and 2026–27 regular seasons; preseason,
playoffs and the Cup final remain unavailable. The 2026–27 calendar guard is a
generous October-to-June season bound, not an inferred actual opener or closer;
matching source season/competition types determine regular-season scope. No season
history is fetched. Actual source availability/observation timestamps remain intact.

In **Browse**, historical entering records retain an explicit reconstructed basis
and actual timestamps in the API/admin evidence. The consumer card shows only
W–L, without repeating temporal implementation prose. It uses an
explicit open allowlist: only entering W–L, smoothed rates, formula, confidence,
missing families, version, source fact reference and actual timestamps. Final
records, removed win/loss, score, winner, game trajectory, box stats and actual
participation never enter this response. The expectation can exist even when
PBP is unusable or the game has no published overall rating.

**Time Machine withholds record reconstruction**, even at later cursors. It can
show genuinely known-before-tip roster star potential when the schedule, ranking
and both rosters are known by the saved cutoff. Upcoming observed matchups can
therefore receive a stars-only expectation without completed-game evidence. No
new collector or timestamp backdating is introduced. Genuine pre-tip team records
and lineups remain future work.

No injuries, confirmed star availability, expected closeness,
rest, rivalry, seeding or playoff leverage are invented. Those are listed as
missing. Ringer first-snapshot backfill and actual participation stay confined
to their existing retrospective/postgame use.

## Read and integrity contract

The guide GET adds slate-scoped `expectations` and independent `entering_records`
maps beside the existing safe cards. Records can be present with no pregame rating. Dedicated strict backend and frontend schemas reject incidental outcome
fields. The legacy game-list/card API is unchanged. Ordinary card membership,
completion state and chronological ordering remain unchanged. Only the openly
labeled pregame recommendation section orders by the public expectation.
Postgame order, exact overall ratings and explanations still require explicit
spoiler consent.

The reader reuses the batched morning-pipeline source policy, canonical identity,
observation/fact revision alignment and validity checks, independently of PBP.
Missing, conflicting, expired or revoked latest evidence withholds context rather
than falling back to a clean older revision. Overall archive verification checks
version, arithmetic and all components against current evidence. Existing guide
revision invalidation covers the reused facts and source policy. Prepared-day
expectations are cached with the same revision; no permission is cached.

Validation uses synthetic evidence and disposable local PostgreSQL, including
open response field isolation, strict-mode withholding, independent PBP failure,
new revision masking, source revocation, additive/cap arithmetic, immutable
archives, shared workbench contribution, browser DOM behavior and safe parsing.
No live provider collection or owner database changes are part of verification.

## Shared Star Power, including preseason

`team_star_power` and `matchup_star_power` now serve both the existing workbench
and the pregame/production paths. Rank values use the existing nonlinear curve.
The top three ranked roster players receive slot weights 1, .4 and .15; team
strength is their sum divided by 1.55, capped at one. The two-team metric is
`.4 × max(home, away) + .6 × sqrt(home × away)`. Star potential is that metric
on a ten-point scale. Its 1.5-point potential bonus is not a promise that all
stars will play. The score still uses only the three weighted slots, while the
card exposes every ranked roster player through `ranked_players` so players
outside those slots are not mistaken for unranked or missing players. The card
labels this as a Top 100 roster view with availability unconfirmed. Pregame
includes every ranked roster player regardless of injury; there is no
injury/availability filter or discount. This does not add a player whom the
publisher omitted from the ranking; missing rank data is not invented.

Only a complete, signature-validated same-season Ringer snapshot genuinely
observed before tip is eligible. Existing permission and retention checks apply;
no publisher request or first-snapshot backfill is used. ESPN identity-only team
facts must also predate tip and the knowledge cutoff, match the canonical ESPN
team identity/name and pass validity/schema checks. Duplicate player membership,
missing rosters, invalid latest revisions and revoked sources withhold the star
component. Snapshot and roster reads are batched and revision-signature cache
invalidation now includes those season/team facts. No game box or actual minutes
enters the public expectation.

`postgame-stars-v3` adds up to 1.5 points of **realized** Star Power to the existing
v1 drama or v2 drama-plus-records model. It uses the same pre-tip ranking, curve,
slots and two-team metric, but applies the existing verified actual-minutes factor.
It replaces the conceptual roster-potential contribution; potential and realized
stars are never summed. Missing or inconsistent participation withholds this
family rather than assuming full minutes. The existing archive retains the exact
ranking/box fact references and re-verifies every displayed score. All three
production versions remain readable with their own validated arithmetic. No
old row is rewritten, and reads never publish ratings.

Read-only verification for October 16, 2026 TOR–DET found a complete pre-tip ranking
and both pre-tip rosters. The shared reader returns 7.6/10 star potential, with
three contributing players per team (Toronto has a fourth ranked roster player,
excluded by the existing top-three rule), despite ineligible preseason records.
The fan guide keeps those three scoring slots separate from its complete
`ranked_players` roster display, so the fourth player remains visible without
changing the score. This is roster reputation potential, not a verified lineup
or calibrated game quality prediction. No provider collection or owner-database
writes were performed.

### Players absent from the ranking (owner follow-up)

A compact **Not in Top 100** disclosure shows per-team counts and names from the
validated pre-tip roster that are absent from the complete selected ranking.
This is set membership by stable ESPN ID, not injury or game availability.
Ranked players outside the three scoring slots are exposed separately in
`ranked_players` and are not labeled unranked. The consumer summary uses
parenthesized per-team counts, with names available on expansion to keep
ordinary cards compact. Missing ranking entries do not receive invented ranks
or change scoring. The same roster/ranking provenance and Time Machine cutoff
apply to both lists. Neither list establishes who is inactive or unavailable
for today's game; a trusted availability source is still required for that.

### Genuine scheduled-game records (#10 continuation)

The existing explicit day collector now captures ESPN scheduled summaries as well
as finals. Both scoreboard and summary must identify a scheduled, unstarted game;
the summary period must be zero, with no scores, plays, winner or period totals,
and actual collection must precede the matching scheduled tip. Regular-season
scope, supported season, Cup Championship exclusion and matching total W–L claims
remain required. Preseason totals never substitute for regular-season records.

Scheduled evidence stores `entering_records` separately from completed-game
`records`. Its canonical observation is `scheduled`, with null scores. Captures,
facts, deduplication, source permissions and timestamps use the existing storage
path. No scheduler or backdating is introduced; operators must collect before tip
to preserve genuine pre-tip knowledge. Later collection cannot recreate it.

Browse and Time Machine prefer validated genuine pre-tip records. Time Machine
also bounds both observation and availability by its saved cutoff. The reader
selects the latest pre-tip observation before validating its matching fact; a
missing, ambiguous, expired or corrupt latest fact does not resurrect an older
record. Canonical game/team/season identities and the current scheduled tip must
agree. Canceled, postponed and suspended current states suppress the context.
Records remain usable after final when those checks pass. Later reconstructed
records remain Browse-only fallback when no genuine records are available.

The existing formula and weights are unchanged. Genuine records display even
below the three-game scoring minimum. When they support a rating, the very same
record component and its pre-tip provenance feed the overall rating; later final
totals do not replace it. Stars still use roster potential pregame and verified
actual minutes postgame. API `basis: known-pre-tip` now applies to records-only
and combined expectations, as well as stars-only expectations. Consumer card
layout and disclosure controls are unchanged.

Pre-tip record reads add one bounded batch query, shared by expectation and
archive verification; the cold guide budget is now sixteen SELECTs on the
existing fixture, with the same three-read warm disclosure and two-read warm GET.
