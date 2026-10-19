# Morning NBA collection (#84)

The owner accepts once-daily morning-after availability for a personal $0 project.
The new `sports/morning.py` path uses ESPN scoreboard/summary JSON first, then CBS
schedule/GameTracker HTML when discovery or a game's primary evidence fails or is
partial. It imports one **Eastern NBA calendar date**, including overnight UTC
games, without fetching seasons. Default date: yesterday in America/New_York.

## Viewing guide action (#111 follow-up)

The local consumer app now offers **Fetch games & update ratings** for one selected
Browse date. It orchestrates this same bounded collector followed by the existing
production rating processor; it does not require a terminal or the workbench.
Progress is score-opaque, and source policies/actual observation times remain
unchanged. See [Viewing guide](VIEWING_GUIDE.md#fetch-games--update-ratings-owner-follow-up).
Selecting a date alone still reads stored data, and no daily job is installed.

## Commands

From `backend/`, a read-only run makes bounded HTTP requests and prints only
counts/health. It does not load database settings or open a database connection:

```bash
.venv/bin/python scripts/collect_nba_morning.py
.venv/bin/python scripts/collect_nba_morning.py --date 2026-10-13 --game 401898718
.venv/bin/python scripts/collect_nba_morning.py --date 2026-10-13 --provider cbs --game NBA_20261013_GS@LAL
```

To persist, first sync the reviewed source seed through the existing registry
workflow, then explicitly select write mode:

```bash
.venv/bin/python scripts/collect_nba_morning.py --date 2026-10-13 --write --manual --report /tmp/morning-health.json
```

`--write` uses the configured PostgreSQL database. `--manual` permits verified,
disabled sources for this operator invocation; it does not enable them or weaken
retention. Both `espn-nba-games` and `cbs-nba-games` must have the expected fixed
locator/adapter, be verified, not require authentication, and use
`normalized_full` retention. A changed policy is rechecked under a row lock
before each write and discards in-flight evidence. Seeds remain **disabled**.
Verification here means tested access/parser behavior, not complete coverage or
a provider license. The generic RSS/web collector does not dispatch these adapters.

No scheduler is installed. An eventual personal morning job can invoke this same
CLI once per day with explicit `--date` and `--write`; enabled verified registry
rows are required without `--manual`. The 1440-minute cadence is scheduling intent,
not an enforced once-per-day lockout; manual reruns are idempotent. Exit 0 means
the requested games have usable PBP and boxes, or a verified ESPN empty slate.
Exit 2 means partial/pending/missing evidence or errors. Inspect the report before
rerunning a day; incomplete games are never silently called successful.

## Provider contract

| Field | ESPN | CBS backup |
| --- | --- | --- |
| Access | Fixed HTTPS scoreboard `?dates=YYYYMMDD`, summary `?event=ID` on `site.api.espn.com` | Fixed HTTPS `/nba/schedule/YYYYMMDD/` and `/nba/gametracker/playbyplay/NBA_YYYYMMDD_AWAY%40HOME/` |
| Auth/cost | None; $0 | None; $0; no client-bundled tokens used |
| Discovery | Validates event date, home/away, unique matchups | Exact dated GameTracker links; deduplicated; an empty/changed HTML page is unverified |
| Identity | Event/team/player source IDs; unique PBP IDs | Numeric embedded game/team IDs and linked player IDs; **no manufactured PBP IDs** |
| Cadence | One date per manual/daily invocation | Requested only when primary fails/partial, or explicit backup smoke |
| Request limits | Shared default 40 requests, maximum 100; at least one second between default requests; maximum 20 games | Same shared budget |
| Time/size | 20-second request deadline including body, 4-MiB decoded-body cap | Same, plus HTML depth limit |
| Errors | No retries; one same-game CBS canonical redirect only (see below); 401/403/429 stops that host for the remainder of the run; Retry-After recorded | Other provider remains independently available |
| Retention | Selected normalized statistics/actions/IDs and coverage only | Same; descriptions, articles, ads, scripts, tokens and HTML are excluded |
| Full content | Never supplied to persistence | Never supplied to persistence |

No published provider quota or uptime contract is claimed. The previous
[live validation](NBA_FRESH_DATA_VALIDATION.md) documents technical access and
source terms; personal-use assumptions do not turn website interfaces into
licensed or stable APIs. No paid feeds, browser impersonation, CAPTCHA or access
control bypass is used.

## Coverage and fallback

Each response becomes a separate typed `Evidence` record. The run report selects
the first usable provider **per family**, but does not splice providers' actions
or player rows into a combined stream. Fallback must match NBA date and both
teams; when ESPN supplied a scheduled tip, CBS must agree within 30 minutes.
Independent primary and fallback errors remain in the report. Pending scoreboard
games are listed but not fetched as completed games.

PBP validation requires source event identities, source order with nonincreasing
period clocks, every regulation/OT period and zero-clock end, period totals and
terminal score reconciliation, tied OT boundaries, and ordinary scoring
transitions. ESPN sequence numbers/wall clocks are preserved as source claims
where relevant but **never used to reorder the array**. Unexplained score
regressions or scoring-event discrepancies mark the trace partial unless the
explicit, fully reconciled scoring-action interpretation below succeeds. No
inferred action revision is attempted. This is structural/internal reconciliation, not
an independent audit of every scorer event.

Player boxes preserve source player IDs, starter/participation state, shooting
and counting statistics, minutes and their precision. Explicit DNP differs from
missing statistics. ESPN integer minutes are rounded; they are not exact seconds
and need not sum to 240. Player points must sum to the supplied team scores.
Box parsing failure does not discard valid PBP. Participant-to-box identity checks
are explicitly unverified when boxes are incomplete.

CBS is an implemented **partial backup**, not a certified complete trajectory
source. The tested mandatory game exposes 473 PBP rows with no event IDs and one
clock reversal. It has 35 linked roster rows and 30 numeric player rows, but five
rows contain only dashes, so their participation stays unknown and the full box
family is marked incomplete. The observed rows are still retained with coverage
errors. No missing minutes, DNP flags, source end timestamp or stable event IDs
are fabricated. A total ESPN outage therefore can yield useful CBS observations
and partial statistics while still exiting 2. This prevents a failed backup from
becoming trusted ranking input.

## Existing persistence and temporal safety

Write mode uses existing `collection_runs`, `source_outcomes`, `source_items`,
`raw_captures`, `sports_external_identities`, `game_observations` and
`temporal_facts`; there is no new schema or separate persistence store. The same
sports advisory lock prevents overlap with existing season ingestion. Games
commit independently; ambiguous identities are quarantined and recorded.

Team mappings first reuse a unique canonical NBA team name (including the two LA
Clippers spellings). Games reuse a unique season/home/away/Eastern-date matchup
from existing observations. Ambiguous teams/games fail closed. Provider mappings
then preserve stable internal game/team UUIDs. Player IDs remain **provider
namespaced inside game-linked evidence**; canonical player UUID reconciliation
is not claimed, particularly for CBS's abbreviated names.

Normalized snapshot hashes exclude retrieval timestamps. Identical repeats do
not append captures/facts/observations or move first availability. Changed
snapshots append a revision, including reversion to earlier values. No original
JSON/HTML/prose is stored. `provider_game_evidence` facts contain selected numeric
actions/statistics and explicit coverage; partial evidence remains marked partial.

`observed_at`, capture/discovery and `available_at` use actual response observation
time. Source wall clocks/update/end markers remain **claims** inside normalized
evidence; publication, actual tip and trusted `final_at` remain unknown. Historical
manual runs cannot manufacture pre-tip knowledge. No scorer, ranking archive,
policy layer, AI context or UI reads are changed by this issue. Importing evidence
does not itself create watchability recommendations.

The separate [morning ranking processor](MORNING_RANKING_PIPELINE.md) can now
derive versioned trajectory features from complete stored evidence and archive
hidden scores for explicit per-game hints. Collection alone does not run it.

## Validation

Generated synthetic fixtures: `backend/tests/morning_fixtures.py`. Offline tests
cover parsing, malformed/partial data, date/matchup mismatch, source-order handling,
family isolation, fallback, access denials, budgets and body/redirect limits.
Disposable PostgreSQL tests cover replay, append-only revisions, shared game
identity, policy revocation and ambiguous canonical matching. Live diagnostic
smokes use the real October 13 game and retain counts/health only.

Verified on 2026-10-14:

- **352 backend tests passed**, including all existing integration tests and the
  new parser/persistence cases, against a fresh disposable local PostgreSQL DB.
- Real Warriors–Lakers write smoke: 2 HTTP 200 requests, 504 plays, 34 player rows,
  one normalized capture/fact; immediate replay wrote **zero** captures.
- Real five-game October 13 dry run: 7 requests; four usable ESPN traces and five
  usable ESPN boxes. POR–SAC's score corrections triggered an actual CBS fallback,
  whose 520 rows also stayed partial. The CLI correctly exited 2 rather than
  pretending that all five trajectories passed.
- [Sanitized live run evidence](evidence/issue-84-morning-smoke.json) contains the
  write/replay/day reports. No raw provider bodies were retained, no owner Neon
  database was used, no scheduler was installed, and no PR was created.


### Game-supplied record extension (#96)

The ESPN scoreboard/summary parsers now retain optional matching overall W–L
claims, season/competition scope and independent record diagnostics, using the
same normalized retention boundary. Missing records do not invalidate otherwise
usable play-by-play or boxes. Morning diagnostics expose `has_game_records` and
`record_errors`; exit success still refers to the existing PBP/box contract.
The local [v4 importance formula](GAME_RECORD_IMPORTANCE.md) removes the completed
game's win/loss from these totals, without a season-history dependency. Historical
captures lacking this optional metadata remain readable and need explicit
re-collection to obtain it. Observation/availability timestamps are never backdated.

## Evidence recovery (#107)

ESPN sometimes returns HTTP 200 with stale running scores attached to otherwise
identified, clock-ordered actions. The parser now retains each action's scoring
team ID. If the only trajectory failures concern score states, it attempts the
explicit `scoring_actions_v1` interpretation: accumulate each action's declared
one/two/three points for its declared team, in unchanged array order. Every action
must explicitly declare scoring/non-scoring and points. The complete candidate
must pass all existing identity, clock, period, overtime, participant and terminal
checks, including reconciliation against **every** supplied quarter and final
total. No event is inserted, removed, reordered or assigned an inferred team or
point value. This is reconciliation against independent fields in the same
provider response, not an independent provider audit.

Accepted candidates carry `trajectory_basis=scoring_actions_v1`, the original
`reported_pbp_errors`, and `reported_home` / `reported_away` on every retained
play. `home` / `away` then represent derived running states. The reconstruction
is revalidated when consumed. Unknown scoring metadata, unresolved action totals,
missing IDs/boundaries and ordering errors keep the original trace partial.
Old evidence is not silently rewritten; an explicit collection appends a newly
interpreted capture at its actual observation time. The workbench labels this
basis and exports both reported and derived states.

CBS may redirect an uppercase GameTracker URL to its lowercase canonical spelling.
The client follows at most one HTTP 301/308 for that exact same game path on the
same HTTPS host, without query/fragment changes. It counts both requests against
the existing budget and reports the first attempt as `redirected`. Other redirects
remain errors; 401/403/429 host stopping, byte/deadline limits and source-policy
checks still apply. This does not make CBS's ID-less HTML a complete PBP source.

Trajectory selection may use the latest ESPN revision when a later partial CBS
fallback agrees on final status, scheduled tip, both final scores, period totals and game type. It never
uses an older clean ESPN revision behind a newer partial one. ESPN's identity,
policy, timestamps, fact validity and ambiguity checks still apply. Player boxes
remain independently incomplete when minutes or participation are missing.

Verified October 18, 2026 against the configured owner's database: explicitly
recollecting October 16 through the canonical manual collector made 15 requests,
appended 14 normalized captures and produced **11 scorable workbench games out
of 12**, previously five. Five trajectories use labeled scoring-action
reconstruction. Atlanta–Dallas retains a usable primary trajectory despite its
missing player minutes. Charlotte–Memphis remains unscored: the action totals and
published quarter/final totals disagree by one point, and the available CBS HTML
cannot establish stable play identities. No score history is fabricated, no
production ratings are archived, and no source is enabled by this operation.

A separate bounded CBS schedule smoke also established that Phoenix's provider
abbreviation is **PHO**, not ESPN's PHX. The mapping now uses the actual CBS
schedule identity; the corrected Utah–Phoenix GameTracker path returned HTTP 200.
The old PHX path redirected to a lowercase path that returned 404, so redirect
handling alone was not sufficient. The structured `plays` field in the two
inspected CBS scoreboards was empty; no hidden complete action feed was claimed.

The live browser showed 11/12 scorable games, labeled reconstructed inputs and
readable quarter/final-total errors for the remaining game. Synthetic tests cover
reconstruction rejection, retained source states through persistence/replay,
latest-primary selection under expiry/revocation/conflicts, request budgets and
redirect restrictions. [Sanitized verification](evidence/game-evidence-recovery-2026-10-18.json)
contains counts/health only, without raw provider bodies or numeric ratings.

### Normalized corroboration metadata (#109)

ESPN plays additionally retain scorer names resolved through provider-local player
IDs and explicit numbered made-free-throw attempts. CBS plays retain exact made
scorer names, explicit scoring values/attempt ordinals and named jump-ball
participants; player rows retain their exact profile-URL slug to disambiguate
abbreviated display names. These are normalized claims, not trusted event
corrections or provider play IDs. Original score states and collection times are
unchanged. The [local workbench recovery](SCORING_WORKBENCH.md#cbs-corroborated-free-throw-previews-109)
uses these fields for a bounded, separately labeled preview interpretation.
Collection reports and production ranking continue to report original coverage.
