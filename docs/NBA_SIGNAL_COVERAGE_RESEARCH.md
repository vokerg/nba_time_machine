# $0 NBA signal coverage — issue #82

Decision, 2026-10-14: **NO-GO for backend ingestion from the sampled routes.**
NBA liveData PBP and box score each returned 403 for all five requested games;
Stats V3 timed out for all five. Ordinary Chrome displays useful box-score
statistics and all regulation period markers, which is materially different
from the backend result. No source has passed access, rights, canonical matching,
chronological coverage and reconciliation together. No scoring, calibration,
training, score archive, operational collector, Neon change or UI change occurs.

This follow-up is based on PR #81, whose probe/report are unchanged. The owner
update on #82 supersedes #81's suggestions about paid trials and calibration:
**$0 only; all model choices provisional.** #80 and #10 remain unresolved.

## Reproduce and interpret the evidence

From the repository root, using the installed backend virtual environment:

```bash
backend/.venv/bin/python backend/scripts/probe_nba_pbp.py --game-id 0022500450 --source all
backend/.venv/bin/python backend/scripts/smoke_nba_signals.py --game-id 0042500311 --source all
cd backend
.venv/bin/pytest -q tests/test_nba_signal_smoke.py tests/test_research_trajectory.py tests/test_nba_pbp_probe.py
```

The original probe was manually invoked first. Its 0022500450 results were
403 / TimeoutError / 403 (live / stats / box score). The subsequent timestamped
sample is [health metadata](evidence/issue-82-signal-access.jsonl), collected
**2026-10-14 04:39:22.062628–04:40:03.989942 UTC** on the local backend interpreter.
It contains exactly 15 requests: one per source/game pair, no retries. Those
records have actual UTC run boundaries, endpoint, auth mode, status/error class,
latency, limits and explicit unknown coverage/identity/availability flags.
No HTTP failure body or third-party content was saved. No JSON body succeeded,
so body size, fields and source corrections are **unobserved**, not zero.

The smoke command accepts one game and one source or `all` (maximum three
requests). Sources are fixed, ten-digit IDs only; no redirects, cookies, keys,
bypass or retries. Each response has a 4-MiB byte cap and 8-second socket timeout.
The final smoke adds a **12-second child-process deadline per request** to bound
slow/drip-fed bodies too (at most 36 seconds for `all`, plus process startup).
The recorded sample preceded this additional process deadline; its timeouts
were the original 8-second socket limit. An error in one request never suppresses
the other requested sources. HTTP errors and transport timeouts are different.

A shape response, if a later run obtains one, is explicitly `not_validated`,
with **zero admitted normalized games**. This CLI deliberately cannot certify a
payload, final time or permission. It prints health/counts only. Run manually;
there is no scheduler, background activation, configurable arbitrary URL or DB
connection. Do not repeatedly probe a blocked route or alter request identity to
evade rejection. The five-game sample is finished; further requests need a
concrete new access hypothesis within the issue's bounds.

## Backend endpoint matrix

`S` below means the same five supplied official NBA IDs:
`0022500450`, `0022500560`, `0022501058`, `0042500311`, `0042500301`.
The issue describes routine/OT/2OT/comeback cases; these labels were **not**
validated from backend data. This is three regular-season and two playoff IDs,
not a season-wide coverage study.

| Source / exact endpoint pattern | Sample / time | Actual auth, HTTP, error | Fields actually obtained | Usable / attempted | Decision / blocker |
| --- | --- | --- | --- | --- | --- |
| NBA liveData `https://cdn.nba.com/static/json/liveData/playbyplay/playbyplay_{id}.json` | S; UTC window above | no credentials; 5 × HTTP 403 | none; bodies unread | 0/5 | blocked: HTTP rejection |
| NBA liveData `https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{id}.json` | S; UTC window above | no credentials; 5 × HTTP 403 | none; bodies unread | 0/5 | blocked independently of PBP |
| NBA Stats `https://stats.nba.com/stats/playbyplayv3?GameID={id}&StartPeriod=0&EndPeriod=0` | S; UTC window above | no credentials; 5 × TimeoutError; **no HTTP status** | none | 0/5 | blocked: transport timeout; not proven 403 |
| ESPN ordinary scoreboard `https://www.espn.com/nba/scoreboard/_/date/20260101` | web reader, 2026-10-14 | reader returned a minimal page; backend JSON not attempted | no confirmed route/schema | 0/0 backend | permission unresolved; no UI-derived JSON URL confirmed |
| TheSportsDB free v1, existing integration | no new requests in #82 | see existing provider discovery | existing schedule/result identity capability only | not sampled | fallback; not evidence of PBP, minutes, historical standings or achievements |

ESPN's current [Disney terms §2.B.x](https://disneytermsofuse.com/english/)
restrict automated monitoring/extraction by scripts, including data collections.
No ESPN JSON request or adapter was built after that review. A commonly shared
community URL is not an ordinary-UI discovery, authorization or coverage proof.
HTTP/auth/latency for an unattempted endpoint are unknown. Review approved access
with ESPN before any proposed test. No paid account or trial is a fallback here.

## Four-family coverage matrix

Provenance for backend rows is the first-party URL and actual request metadata,
not cached search snippets or synthetic fixtures. `missing` describes this
sample's evidence, not proof the source has no such data.

| Required family | Source / sampled games / run | Fields actually found | Complete / partial / missing | Chronological availability / retention | Decision and blocker |
| --- | --- | --- | --- | --- | --- |
| Context / magnitude | liveData box score, S, backend window above; separate Chrome box-score checks below | backend: none; browser: matchup, game date, final state, period filters | missing backend; partial browser context | observed today; no historical pre-tip record, strength, standings or series-stakes audit; metadata only | incomplete: game context only; canonical UUID/team joins and period-accurate standings absent |
| Stars / real participation | liveData box score, S, backend window above; Chrome regular-season + playoff | backend: none; browser: both teams, player links, MIN, positional starter labels, explicit DND/DNP and separate inactive section | missing backend; partial browser | postgame visibility today never proves pre-tip active/injury availability; no full content retained | incomplete/browser-only; no verified roster/active/played history or top-rotation/star classification |
| Actual trajectory | liveData PBP + Stats V3, S, backend window above; Chrome 0022500450 ALL | backend: none; browser: Q1–Q4 start/end headings and clock entries | missing backend; partial browser | no backend action identity/revision/timing or actual final timestamp; no raw plays retained | blocked: 403 / timeout; ALL headings alone do not validate a full chronological stream |
| Individual achievements | liveData box score, S, backend window above; Chrome 0022500938 threshold check | backend: none; browser: PTS/MIN, shooting, REB/AST/STL/BLK columns, both-team player links; one 80+ PTS row detected from statistics | missing backend; partial browser | current postgame row only; correction history and independently sourced historical distribution absent; diagnostic counts retained | incomplete/browser-only: outlier identifiable, no verified benchmark for a historical-record claim |

No current standings request can repair historical pre-tip coverage. Roster
membership, active status, actual minutes, explicit nonparticipation and injury
exit are distinct. Empty rows must not be classified as DNP; a short minute
count alone cannot establish an injury exit or a meaningful star absence.

## Separate ordinary-browser observations

These are bounded **visible UI** inspections in ordinary Chrome, not backend
HTTP responses. No network interception, cookie export, security bypass,
login prompt, raw play export, screenshot archive or browser-backed collector
was used. Existing browser session authentication is not independently audited;
no new credentials were supplied. Browser HTTP status/latency were not measured.
Diagnostic counts are also in [browser observations](evidence/issue-82-browser-observations.json).

- [0022500450 box score](https://www.nba.com/game/den-vs-mia-0022500450/box-score):
  both team tables, player links, MIN, shooting and counting-stat headers,
  starter-position annotations, DND text and inactive lists were visible.
  This is evidence that participation and achievements surfaces exist even when
  backend PBP and box-score requests fail independently.
- [0022500450 PBP](https://www.nba.com/game/den-vs-mia-0022500450/play-by-play),
  **04:41:09 UTC**: clicking ALL exposed each Q1–Q4 start/end heading;
  105 clock text entries were counted. This is **not** a validated action count,
  evidence of every action, corrected score reconciliation or a trusted end time.
- [0042500311 playoff box score](https://www.nba.com/game/sas-vs-okc-0042500311/box-score),
  **04:41:43 UTC**: two tables, 23 player links, 21 minute-formatted cells,
  DNP/DND and inactive sections, and final-state text were present. Do not
  interpret the two missing minute cells as inferred DNP; only explicit source
  statuses can classify nonparticipants. No playoff series-stakes audit occurred.
- [0022500938 extraordinary-points box score](https://www.nba.com/game/was-vs-mia-0022500938/box-score),
  **04:42:22 UTC onward**: generic table-header lookup found PTS and MIN;
  numeric player rows were tested against `PTS >= 70` and `PTS >= 80`.
  The two teams had 12 and 15 linked player rows, with 10 and 11 rows containing
  minutes + numeric points. Threshold counts were **0/1 for both 70+ and 80+**.
  No named player or game-specific exception was needed for this computation.
  Thus an 80+ achievement can be identified from actual statistics, independently
  of recap wording. It is not proof of player/team sum reconciliation or any
  historical record; no record distribution was collected.

For the browser threshold check, select the all-period traditional table, locate
PTS and MIN by header text, consider only rows linked to `/player/`, require an
explicit `minutes:seconds` field plus numeric points, then count threshold
matches per team. Nonparticipants remain outside that numeric subset. This
procedure is repeatable manually in the linked official UI; no reusable browser
scraper/provider parser is approved. Do not persist complete tables as fixtures.

The official [regular-season summary](https://www.nba.com/game/0022500450) and
[playoff summary](https://www.nba.com/game/0042500311) were also checked with the
web reader: they exposed page identity/date/navigation, not independent period
and final totals usable for reconciliation. No computed trajectory was available
to cross-check. **Independent complete-game reconciliation remains blocked.**

## Coverage denominators and temporal conclusions

| Check | Backend result | Separate browser result |
| --- | --- | --- |
| Usable trajectory games / attempts | liveData 0/5; Stats 0/5 | 0 validated / 1 ALL view inspected |
| Full Q1–Q4(+OT) action coverage | 0/10 PBP attempts demonstrated; payloads unavailable | 1/1 ALL view had regulation boundary headings; chronological completeness unknown |
| Both-team players + minutes | 0/5 box-score attempts | visible in 3/3 box-score pages; all roster/active-status completeness unknown |
| Player threshold from real numeric PTS | 0/5 box-score attempts | 1/1 additional outlier game; one 80+ row found |
| Canonical game/team/player UUID matches | 0 established; payloads unavailable | 0 established; source links are not canonical UUIDs |
| Defensible pre-tip observation proof | 0 established | 0 established |
| Trusted actual final timestamp | 0 established | 0 established; final text is state only |
| Source corrections/action revision history | 0 assessed | not extracted |
| Error classes | ten HTTP 403; five transport TimeoutError | no browser block observed on inspected pages |

Unavailable checks are **unknown**, not negative observations of real source
coverage. Percentages from inaccessible payloads cannot characterize completeness
of the underlying feed. These denominators measure only the small attempted
sample; the additional outlier UI game is outside S and not a sixth backend game.

`started_at` / `completed_at` are our request times. Neither is publication,
actual tip nor `final_at`. A current final state or terminal game clock does not
establish a physical final instant. A later permitted backfill would be observed
then; it cannot fabricate a 2025/26 pre-tip slate or availability boundary.

## Rights and operational contract

[NBA terms §9](https://www.nba.com/termsofuse) limit statistical reuse; private use
does not authorize archived PBP or comprehensive regularly updated databases.
Production rights remain unresolved. This is bounded transient research;
no full-content or source-text retention has been approved. Only access metadata,
field presence and small diagnostic counts are retained here. Do not infer
approved full, normalized-full, redistribution or production capture policy.

| Contract | Research result / future gate |
| --- | --- |
| Access/auth | fixed first-party liveData and Stats URLs, no key; website-internal, no supported developer contract proved |
| Cadence | explicit operator invocation only; future cadence requires source review; no polling deployment |
| Rate limits/stability | no published usable contract established; sample has 403/timeouts; no retry or bypass; future 429 must respect Retry-After |
| Dedup | future provider game + event identity + explicit revision timestamp; collisions/ambiguous revisions fail closed; no provider adapter today |
| Timestamps | source event/edit clocks are claims; preserve actual observation; unavailable fields stay unknown; never infer final_at |
| Retention/full content | diagnostic metadata only here; full-content permission unresolved; synthetic offline fixtures only |
| Failure isolation | separate endpoint outcomes; PBP failure cannot suppress box score; report transport versus HTTP separately |
| Historical coverage | five backend game IDs, three visible box scores, one ALL view; no season claim |

## Offline prototype and remaining parser gate

`nba_time_machine.research.trajectory` is a small provider-neutral typed boundary
with **only generated synthetic input**. It validates strict identities, aware
observation/revision timestamps, numeric types, countdown range/order, regulation
and OT boundaries, terminal state, score continuity, explicit revision selection,
and externally supplied reference totals. Exact duplicate versions collapse;
ambiguous/conflicting revisions or reversed sequences fail closed. Only a passing
structural trace emits raw lead-change, winner-deficit and OT counts. These are
not watchability values. No physical final timestamp or canonical UUID is inferred.

Boundary markers and reference totals cannot prove all intervening events exist;
source action continuity, authoritative terminal-period count, correction audit
and independent source reconciliation are still required. Contract success
therefore never sets `independently_verified_complete`. The contract is not
imported by the app, collectors, sports repository, ranking or AI code.

There is **no usable, rights-cleared backend endpoint** from which to implement
an honest real provider parser. In accordance with #82's conditional parser gate,
no liveData/Stats/ESPN adapter was invented from documentation or synthetic payloads.
All important parser-like ordering/correction/coverage behavior is exercised at
the neutral synthetic boundary. Context/participation/achievement provider
normalizers await verified allowed payloads; browser visibility is recorded
without turning Chrome into an operational collector.

## Next implementation task prepared for separate authorization

**Title:** Admit a rights-reviewed $0 NBA evidence source into canonical ingestion.

Prerequisite: document the source's permitted machine access, normalized-fact and
raw retention policies, attribution, corrections and request limits. Start with
one regular-season and one playoff box score independently of PBP. If no source
permits this at $0, retain NO-GO and use existing schedule/results only; do not
substitute paid trials or circumvent current failures.

Allowed implementation paths after approval: existing `sports/`, ingestion
contracts/source policy, temporal repositories and synthetic tests. Resolve NBA
provider game/team/player identities against existing canonical UUIDs through
`SportsExternalIdentityRecord`, using verified team mappings plus season/tip and
home/away checks; quarantine ambiguous/rescheduled matches. No parallel schema.
Write idempotent observation/correction history using existing sports records and
`TemporalFactRecord` only when evidence and retention gates pass. Record per-source
run health and coverage independently. Replay must preserve today's observation
rather than claiming historical pre-tip knowledge. A real final timestamp, or a
separately reviewed final-confirmation contract, is a separate gate.

Acceptance for that task: approved source policy; bounded live box-score proof;
two-team participation and player-total reconciliation; explicit missing fields;
canonical identity collision tests; idempotent retries and append-only correction
history; disposable PostgreSQL tests; per-family health; independently reconciled
complete PBP before trajectory admission. Keep scoring/model calibration, numeric
archive materialization and policy-gated product exposure separately authorized.

Current research deliverable is a concrete **NO-GO plus partial browser evidence**,
not an ingestion-ready provider recommendation. Review #82 before closing it.

## Validation

- 38 targeted offline tests passed locally (12 existing probe checks plus 26
  research/smoke cases); all fixtures/results in those tests are synthetic.
- Broader local `pytest -q -m 'not integration'`: **280 passed, 1 failed,
  42 deselected**. The existing
  `test_dev_launcher.py::test_cleanup_stops_descendants_after_parent_exits`
  fails with macOS `PermissionError` in unchanged `dev.py` process-group cleanup.
  This issue does not alter the launcher; the failure is recorded, not hidden.
- No local DB tests were run; DATABASE_URL and DIRECT_DATABASE_URL were removed
  from the test environment. Disposable PostgreSQL/migrations and frontend checks
  run in GitHub CI. See PR #83 for the final-commit CI outcome.
