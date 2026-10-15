# Game-supplied records for matchup importance (#96)

The default workbench proposal is **entertainment-records-v4**. It uses the two
season records already attached to the game response. It does **not** fetch,
query or reconstruct season history. Existing drama, player performances,
extreme patterns, total cap and archived app ratings keep their contracts.

## Source records and exact adjustment

The reviewed ESPN scoreboard exposes each competitor's `records[type=total]`;
the corresponding summary exposes `header.competitions[].competitors[].record`
with a `type=total` row. The collector retains both numerical claims and requires
them to match. For completed regular-season games these fields include that
game's result. This observed provider convention was checked against the earlier
November 10 history; it is not a promise of a licensed/documented historical API.

For example, the Wolves–Jazz response supplies 7–4 and 3–7. Minnesota won, so
removing one win/loss yields **Minnesota 6–4 and Utah 3–6 entering the game**.
This is a one-game adjustment of supplied records, not a season replay.

Each team shows its source record after the game, the removed result and its
entering record. Both endpoints must agree, source winner flags must agree with
the final score, records must be unambiguous nonnegative W–L pairs with at most
82 games, and the result must be removable. The reader revalidates retained
claims and rejects records exceeding the number of elapsed season dates. Pending
games, unsupported seasons, preseason/postseason, unknown competition scope,
NBA Cup Championship, missing totals and conflicting claims give **unavailable
importance**, independently of otherwise usable PBP/player boxes. The Cup final
is excluded through the scoreboard competition type 39, despite season type 2.

The first reviewed season/calendar remains 2025–26. The underlying evidence
schema gains optional record fields, so older stored captures remain readable;
they cannot fabricate records and must be explicitly re-collected to obtain
them. Current v1 scores still derive from trajectory data, not these records.

## Formula and missing context

`config/ranking/entertainment-records-v4.json` uses schema 4 and an explicit
`importance` settings object. The UI exposes every setting and term:

| Term | Default |
| --- | --- |
| Minimum earlier games per team | 3; smaller samples make the bonus unavailable |
| Smoothed entering win rate | `(entering wins + 10/2) / (earlier games played + 10)` |
| Per-team strength | Ramp smoothed win rate from .50 to .75, limited to 0–1 |
| Both-team strength | The smaller of the two strengths |
| Sample confidence | Smaller games-played count / 20, limited to 1 |
| Importance bonus | `2 × both-team strength × sample confidence` game-score points |

An ordinary weak-vs-strong matchup can earn zero with complete data. Missing
records earn no estimated contribution and explicitly mark the proposed total
incomplete. The v4 total includes the available importance bonus alongside the
same drama/player/pattern contributions, with its uncapped sum and cap/rounding
adjustments visible. Changing importance settings never rewrites app ratings.

Two records establish win rates, **not league/conference ranks, true leader
status, seeding stakes, playoff odds, clinching or elimination**. Those fields
are explicitly unavailable in v4, and there are no hidden rank/race settings.
Conference membership is display metadata from the reviewed season mapping;
it does not supply a rank. Star power remains a separate assignment.

Schemas 1/2 keep their existing formulas. Explicit imports of the earlier
[schema-3 formula](GAME_IMPORTANCE.md) retain the optional reconstructed-history
calculation for comparison. Restoring the default selects v4. Legacy settings
are not silently applied to the new formula or vice versa.

## Collection, persistence and time

No new collector is needed. Use the existing bounded morning entry point:

```bash
cd backend
.venv/bin/python scripts/collect_nba_morning.py --date 2025-11-10 --write --manual
```

Access, cadence, no-auth fixed ESPN endpoints, request/body/time bounds,
no-redirect/retry policy, deduplication, source policy/locking and normalized-full
retention remain as documented in [morning collection](NBA_MORNING_COLLECTION.md).
This extension retains only numerical records and explicit interpretation/scope
metadata; original provider JSON/prose is not retained. Representative synthetic
records and endpoint shapes are in `tests/test_game_records.py`.

Collection/availability stay at actual observation time. The game date and the
inferred entering record do not become historical observation timestamps. These
facts are for local retrospective tuning and never become strict pregame ranking
facts or pass directly into consumer/AI projections.

Re-collection appends normalized evidence revisions through the existing store.
The current pipeline correctly withholds archives referencing an older input
revision. Explicit processing can append a new v1 snapshot for the updated
capture; it does not overwrite older ratings. Equal trajectory inputs should
produce equal numeric v1 scores despite new provenance. No v4 adoption occurs.
