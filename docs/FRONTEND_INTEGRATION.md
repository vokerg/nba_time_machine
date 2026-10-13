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
Date input supports the 2025/26 and 2026/27 seasons. Two explicit views exist:

- `pregame` (default): genuine pre-tip observations already known at the cursor.
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
