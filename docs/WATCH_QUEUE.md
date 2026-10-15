# Personal Watch Queue (#90)

The Watch Queue is **personal intent, not a spoiler permission**. Each row is a
`(profile_id, game_id)` membership with a user-selected `queued`, `done`, or
`dismissed` state. No state transition acknowledges a game, advances the
timeline, fetches a watchability score or implies that a game was watched.
The canonical spoiler states remain **sealed / acknowledged** and use separate
explicit result-reveal actions. Existing profile UUIDs are state keys, not login
credentials or cross-device authentication.

## API

- `GET /profiles/{profile_id}/watch-queue?time_cursor=<ISO>&view=replay`
  returns insertion-ordered user entries and the saved cursor. Each item has
  `game_id`, `queue_state`, and either a policy-derived *pregame-only*
  `game` card or `game: null` when not safely available.
- `PUT /profiles/{profile_id}/watch-queue/{game_id}` with
  `{"time_cursor":"<ISO>","queue_state":"queued|done|dismissed"}`
  idempotently creates/updates the personal state (HTTP 204).
- `DELETE /profiles/{profile_id}/watch-queue/{game_id}?time_cursor=<ISO>`
  idempotently removes an entry (HTTP 204).

All operations require an initialized profile and the exact current cursor;
stale clients get HTTP 409 and must reload. Writes lock the timeline state row
so cursor advancement cannot interleave. PUT accepts only canonical NBA game
IDs and preserves original insertion order on re-state. Sorting and membership
never depend on results, rating, tip outcome, game length or update cadence.
Deleting and re-adding intentionally creates a new position.

The default queue view uses the explicitly labeled retrospective **season
replay** identity/scheduled-tip exception for games through the cursor's NBA
Eastern day. It does not claim verified pregame observation. `view=pregame`
and `view=observed` retain strict historical observation gates. All views
pass snapshots through the existing `DisclosureLayer.PREGAME` policy and safe
`GameCardResponse` serializer, so no score, winner, rating, postgame status,
thumbnail, runtime or provider payload enters the queue. Future-day and missing
games remain neutral placeholders; their identity is not inferred from later
game results. Deliberately revealing a game separately does **not** add/finish
a queue entry or unlock later general media.

## Verification

Backend: `cd backend && alembic upgrade head && pytest -q` using an isolated
test PostgreSQL. Frontend: `cd frontend && npm test && npm run build`.
Neon migration should only be applied by the normal deployment/migration
workflow; this PR does not run live data operations.
