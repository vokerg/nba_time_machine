# Architecture: temporal and spoiler model

## The fundamental query

Every read path should be able to answer:

> What was safe to expose at timeline position T, given the game's acknowledgement state and the requested disclosure layer?

This is more precise than filtering rows by publication date.

## Timeline semantics

The selected `time_cursor` is persistent user state. The app resumes from the last selected position rather than assuming real-world now.

For MVP, timeline movement is **forward-only** after the cursor has been established.

Moving the cursor forward is an intentional acknowledgement of the NBA world up to the new point. Games that the user has deliberately moved past are no longer treated as sealed. Backward travel and arbitrary historical replay are deferred to a future full-time-machine mode.

This design deliberately separates:

- **global timeline state** — controls what general world/media information may appear;
- **per-game acknowledgement** — allows one sealed game to be opened without advancing the global media world.

### Persistent timeline service contract

MVP timeline persistence uses an opaque UUID `profile_id`. It is only a durable state key; it does not create or imply an authentication/account model.

The timeline service:

- initializes a profile cursor exactly once;
- stores timezone-aware timestamps canonically in UTC;
- resumes the last persisted cursor after process restart;
- permits equal or later cursor updates;
- rejects any attempt to move the cursor backward;
- performs the monotonic comparison in the database update so concurrent requests cannot regress the cursor;
- has no hidden game-reveal or media side effects.

The timeline layer deliberately does not infer when a specific game stops needing spoiler protection. A caller supplies a defensible `protection_ends_at` boundary, derived later by the spoiler-policy/game-state layer from temporally valid game information. A game is considered past that boundary when `time_cursor >= protection_ends_at`; equality counts because information available exactly at the cursor belongs to the reconstructed world.

## Core timestamps

A content item should preserve:

- `published_at`: claimed source publication time;
- `published_at_precision`: exact / date-only / unknown;
- `discovered_at`: first observation by us;
- `captured_at`: timestamp of this stored capture;
- `available_at`: conservative earliest public availability used by the time machine.

For mutable structured facts use temporal validity:

- `valid_from`;
- `valid_to` (nullable);
- `observed_at`;
- provenance/source reference.

## Conservative availability

When publication time is absent or ambiguous, do not backdate aggressively.

For strict timeline reads, a safe default is:

```text
available_at = max(defensible publication time, first reliable observation time)
```

The exact reconciliation algorithm belongs in a dedicated implementation issue and must be testable.

## Game state: sealed vs acknowledged

"Watched" is not a reliable state because the user may reveal a result without watching the game.

A game is:

- **sealed**: result-dependent information remains protected;
- **acknowledged**: the user has explicitly revealed it, or has advanced the timeline beyond the period in which it was being protected.

Explicit acknowledgement can reveal the game's downstream branch without moving the global cursor.

Game-linked information can be classified as:

- pregame;
- in-game;
- postgame;
- retrospective.

## Layered disclosure

A sealed game should support progressively more revealing projections:

1. **pregame** — only facts knowable before tip-off;
2. **watchability verdict** — a coarse postgame signal, without a numeric score by default;
3. **watchability reason** — more specific explanation only when explicitly requested;
4. **full reveal** — score, result, box score, recap/highlights and postgame information.

The internal postgame-quality score may be continuous and rich even when the public projection is coarse.

The exact labels for the coarse watchability verdict are intentionally not fixed yet.

## Media-feed rule

General news, social/X and podcast feeds are strictly governed by the global `time_cursor`.

Acknowledging an individual game does not cause later articles, posts or podcast episodes to appear in those general feeds. This avoids mixed articles/posts leaking information about other still-future games.

A game-specific view may expose downstream information tied to an acknowledged game, but the general media universe remains time-consistent.

## User state

Expected fields include:

- selected `time_cursor`;
- timeline initialization / last-position metadata;
- per-game acknowledgement state where explicit reveal happened before timeline advancement;
- requested disclosure level for a game interaction;
- postgame/watchability visibility preferences;
- favorite team IDs (zero or more), separate from canonical ranking.

## Safe projection

The policy engine should return a projection, not merely an allow/deny bit, because the same game has multiple disclosure layers.

For general media items, initially prefer timeline-based whole-item hiding over AI redaction when an item crosses the cursor or mixes safe and unsafe consequences. Deterministic field-level transforms may be introduced later where they are provably safe.

## Ranking boundary

Favorite teams never alter canonical watchability ranking.

Pregame ranking uses only pre-tip information. Postgame quality can use outcome-aware events, but its score and reasons are themselves spoiler-bearing and must respect the requested disclosure layer.

## AI rule

No model is asked to "remove spoilers" from forbidden content.

Forbidden content never enters the prompt.

This invariant should have regression tests using deliberately spoiler-heavy fixtures.


## Pure spoiler-policy kernel (issue #7)

The backend `nba_time_machine.spoilers` package is the deterministic, in-memory
filter. The API/read models and persistence services integrate this boundary in
separate issues (#15 and #14). Neither the collector nor the AI client authorizes
information disclosure.

**Caller contract**

- Construct `GameContext` using the persisted global `time_cursor`, trusted
  `acknowledged` state, a timezone-aware `tip_at`, and a conservatively derived
  `protection_ends_at`. The boundary is a caller-supplied observation-based
  timestamp, not guessed from a scheduled end or current score.
- Supply individual `GameField` values with trusted, explicit field kinds,
  `available_at` and `observed_at` provenance. A pregame field requires
  both timestamps no later than the cursor and `available_at < tip_at`.
  This initial contract conservatively hides historically backfilled facts that
  were first observed after the cursor, even if they appear to have been
  published earlier.
- Call `project_game` with the exact requested `DisclosureLayer`. A sealed
  game's full projection additionally needs `explicit_full_reveal=True`;
  only #14 may convert that explicit action into a durable acknowledgement.
  Opt-in watchability and why require separate disclosure requests. A numeric
  postgame-quality score is intentionally not a projected field.
- Construct `MediaItem` with complete game linkage and a trusted classification:
  `GENERAL` for unlinked world news, `PREGAME` for pre-tip game-linked items,
  or `OUTCOME_DEPENDENT` for a fully linked downstream item. Unknown classifications,
  missing linked-game state, ambiguous timestamps or mixed sealed-game outcomes
  hide the **entire item**. Every media field, including thumbnails and runtime,
  must independently pass the global timestamp check. For a `PREGAME`
  media item, each exposed field must also be available before every linked
  game's tipoff: a post-tip edit to an old preview's headline, thumbnail, or
  runtime is not pregame-safe even when it precedes the current cursor.
- Only pass `GameProjection`/`MediaProjection` into
  `build_safe_ai_context`. Do not forward raw provider observations, source
  capture text, extra metadata, or unrestricted headlines to models or the UI.
  `order_game_cards` accepts projections and sorts using only the admitted
  pregame-interest signal with a stable game-ID fallback; favorite teams and
  hidden postgame scores are not inputs.

**Trust and implementation boundary**

These are pure policy functions, not a complete ingest classifier or enforcement
gateway. The upstream read-model adapter must establish valid provenance,
complete cross-game linkage, trusted sensitivity classification, and canonical
as-of values. Untrusted source claims and AI output must **never** create these
trusted assertions directly. A later API service must authorize explicit reveal
requests, persist acknowledgements, and return only the safe projections.

Game acknowledgement permits game-specific downstream facts but **never**
relaxes the global `time_cursor` for general media. The conservative kernel
does not redact mixed articles; it omits them rather than guessing which
phrases could reveal still-sealed games.

**Test scope**

`backend/tests/test_spoiler_policy.py` exercises late standings/observations,
in-game and final fields, hints versus scores, boundary inclusivity,
ambiguous/naive timestamps, cross-game contamination, updated headlines,
post-cursor thumbnails and runtimes, ranking order, and AI projection inputs.


## Strict HTTP read-model boundary (issue #15)

`nba_time_machine.api.read_models` translates **only** pure policy projections
into Pydantic response schemas. Converters require the exact disclosure layer,
reject unrecognized fields, and reject direct source/provider records. This is
serialization, not authorization: callers must first establish a trusted
`GameContext` and run `project_game` or `project_general_media`.

- `GameCardResponse` and `PregameDetailResponse` accept PREGAME projections
  only. Cards can include pre-tip interest but never a result, score, runtime,
  highlight image, or postgame watchability.
- `WatchabilityResponse` and `WatchabilityReasonResponse` are separate
  requested layers, with coarse text and optional text reason. Neither can
  contain a numeric postgame quality signal or full game result.
- `FullGameResponse` requires a policy FULL projection; the policy produces
  one only for an unsealed game or an authorized explicit full reveal.
- `MediaFeedItemResponse` is built from `project_general_media`, which
  checks the global cursor independently of single-game acknowledgement.
  `MediaFeedResponse` and `GameListResponse` can serve as composable
  dashboard endpoints once the service routes exist.
- Missing optional fields are omitted entirely from JSON, not emitted as
  `null`. Schemas reject unexpected fields (`extra="forbid"`). HTTP
  routes must use these typed models instead of unfiltered ORM/AI/raw data.
  `scheduled_tip` is currently an ISO-8601 string emitted by the policy
  scalar boundary; no inferred tip times are introduced by the serializer.
- Card `state` is caller-supplied and **must** be derived by the trusted
  #14 game-state service, not a client request. This issue intentionally
  does not introduce database endpoints or durable acknowledgement.

For frontend fixture refresh, from `backend/` run:

```bash
PYTHONPATH=src python scripts/export_read_model_fixtures.py
```

The script exercises the real spoiler policy before serializing synthetic
pregame/verdict/reason/full/media fixtures. The deliberately post-cursor media
item must not enter the global feed. The fixture is demonstration data, not
evidence of a live data provider.

## Trusted game disclosure service (issue #14)

The `GameDisclosureService` owns the application-level transition from a
sealed game to an explicitly acknowledged one. It takes the persisted profile
cursor from `TimelineService`, a server-side `TrustedGameSnapshot` and a
profile/game acknowledgement record. No HTTP request accepts raw game facts,
arbitrary provenance, an `acknowledged` flag, or an `explicit_full_reveal`
flag. These inputs must come from trusted server repositories.

- `GET /profiles/{profile_id}/games/{game_id}/pregame` exposes only the
  policy PREGAME projection, regardless of acknowledgement state.
- `GET .../watchability` and `GET .../why` explicitly request separate
  disclosure layers without persisting an acknowledgement. Unavailable
  verdicts/reasons are omitted, never invented from a final score.
- `GET .../full` works only when the game is already unsealed.
  For a sealed game it returns HTTP 409 and does not change state.
- `POST .../reveal` is the deliberate full reveal. For a still-sealed game,
  it requires a trusted final observation with both scores, persists one
  acknowledgement per `(profile_id, game_id)`, then projects FULL. Repeated
  calls are idempotent. No `watched` field is stored.
- The cursor reaching an observed final protection boundary unseals a game
  without writing an acknowledgement. A missing or invalid boundary never
  unseals from an inferred scheduled end; equality counts. A passive FULL
  read of a timeline-unsealed game still omits fields first known after the
  cursor; a deliberate POST reveal may authorize those game-specific updates
  and persist the explicit acknowledgement.
- Media remains governed by the global cursor. `general_media` still calls
  `project_general_media` after loading linked game state, and even an
  acknowledged game cannot make post-cursor general articles appear.

The `game_acknowledgements` table has a composite profile/game primary
key, FK references to the timeline profile and canonical game, and a
server-generated acknowledgement timestamp. PostgreSQL `ON CONFLICT DO
NOTHING` makes concurrent repeat reveals idempotent. Acknowledgement writes
never update `timeline_states`.

The initial `SqlAlchemyGameSnapshotRepository` is conservative: it uses a
historical observation made *before tip* for pregame identity/tip fields.
It derives a protection boundary only from a recorded final observation
and uses the later of observed, available and explicit final timestamps.
Postgame score fields retain the final observation's availability and
observation timestamps. More kinds of historical fields can be added by
future adapters, but source backfill must not silently become pre-tip truth.

The game-specific endpoints currently expose only available structured
facts. The postgame watchability classifier/labels belong to #10, and
general feed endpoint wiring remains a later dashboard integration task.


## Trusted historical game-list composition (issue #28)

`GET /profiles/{profile_id}/games?date=YYYY-MM-DD` returns the existing strict
`GameListResponse` shape: the **persisted** UTC `time_cursor` and safe pregame
cards with real canonical game UUIDs. `date` is required and is an NBA/Eastern
(`America/New_York`) calendar date, not the requester's local date nor a
24-hour interval assumed in UTC. Separate Eastern midnights handle DST.

Membership and schedule use **only** observations with both `available_at`
and `observed_at` no later than the persisted cursor and strictly before the
observation's `scheduled_tip_at`. Per game, select the latest such observation
(by observation time and stable UUID tie-break) **before** testing its
scheduled state and whether its scheduled tip lies within the requested day.
A changed date, known cancellation or later correction cannot leak into an
earlier cursor, and a game does not appear twice on both its old and new slate.
Finals, final-result counts, real-world status, acknowledgment and favorite
teams do not participate in selection or canonical card order.

For each selected UUID, the trusted snapshot reader supplies fields and temporal
provenance; the service creates a server-side `GameContext` from persisted
cursor and per-game acknowledgement, runs `project_game(PREGAME)`, then
`order_game_cards` and `game_card_from_projection`. Missing pregame team
identity/tip, conflicting as-of date, no historically observed pregame state
or an uninitialized profile fail closed. Unknown/uninitialized profiles return
404; an unconfigured database returns 503. An empty slate can mean **missing
historical coverage**, not proof that no NBA games occurred. There is no fake
game-count or guessed tip/protection-end time.

Explicit `POST .../{game_id}/reveal` only changes that game's stored
acknowledgement; the list's membership, order and global cursor remain
unchanged. Actual observation ingestion/Neon provisioning and frontend live
wiring remain separate tasks. Unit tests cover route validation, layer
exclusion, acknowledgement isolation and ET/DST dates; PostgreSQL integration
tests cover latest as-of selection, rescheduling, future backfill and stable
canonical identity.

## Explicit observed-schedule browsing (#74)

The default game-list view retains genuine pre-tip/as-of selection. The optional
`view=observed` uses the last observation known by the persisted cursor for each
game, ranking before filtering by tip date. It never filters membership by status,
scores or final availability. Only basic home/away identity and scheduled tip can
pass policy after tip, and both observation and availability must precede/equal
the cursor. All other pregame fields still require pre-tip provenance. No timestamp
is backdated and no historical pregame reconstruction is claimed. This enables
inspection of backfilled schedules after their actual observation date.

The connected UI resumes backend state and makes explicit per-game disclosure
requests; it never silently requests outcomes for acknowledged games. See
[Frontend integration](../FRONTEND_INTEGRATION.md) for routing and UI state contracts.

## Retrospective season replay (#77)

The explicit `view=replay` schedule allows imported game identity and scheduled
tip on original Eastern game dates through the cursor's Eastern day, irrespective
of collection date. It is a labeled retrospective testing surface, not a claim
of verified pre-tip publication. Later corrections and postseason participants
can be reflected. The trusted repository selects the latest timestamped observation
before date filtering, without result/status-based membership or ordering.

`GameContext.season_replay` permits only home/away identity and scheduled tip
with actual provenance to bypass cursor/pre-tip gating. No stored timestamps
change. Other pregame facts, full-result authorization, media and strict/observed
views retain existing contracts. Results stay hidden on cards even after
acknowledgement; explicit reveal persists only that game's acknowledgement.
Historical final/protection times are not invented from game date or tipoff.

### Archived watchability disclosure (#10)

Only explicit watchability/why requests consult the postgame archive, at the
persisted profile cursor. The disclosure service validates one internally
consistent eligible score and converts it to configured coarse bands before
`project_game`; no numeric quality or component metadata enters public fields.
No evidence means no verdict or fabricated reason. Frontend postgame ordering
requires fresh per-request consent on a historically observed pregame slate;
retrospective replay does not authorize outcome ranking. Budget inputs are user
allocations, never observed runtimes. Hints and picks leave acknowledgement and
media cursor unchanged.

## Reviewed general media history (#91)

General media uses **a separate profile-cursor-bound query** with no season-replay
exception. The query selects the latest per-item raw capture revision observed
by the cursor, requires explicit per-revision operator review (classification,
complete game linkage and rights clearance), then sends typed fields through
`project_general_media` before JSON serialization. Review time is a
conservative availability lower bound; publisher dates never backdate it.
Updated but unreviewed headlines fail closed instead of falling back to a
safe-looking earlier revision. Outcome-linked media additionally verifies each
linked game's unsealed status; one game's explicit acknowledgement never
advances the global media clock or exposes a different sealed game. Link
candidates are not authorizations. See [Media feed](../MEDIA_FEED.md) for
cursor-bound paging and operational source/rights review.


### Explicit retrospective scoring-workbench assumption

The owner-directed schema-6 experimental formula may apply the first complete
Ringer snapshot to earlier games. It preserves actual observation/availability,
labels retrospective and cross-season use, and never changes strict consumer
projections, production scores or old schema-5 tuning configurations. This is a
separate tuning assumption, not evidence of pre-tip knowledge. See
[Star Power](../STAR_POWER.md) for the exact selection and failure rules.


## Two-mode viewing guide (#111)

[Viewing guide](../VIEWING_GUIDE.md) defines the independent Browse knowledge
clock and strict Time Machine disclosure boundary. The new guide endpoint never
uses replay to fake pre-tip knowledge. Its full-result path filters all fields
by the selected knowledge cutoff before projection, even for acknowledged games.
Exact ratings and traceable component fields are available only through explicit
POST consent; ordinary cards and general media never receive these fields.

### Open reconstructed expectation (#10)

Browse's explicitly labeled record-only expectation is a separate allowlisted
response beside safe cards, using entering W–L reconstructed from validated
completed-game records. No result, removed result, final record, participation,
trajectory or later player ranking is exposed. This is not historical pre-tip
knowledge; Time Machine withholds the reconstruction entirely. The shared
calculation also supplies a versioned overall-rating contribution behind existing
postgame consent. Actual provenance, source revocation and revision checks remain
mandatory. See [Pregame expectation](../PREGAME_EXPECTATION.md).
