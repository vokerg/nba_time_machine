# Connected dashboard (#74)

Run both applications with `./dev.py`. Vite proxies `/api/*` to the backend at
`127.0.0.1:8000`, stripping `/api`. A production host must supply equivalent
same-origin routing. Provider/database credentials stay on the backend; no
frontend secrets, direct provider calls or fixture fallback exist.

The browser stores only an opaque profile UUID. This is a state key, not
authentication. First use requests `GET /timeline/{profile_id}` and asks for an
explicit starting cursor if absent. Initialization is a POST; reload resumes the
backend cursor. Advancement is a PUT and backend-enforced forward only. Advancing
to now asks for confirmation because it accepts the intervening NBA world.
Switching a slate date does not move the cursor or make earlier knowledge exist.

Game requests use `/profiles/{profile_id}/games?date=YYYY-MM-DD&view=...`.
The selected date uses Eastern NBA calendar days; tip times display in Eastern.
Date input supports the 2025/26 and 2026/27 seasons. Three explicit views exist (season replay is the UI default):

- `replay`: retrospective imported matchups on original game dates; see below.
- `pregame` (strict API default): genuine pre-tip observations already known at the cursor.
- `observed`: latest schedule observation already known at the cursor, including
  backfill. Basic matchup and scheduled-tip fields are timestamp-gated rather than
  required to precede tip. Pregame interest, standings and availability still need
  pre-tip provenance. Membership is never filtered or ordered by result/status.

The observed view does not recreate the old pregame world or invent publication
times. A 2025 game collected in October 2026 remains invisible to a cursor in 2025.
To browse available backfill, intentionally advance the cursor past its observation
time and select the game's date and observed view. Empty slates can indicate
missing provider coverage. Imported preseason events may also appear. Complete
season availability depends on the ingestion issue and provider coverage.

Game cards contain allowlisted fields only. Watchability and why are GETs made
only by explicit hint buttons; full disclosure POSTs `/{game_id}/reveal` only
after confirmation. Acknowledgement persists server-side, without moving the
cursor. Even acknowledged cards don't passively request results. Date, view,
cursor and reload changes clear disclosures; aborted/old slate responses cannot
replace current state. A server cursor mismatch prompts reload rather than mixing
different NBA worlds. Errors never display arbitrary backend response bodies.

Loading, no coverage, initialization, failed requests and unavailable disclosures
have explicit states. Favorites remain separate and don't reorder games. The
media area reports that no endpoint is connected; it no longer renders synthetic
headlines. Pregame recommendations appear only when an actual pregame score exists.

Verification: `cd frontend && npm test && npm run build`; backend policy/route
and PostgreSQL integration tests cover observation-time membership and excluded
result fields. Persistence tests run only against disposable local/CI PostgreSQL.

## Season replay (#77)

The UI now defaults to `view=replay`. Imported matchups and scheduled tip times
appear on their original Eastern dates, through the cursor's Eastern calendar day,
even when collected later. Advancing the cursor selects its new Eastern day.
This is retrospective schedule browsing: it can reflect later schedule corrections
and postseason participants, and does not claim archived pregame knowledge.

The exception admits only home/away identity and scheduled tip, with valid stored
provenance. Selection uses the latest timestamped observation, then filters its
date; status, scores and result availability never control membership or order.
Stored collection/availability timestamps are unchanged. All other pregame fields
retain strict gating; general media gets no exception. Existing pregame and
observed views remain available and unchanged. Results remain hidden on cards
and are disclosed only through existing deliberate reveal actions. Replay does
not infer a historical game-ending time or silently unseal games at tipoff.

Current coverage is partial: 612 imported 2025/26 games and 53 2026/27 games.
There are no ingested standings, injuries, player statistics, ranking scores or
media feeds. Replay supports date browsing, cursor progression and individual
result reveals; it does not make the full product or full-season coverage complete.

The viewing guide can explicitly request postgame ordering in
Historically observed pregame view. Each action requires fresh acceptance of
outcome-based hints; replay and observed/backfill views do not submit ranking
requests. Picks contain only the existing safe matchup fields and reset on
cursor/date/view changes. Favorites affect neither requests nor ordering.
Missing score coverage is displayed as unavailable rather than guessed quality.
See [Ranking](RANKING.md#connected-viewing-guide-and-archived-verdicts-10) for
provisional verdict bands and the remaining feature-production blocker.

## Personal Watch Queue (#90)

The side-panel queue and buttons on game cards call the profile-scoped persisted
Watch Queue endpoint (see [Watch Queue](WATCH_QUEUE.md)). Saving, marking
`done`, dismissing or removing is personal bookkeeping: none of these actions
changes the sealed/acknowledged status or requests spoiler-bearing evidence.
Queue entries render the existing strict pregame policy card or an honest
unavailable placeholder. Only an explicit, separately confirmed result reveal
can acknowledge a game. Queue reads require the currently saved global cursor;
stale concurrent-tab responses fail closed.
