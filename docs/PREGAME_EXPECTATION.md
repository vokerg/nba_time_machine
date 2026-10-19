# Shared pregame expectation (#10)

The fan guide openly shows a **record-based matchup expectation**, its entering
W–L records, explanation and missing inputs. This first slice reuses the existing
schema-4 workbench formula; it does not claim a calibrated prediction of winning,
closeness or entertainment. The weak-team floor can produce zero with valid data.
Missing or insufficient records produce no score, never zero.

## One calculation, two uses

`ranking.pregame.record_preview` owns the existing settings and arithmetic.
The workbench imports it; it is no longer a separate implementation.

For each team, smoothed win rate is `(wins + 5) / (earlier games + 10)`.
Strength ramps from zero at .500 to one at .750. The smaller of the two strengths
is multiplied by sample confidence: the smaller games-played count divided by
20, capped at one. Both teams need at least three earlier games.

`pregame-records-v1` displays ten times that magnitude, on a 0–10 scale.
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
scoreboard claims must agree. The current reviewed scope remains 2025–26 regular
season; preseason, playoffs and the Cup final remain unavailable. No season
history is fetched. Actual source availability/observation timestamps remain intact.

In **Browse**, the expectation is explicitly labeled **Reconstructed from records
collected later; records only, not an archived pre-tip prediction**. It uses an
explicit open allowlist: only entering W–L, smoothed rates, formula, confidence,
missing families, version, source fact reference and actual timestamps. Final
records, removed win/loss, score, winner, game trajectory, box stats and actual
participation never enter this response. The expectation can exist even when
PBP is unusable or the game has no published overall rating.

**Time Machine withholds this reconstruction**, even at later cursors. This
slice does not manufacture a historically archived pre-tip prediction or connect
an upcoming-game collector. The legacy genuine pregame fields remain subject to
the existing policy. Future work can feed genuinely observed pre-tip records,
lineups and rankings into the same shared arithmetic; it must preserve the
explicit distinction between expected participation and actual minutes played.

No injuries, expected star availability, roster assumptions, expected closeness,
rest, rivalry, seeding or playoff leverage are invented. Those are listed as
missing. Ringer first-snapshot backfill and actual participation stay confined
to their existing retrospective/postgame use.

## Read and integrity contract

The guide GET adds a slate-scoped `expectations` map beside the existing safe
cards. Dedicated strict backend and frontend schemas reject incidental outcome
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
