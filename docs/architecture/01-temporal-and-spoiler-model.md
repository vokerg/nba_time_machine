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
