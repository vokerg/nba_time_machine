# Inspectable entertainment candidate v2 (#87 / PR #88)

The v2 formula is defined in `config/ranking/entertainment-preview-v2.json`.
The workbench now defaults to [v3](GAME_IMPORTANCE.md), which retains these terms
and adds game importance; v2 imports still calculate their original formula.
This is a read-only experiment against real stored evidence, compared with the
saved `postgame-v1` rating and its four-signal baseline. No production rating,
source evidence, source policy, profile cursor or acknowledgement is changed.

Candidate score is `min(10, rounded drama score + player bonus + pattern bonus)`.
The report records uncapped value, cap adjustment and final rounding separately.
This preserves exceptional-performance credit even for non-clutch, one-sided games.
All settings are provisional heuristics, not calibrated historical percentiles.

## Player production

Only a complete box family is accepted. Validate nonnegative integer counts,
shooting makes/attempts, points arithmetic, rebound arithmetic and team totals.
DNP rows are excluded; played players from either team qualify. IDs and references
remain provider-namespaced; names/favorites do not influence the calculation.

Four axes use `clamp((raw - floor)/(peak - floor), 0, 1)`:

| Axis | Floor | Peak |
| --- | --- | --- |
| Points | 25 | 60 |
| Assists | 8 | 20 |
| Rebounds | 12 | 30 |
| Steals + blocks | 4 | 12 |

Player severity is the clamped sum of:

- strongest axis;
- 0.15 times the next two strongest axes;
- 0.10 times scoring magnitude times efficiency magnitude;
- 0.10 triple-double credit;
- minus 0.10 times `min(turnovers / 10, 1)`.

Efficiency ramps from 50% to 75% true shooting.
`TS = PTS / [2 × (FGA + 0.44 × FTA)]` ([NBA definition](https://www.nba.com/stats/help/glossary)).
It is undefined with no attempts, yielding no shooting support; the raw
approximation can exceed 100% and is preserved. Minutes retain their source
precision and are never extrapolated into per-minute performances.

Player bonus is `4 × min(1, strongest severity + 0.25 × runner-up severity)`.
Only two players contribute; participant count cannot multiply the bonus. The
workbench lists all participating players (top eight initially), with selectable
per-player raw statistics, axes, floors/peaks, signed terms and source references.
All thresholds, multipliers, turnover penalty and maximum bonus are editable.

## Extreme game patterns

A complete revalidated trajectory is required. No clock/score repairs are made.
Each measurement retains team, period and supporting source play IDs.

| Pattern | Starts beyond | Full credit at |
| --- | --- | --- |
| Largest lead at any point | 20 points | 60 points |
| Largest first-half lead at any point | 15 points | 40 points |
| Largest regulation quarter margin | 20 points | 40 points |
| Lowest regulation quarter, one team | Below 15 points | 0 points |
| Highest regulation quarter, one team | Above 35 points | 55 points |
| Longest team scoring drought | 4 minutes | 12 minutes |

Increasing extremes use the floor/peak ramp. Low-quarter magnitude uses
`clamp((ceiling - points)/ceiling, 0, 1)`, with default ceiling 15. These are
continuous ranges, not exact conditions for illustrative examples. Quarter
measurements exclude shorter overtime periods. Droughts use elapsed game-clock
time across periods, exclude breaks, and retain both boundary events/times.

Correlated measures are grouped before scoring. **Dominance** is the maximum of
overall lead, first-half lead and quarter margin. **Scoring extremes** is the
maximum of low quarter, high quarter and drought. Pattern bonus is
`3 × min(1, strongest group + 0.20 × second group)`. One runaway stretch therefore
cannot be added three times within a group. Every measurement/ramp and the group
arithmetic are visible in the workbench. All floors, peaks and caps are editable.

## Coverage, formats and activation boundary

Family coverage is independent: valid player boxes remain inspectable when PBP
is partial, but the combined candidate is withheld if canonical trajectory,
finality or identity eligibility fails. Eligible PBP with missing/invalid boxes
produces an explicitly **partial** preview: player bonus is `null`, not a measured
zero or an estimated performance. No historical rarity percentile is fabricated.

The measurement version is `entertainment-measurements-v1`. Reports include exact
settings and source provenance. Schema-2 configs require explicit `player` and
`pattern` settings as well as the existing drama weights/scales/thresholds. Finite
bounds and ordered floor/peak values are validated. Schema-1 configs and review
sessions remain readable and reproduce the original four-signal preview without
silently enabling bonuses. Restore default formula restores the current checked-in default (now v3). Import the v2 file explicitly to compare its original formula.

Clutch and drought controls display minutes and convert back to stored
milliseconds. Exports include all compared settings and optional reviewer notes.
No production activation endpoint is added: tune and review the candidate before
adopting a new production score version in a separate explicit change.

Star power, matchup strength, standings/playoff/seeding stakes, rivalry, historical
rarity and subjective/tactical game quality remain unavailable. AI is not used.

## Verification

Verified on October 15, 2026: **404 backend tests** passed on fresh disposable
PostgreSQL and **four DOM tests** passed, including minute conversions, v2-setting
round trips and legacy imports. Synthetic trajectories cover continuous early
blowouts, scoreless quarters, droughts, OT exclusion and correlated-pattern grouping;
box tests cover independent family failures, DNP, shooting/rebound consistency,
undefined efficiency, bounded bonuses and final-score clamping.

The running owner-database workbench exposes six valid player-box families and
five complete pattern families/combined candidates. Setting both bonus caps to
zero reproduces the saved-model baseline; player terms and score adjustments
reconcile, and owner fact/score counts remain unchanged. Sanitized checks are in
[evidence](evidence/entertainment-candidate-2026-10-15.json). No new production
ratings, historical percentiles or AI annotations were generated.
