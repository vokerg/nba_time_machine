# Scoring integration review — 2026-10-15

PRs #86 and #88 were reviewed with the Watch Queue (#92) and reviewed News &
Buzz feed (#93), against main `597afd8`. Both branches integrated main without
textual conflicts. The newer work did not change ranking modules or scoring
contracts. This document records the combined domain contract for testing.

## Evidence to product

1. Reviewed collectors retain captures according to source policy. With
   `normalized_full`, normalized evidence is retained; the raw provider response
   is not. Capture and interpretation remain distinct layers, with separate
   collection/availability and processing timestamps.
2. The explicit morning processor revalidates complete final trajectories,
   provider identity, source policy and temporal provenance. It archives four
   deterministic drama signals and a hidden `postgame-v1` score. Corrections or
   revoked source approval withhold obsolete scores without erasing history.
3. Consumer disclosure uses existing deterministic gates. Numeric scores and
   evidence stay internal; hints and ranked picks require their own explicit
   actions/consent. Historical replay does not invent pregame knowledge.
4. The separately launched, loopback-only scoring workbench reads the same DB
   in repeatable-read, database-enforced read-only transactions. It compares
   archived ratings, the reproduced baseline and a tunable candidate. Exports
   contain explicit config/review sessions; imports recompute from evidence.
5. The v2 candidate adds bounded player-production and extreme-pattern bonuses
   to drama, capped at ten. Raw stats, normalizations, terms, grouping, caps and
   evidence references are visible. This is a tuning preview: merging the code
   does not activate v2 or rewrite archived ratings.

See [morning processing](MORNING_RANKING_PIPELINE.md),
[workbench operation](SCORING_WORKBENCH.md) and
[candidate formulas](SCORING_ENRICHMENT.md).

## Compatibility with the new main features

| Surface | Owns | Scoring interaction |
| --- | --- | --- |
| Watch Queue | Personal membership, insertion order, queued/done/dismissed state | No score-dependent ordering or implicit hint/reveal; done does not acknowledge a game. |
| News & Buzz | Revision-specific rights/safety review and global timeline projection | Sports captures and calculated scores do not create approved media. A game reveal does not advance the media cursor. |
| Ranking | Versioned evidence and canonical quality comparison | Favorites and queue state do not change the score. No media-review bypass. |
| Workbench | Local operator inspection and experimental calculation | No consumer routes/assets, queue mutations, acknowledgements, timeline writes or model adoption endpoint. |

The two existing new-main migrations, `0009_watch_queue` and
`0010_media_reviews`, form one linear migration chain after `0008`. Scoring
introduces no migrations or alternate canonical database. Apply normal forward
migrations before exercising queue/media against an older configured database.
Never run integration tests or rollback migrations against the owner's DB.

## Combined validation

- Backend regression includes a cross-feature test that archives a rating and
  inspects a later v2 candidate while an earlier consumer cursor stays fixed.
  Its done queue entry remains sealed, the queue response is unchanged, raw
  sports evidence does not appear in the reviewed media feed, and no explicit
  acknowledgement is created.
- Existing queue/media suites cover their own ordering, stale-cursor,
  revision-specific review, rights and spoiler gates. Workbench tests cover
  read-only rejection, unchanged archives, partial families and legacy imports.
- Fresh disposable PostgreSQL verifies the full migration chain, latest
  revision rollback/upgrade, metadata parity and the combined backend suite.
- Frontend tests cover queue/media and disclosure behavior; four standalone
  workbench DOM tests cover config/review recomputation and rendering. The
  production frontend build validates TypeScript and bundling.

The first local combined run passed 420 tests and hit the previously observed
macOS process-group cleanup PermissionError in `test_dev_launcher.py`. All
eight launcher tests passed on immediate isolated rerun. A second full run on a
fresh database passed all **421 backend tests**. All **38 frontend tests**, **four
workbench DOM tests** and the frontend build passed. No launcher change is part
of these scoring PRs; hosted Linux CI is also required before merge.

## Limits to carry into testing

Star power, standings/playoff stakes, team-strength context and historical
rarity percentiles remain unimplemented. Player magnitude and extreme patterns
are transparent provisional heuristics. Missing evidence remains missing, not
zero. No AI, automatic daily scheduler or automatic v2 activation is included.
An empty reviewed media feed can mean unavailable coverage; merging does not
enable sources or clear publisher rights. Existing stored game coverage is not
a promise of a complete or freshly collected slate.
