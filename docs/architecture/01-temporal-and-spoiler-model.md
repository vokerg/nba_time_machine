# Architecture: temporal and spoiler model

## The fundamental query

Every read path should be able to answer:

> What was safe for this user to know at time T, given the games they have already watched and their spoiler policy?

This is more precise than filtering rows by publication date.

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

For strict mode, a safe default is:

```text
available_at = max(defensible publication time, first reliable observation time)
```

The exact reconciliation algorithm belongs in a dedicated implementation issue and must be testable.

## Game causality

Content/facts may be linked to one or more games with a relationship such as:

- pregame;
- in-game;
- postgame;
- retrospective.

For an unwatched game, in-game/postgame consequences are hidden even when the global cursor has advanced beyond the game's finish, unless the selected spoiler mode explicitly allows them.

## User state

Expected fields:

- selected `time_cursor`;
- spoiler mode;
- set of watched game IDs;
- postgame ranking visibility;
- historic-event hint level.

## Safe projection

The policy engine should return a projection, not merely an allow/deny bit, because one item can contain both safe and unsafe fields.

Example: a Monday injury article may safely reveal that a player was already questionable Sunday morning but not reveal an injury sustained during Sunday's game. Initially we should prefer hiding the whole item unless a deterministic field-level transform exists.

## AI rule

No model is asked to "remove spoilers" from forbidden content.

Forbidden content never enters the prompt.

This invariant should have regression tests using deliberately spoiler-heavy fixtures.
