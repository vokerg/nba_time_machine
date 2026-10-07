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
