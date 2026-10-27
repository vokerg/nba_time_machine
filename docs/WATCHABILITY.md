# Production watchability (#116)

The guide and local scoring dashboard use one production calculation,
`postgame-watchability-v4`, derived by `MorningRankingPipeline`. The dashboard
has one rating and component breakdown; it has no proposed/live comparison or
formula-adoption step. Earlier workbench configurations remain historical
calculation fixtures, and earlier archives remain immutable.

The final rating is the sum of available contributions, capped at 10:

- Drama: the existing clutch, lead-change, comeback and overtime calculation.
- Exceptional player production: up to 4 points.
- Exceptional game magnitude: up to 3 points.
- Entering-record strength: up to 2 points, using the existing pregame calculation.
- Realized Star Power: up to 1.5 points, using pre-tip rank and verified minutes.

Pregame expectation remains a separately labeled pre-tip projection. Actual game
statistics never enter that open projection. The postgame rating, ordering and
reasons continue to require existing disclosure consent and the knowledge cutoff.

## Exceptional player thresholds

| Axis | No credit through | Full axis credit at |
| --- | ---: | ---: |
| Points | 40 | 60 |
| Assists | 15 | 25 |
| Rebounds | 20 | 30 |
| Steals + blocks | 8 | 12 |

Each axis ramps linearly from zero to one. Severity uses the strongest axis plus
15% of the next two, supported by shooting efficiency (50–75% true shooting,
up to 10% of scoring magnitude) and triple-double credit (10%, only when an
exceptional axis is already positive). Turnovers deduct up to 10%. Severity is
clamped to zero–one. An ordinary 25-point outing or 10–10–10 earns zero.
The strongest performance plus 25% of the runner-up determines the bounded
4-point contribution. All participating players qualify equally, regardless of
ranking, identity, team or favorites. A role player's 60-point game can earn
the full contribution; turnovers and efficiency still participate in the formula.

These are explicit entertainment heuristics, not historical rarity percentiles
or deviations from an individual player's career average. Unexpectedness relative
to a player's usual production is not claimed without historical baselines.

## Game magnitude

Existing measured patterns now contribute in production: overall lead 20–60,
first-half lead 15–40, quarter margin 20–40, low regulation quarter below 15,
high regulation quarter 35–55, and scoring drought 4–12 game-clock minutes.
Overall lead, first-half lead and quarter margin form one dominance group;
low/high quarter and drought form a scoring-extremes group. Each group uses its
maximum, then the stronger group plus 20% of the other is capped at one and
multiplied by 3. Correlated observations cannot be added repeatedly.

## Evidence, publication and history

Complete verified trajectories remain required. Missing or invalid player boxes
omit the performance family; the dashboard reports it missing. Zero is reserved
for valid evidence that earns no credit. Ranking snapshots must genuinely predate
tip-off; the dashboard no longer applies retrospective first-snapshot assumptions.
Publication archives the calculation with its model version, source fact references
and actual timestamps. Reads use the saved snapshot and check its schema, arithmetic, source permissions
and knowledge cutoff; they never run the scoring pipeline. Existing archives stay
usable across server restarts, source corrections and formula changes until the
owner explicitly recalculates. A formula change does not silently replace a rating.
Source permission revocation can withhold access without recalculation or deletion.
Explicit updates append snapshots and leave prior history intact. If recalculation
cannot produce a valid new score, the last successful saved rating is retained;
the update reports unavailable/failed games rather than inventing a replacement.

Migration `0011_saved_rating_details` adds an optional JSON breakdown to the existing
score row. New publications save player, magnitude, record and Star Power details
atomically with the rating. Older rows remain readable without an automatic
backfill; their missing detailed inspection is labeled until explicit recalculation.
Admin loads one bounded batch of saved ratings/details. Full source evidence is
fetched only when its disclosure panel is opened, without assessment or scoring.

Both the guide's **Fetch games & update ratings** and the scoring dashboard's
corresponding action collect and publish this formula. The dashboard also offers
**Recalculate saved ratings** with no network collection. The guide also offers **Recalculate saved ratings** without collection. Loading
either dashboard does not reveal games or move a user's timeline. Read-only
dashboard sessions remain enforced by PostgreSQL. Publication runs in separate,
explicit write transactions; failures for one game do not prevent other games
from committing. Publication status distinguishes calculated from saved evidence,
without displaying competing scores.

The main guide footer links to the scoring dashboard on `127.0.0.1:8765` and the
operator dashboard on `127.0.0.1:8766`. These remain separate local processes.
