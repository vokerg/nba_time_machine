# Fresh NBA data validation — 2026-10-14

**ESPN's unauthenticated summary JSON works from the local backend runtime for fresh 2026 preseason games. A two-hour publication target remains unverified. No source passed both technical validation and permission for recurring production access.**

The mandatory Warriors–Lakers game was retrieved and checked using real responses. This materially extends the earlier [PBP research](NBA_PLAY_BY_PLAY_ACCESS_RESEARCH.md) and [signal-access research](NBA_SIGNAL_COVERAGE_RESEARCH.md), which had not tested ESPN JSON. Those reports remain records of their earlier observations.

Requests ran **18:25–18:33 UTC on October 14**, using `backend/.venv/bin/python` (Python 3.14.8), the backend's installed `httpx 0.28.1`, and the current macOS workspace network. No app collector, database, source registry, ranking or production ingestion was invoked. No separate hosted backend was available/tested; these results establish access from this actual **local backend environment**, not every deployment network. No private credentials, cookies, browser impersonation, redirects, retries or bypass were used. TheSportsDB's documented public development key `123` was the only key supplied.

[Machine-readable evidence](evidence/fresh-nba-source-validation-2026-10-14.json) records all 39 request URLs, UTC start times, status codes, content types, byte counts, durations, response digests and validation diagnostics. Full responses were used transiently for analysis and removed; no full-content fixtures were committed. The evidence retains small actual response field excerpts, not mocked games.

## Comparison

| Source | Fresh PBP | Box scores | Preseason | Backend access | Publication lag | Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| NBA liveData CDN | Not observable | Not observable | Exact 2026 game attempted | PBP, box, today's scoreboard and schedule all **403**, HTML | Unknown | Blocked here; latest complete game unknown |
| ESPN summary JSON | **504 plays** for mandatory game; all five October 13 games checked | Both teams, player IDs, points and rounded MIN | **Validated**, including another game with OT | **200 JSON**, no authentication | **Unknown**; first check approximately 14 hours after source end-game timestamp | Strongest technical primary candidate; automation terms unresolved |
| CBS GameTracker | 473 HTML play rows across Q1–Q4; one clock reversal | Both teams, player links and rounded MIN | Mandatory game and POR–SAC available | **200 HTML**; website-internal JSON transport also located, but no usable standalone game payload validated | Unknown | Accessible comparison source; complete chronological feed/identity contract not validated |
| TheSportsDB free v1 | `timeline: null` | Lineup, event results and event statistics all null | Exact game and final score found | **200 JSON**, public development key | Unknown | Schedule/result source; fails required PBP/player coverage |
| SportsDataverse release | No 2027-season asset in inspected NBA PBP release | Fresh player boxes not tested | Not demonstrated | **200 GitHub release metadata** | Unknown | Historical test-data candidate only; no production fallback claim |
| BALLDONTLIE | PBP excluded from free tier | Game player stats/boxes excluded from free tier | Not tested | Documentation reviewed; no data requests or trials | Unknown | Fails $0 constraint |

No independently validated fallback is recommended. ESPN is a **technical candidate**, not an approved production provider or a demonstrated two-hour service.

## Mandatory game: actual ESPN response

| Test | Observed result |
| --- | --- |
| URL | [Summary, event 401898718](https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event=401898718) |
| HTTP / format | **200**, `application/json;charset=UTF-8`, 455,931 decoded bytes, 0.460 seconds |
| Identity / season | Event `401898718`; team IDs GS `9`, LAL `13`; season year `2027`, type `1` (preseason) |
| Status | `STATUS_FINAL`, `state: post`, `completed: true`; full PBP and full box-score flags |
| Scheduled tip | `2026-10-14T02:00Z` — October 13 in the game's US date, not a date mismatch |
| Plays | **504 unique play IDs**; Q1/Q2/Q3/Q4 counts **113 / 137 / 127 / 127** |
| Chronology | Periods ascend; clocks never increase within a period; every period ends at zero; explicit End Game record |
| Final reconciliation | PBP terminal, header, separate scoreboard, player-point sums and CBS all agree: **GS 101–89 LAL** |
| Quarter reconciliation | GS **29 / 21 / 22 / 29**; LAL **29 / 34 / 13 / 13**, reproduced from cumulative PBP |
| Scoring transitions | 101 score changes; each adds 1–3 points to one team and agrees with its scoring event; no negative or unexplained transition |
| Player boxes | 17 roster rows per team; **14 GS / 16 LAL played**, 3 / 1 explicit DNP; every played row has MIN and statistics |
| Player identity | Every PBP participant ID resolves to a player row in this response; provider player IDs, UIDs and player links are present |
| Minutes precision | Integer display minutes, not seconds; displayed sums **242 / 240**, not proof of exact 240-minute team totals |
| Source timestamps | All 504 plays have wall clocks; Q4 end `04:23:56Z`, End Game and `meta.lastUpdatedAt` **`04:25:54Z`** |

Game-clock order is usable **as returned**. Do not sort by `sequenceNumber`: it reverses twice, including inserted records numbered 746/747 in Q2. Wall clocks reverse six times at equal game clocks. These observations are compatible with corrections/inserts, but the response does not provide a verified correction history.

A deeper shot-count check reconciled every played player's points, FGM/FGA, 3PM/3PA and FTM against the box. Naively counting FTA found **one exception**: Chris Manon's Q2 11:03 sequence has both made and missed FT records plus a lane violation, while his box says 1–1. The source does not explicitly label the extra attempt as void. Therefore no claim is made that raw event counts can reproduce every official statistic without correction rules. Similarly, `active: false` and a `reason` string can occur on a player who played; use explicit participation/stat fields, not those fields alone.

Provider IDs are observable identities within ESPN's namespace. No NBA-ID crosswalk, canonical database join or lifetime stability guarantee was established. Complete period coverage and score reconciliation do not independently audit every non-scoring action against an official scorer's log.

The successful discovery endpoint was [October 13 scoreboard](https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=20261013), **200 JSON**. It includes this game and four others. The separately tested [Core plays URL](https://sports.core.api.espn.com/v2/sports/basketball/nba/leagues/nba/events/401898718/competitions/401898718/plays?limit=1000) returned **404**; it is not the working PBP route. The **summary's `plays` array** supplies the complete-period sequence in this test.

## Coverage and latest-game evidence

All rows below were actual **200 JSON** summary responses. Every row passed game-clock ordering, all-period end markers, terminal-score/header reconciliation, period-total reconciliation and both teams' player-point-total checks. These are bounded samples, not season-wide guarantees.

| Game | ESPN ID / summary query `?event=` | Plays | Periods | Source End Game wall clock (UTC) |
| --- | --- | --- | --- | --- |
| CLE–ORL, October 13 preseason | `401898403` | 492 | 1–4 | October 14 01:26:06 |
| NYK–TOR, October 13 preseason | `401908944` | 521 | 1–4 | October 14 01:32:58 |
| IND–OKC, October 13 preseason | `401908621` | 537 | 1–5, OT | October 14 02:40:45 |
| GS–LAL, mandatory preseason game | `401898718` | 504 | 1–4 | October 14 04:25:54 |
| POR–SAC, October 13 preseason | `401901826` | 536 | 1–4 | **October 14 04:27:40** |
| PHI–TOR, January 12 regular season | `401810415` | 469 | 1–4 | Historical test only |
| SAS–OKC, May 18 playoffs | `401873197` | 579 | 1–6, 2OT | Historical test only |

POR–SAC is the latest completed game **by ESPN's reported end-game wall clock among all five October 13 slate games**. The [October 14 scoreboard](https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=20261014) was also checked: its seven games were all pregame, beginning at 23:30 UTC. POR–SAC was first fetched here at 18:26:59 UTC. This bounds the current-slate investigation; it is not a global historical search.

The additional POR–SAC trace has **two scoring-transition anomalies**, despite reconciling at every period end and at final: SAC's cumulative score decreases by one on a Q4 9:11 foul record, then increases by one on an 8:53 record marked non-scoring. Their correction semantics were not resolved. Consequently, the mandatory game passes the stricter transition check, but not every fresh game does. A usable provider boundary must preserve and flag such exceptions; silently treating every raw score change as an ordinary scoring event would be incorrect.

**Publication delay is unknown for every source.** ESPN's event wall clocks and `lastUpdatedAt` are publisher claims about event/update times. They do not establish first public availability or an independently verified physical final instant. HTTP `Date`, a short `Cache-Control: max-age`, retrieval duration, and an event-shaped identifier are not publication timestamps. No observation was made at final or at final + two hours. For the mandatory game, the first successful summary retrieval here was approximately **13h 59m 37s after the End Game wall clock**; that is observation age, **not measured publication lag**. An earlier first-publication timestamp was not verified.

## Other sources: exact routes and blockers

**NBA:** [PBP 0012600048](https://cdn.nba.com/static/json/liveData/playbyplay/playbyplay_0012600048.json), [box score](https://cdn.nba.com/static/json/liveData/boxscore/boxscore_0012600048.json), [today's scoreboard](https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json) and [schedule](https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json) each returned **403 `text/html`**. No game payload was obtained, so preseason completeness, latest available PBP, players and timestamps remain unobservable here. This is an HTTP rejection, not a DNS error or evidence that NBA lacks the game. No blocked route was retried or disguised.

**CBS:** [Live GameTracker](https://www.cbssports.com/nba/gametracker/live/NBA_20261013_GS%40LAL/) and [play-by-play page](https://www.cbssports.com/nba/gametracker/playbyplay/NBA_20261013_GS%40LAL/) each returned **200 `text/html`**, approximately 1.852 MB. No JavaScript execution or browser session was needed. PBP is rendered into four HTML tables (**110 / 128 / 119 / 116 rows**), not a populated embedded PBP JSON array. Period ends and final/quarter scores reconcile with ESPN. There is one Q1 clock reversal, 2:42 → 2:43. Of 110 score-bearing rows, 101 change the cumulative score; nine retain the prior score, so counting visible score annotations overcounts scoring events. No stable IDs were found on individual play rows. Row-count differences from ESPN alone do not prove which non-scoring events are missing.

CBS's embedded `current_game_scoreboard` JSON contains game ID **50037013**, FINAL status, scheduled tip, team IDs **341 / 345** and line scores; its `plays` array is empty. Player boxes are HTML: **17 GS / 18 LAL distinct linked player IDs**, 14 / 16 played, and point sums 101 / 89. MIN is integer display precision; each team's displayed minutes sum to **232**. Responsive starter tables are duplicated and must not be counted twice. A last-play ID resembles epoch milliseconds, but its timestamp semantics are undocumented and were not inferred.

The ordinary page loads [this public JavaScript bundle](https://sportsfly.cbsistatic.com/fly-845/bundles/sportsmediajs/js-build/managers/live-app-gametracker-basketball.js), which returned **200 `application/javascript`**. It references Torq/SockJS live transport and an internal JSON state-file service. A no-credential request to [the state-file route](https://sdf-api.cbssports.cloud/napi/util/getTorqStateFile) returned **200 `application/json`**, but only `{"topics":[]}`. Client-bundled access tokens were not used. This identifies website infrastructure, **not a validated, authorized third-party NBA JSON API**.

The latest sampled [CBS POR–SAC page](https://www.cbssports.com/nba/gametracker/playbyplay/NBA_20261013_POR%40SAC/) also returned **200 HTML**, with 520 rows across all four periods, no clock reversals and final 110–98. Completeness and publication time remain unverified; its ordering relative to GS–LAL comes from ESPN's timestamps, not a CBS final timestamp.

**TheSportsDB:** [Exact matchup search on its UTC date](https://www.thesportsdb.com/api/v1/json/123/searchevents.php?e=Los_Angeles_Lakers_vs_Golden_State_Warriors&d=2026-10-14) returned **200 JSON**, event **2601647**, `FT`, scheduled 02:00 UTC, 89–101. The same search on October 13 returned `event: null`. For that real event, [timeline](https://www.thesportsdb.com/api/v1/json/123/lookuptimeline.php?id=2601647), [lineup](https://www.thesportsdb.com/api/v1/json/123/lookuplineup.php?id=2601647), [event results](https://www.thesportsdb.com/api/v1/json/123/eventresults.php?id=2601647) and [event statistics](https://www.thesportsdb.com/api/v1/json/123/lookupeventstats.php?id=2601647) were all **200 JSON with null payloads**. Latest complete PBP: unknown; none validated. An exploratory misspelled `lookupresults.php` route returned 404 and was corrected to the documented `eventresults.php`; it is not evidence against that documented route. The free daily schedule returned three rows, consistent with its documented cap, and was not treated as a full slate.

**SportsDataverse:** [NBA PBP release metadata](https://api.github.com/repos/sportsdataverse/sportsdataverse-data/releases/tags/espn_nba_pbp) returned **200 JSON**. It listed 2026 CSV/Parquet/RDS assets updated **September 9**, and **no 2027 asset**. NBA season year 2027 is the current 2026/27 season in the tested ESPN responses. No season file was downloaded, so the latest complete game within those older assets was not established. The maintainers' [ESPN extraction code](https://github.com/sportsdataverse/hoopR/blob/main/R/espn_nba_data.R) uses the same summary interface: a package wrapper is not an independent provider or permission grant.

## Terms and operational limits

These are observed source restrictions, not a determination of legal rights for the product.

- **NBA:** [Terms §9](https://www.nba.com/termsofuse) restrict play-by-play products and comprehensive updated statistical databases without consent; attribution is required. No usable developer rate-limit/SLA contract was established. NBA/CDN robots requests were also 403.
- **ESPN:** [Disney terms §2.B.x](https://disneytermsofuse.com/english/) restrict automated access/extraction and dataset/database compilation. Public JSON access does not clear recurring ingestion or retention. No published request quota or compatibility guarantee was established for these routes; observed cache TTLs are not quotas. API-host `robots.txt` returned 403. The separate [website robots file](https://www.espn.com/robots.txt) returned 200 and includes crawler-specific exclusions and PBP/box-score path restrictions; it does not grant API rights.
- **CBS:** The page's terms link redirects to [Paramount/CBS Interactive terms](https://www.viacomcbs.legal/us/en/cbsi/terms-of-use), effective May 27, 2025. They restrict unauthorized scraping/data harvesting/automated gathering. No third-party API license, published NBA quota or stability contract was established. Its [robots file](https://www.cbssports.com/robots.txt), 200, includes general path restrictions and a GPTBot exclusion; neither HTML visibility nor robots treatment supplies authorization.
- **TheSportsDB:** [Documentation](https://api.thesportsdb.com/documentation) permits public development key `123`, with **30 requests/minute** and endpoint-specific result caps; [terms](https://www.thesportsdb.com/docs_terms_of_use.php) permit official-API reuse subject to rights, and require a paid subscription for app-store publication. Current null coverage already fails this task.
- **BALLDONTLIE:** Its [official tier matrix](https://nba.balldontlie.io/) places Plays and Box Scores on paid GOAT, with player game statistics also outside Free. No account, trial or paid API was used.

No numerical rate limit was invented from successful requests. There were no 429s in this bounded sample; that does not establish an allowed polling rate. No production retention policy was approved or changed.

## Decision and exact next step

**Can the backend retrieve yesterday's complete-period PBP and player statistics now? Yes, technically, through ESPN's summary endpoint.** This is demonstrated for the mandatory game and the latest completed slate, including an overtime game. Exact seconds played and fully corrected event-derived box statistics are not demonstrated.

**Can we demonstrate that a game ending two hours ago is already available automatically? Not from this observation window.** The missing proof is a timestamped observation within that window, plus permission for recurring machine access. ESPN is the most promising source to resolve those gaps. After permitted access is established, observe a newly finishing game's complete PBP/box response at final and within two hours, keeping first successful observation separate from source event/update timestamps. No such poller was deployed here.

CBS remains a possible source for further investigation, but its HTML ordering, per-play identity, completeness and access permission need resolution before calling it a fallback. No validated $0 production fallback was found. No implementation, backfill, database changes or PR were made.
