# Fan viewing guide (#111)

The consumer home is a dated basketball viewing guide. **Browse games** opens on
the current Eastern day in the supported July 2025–June 2027 range, independent
of the saved Time Machine cursor. Select any supported date, including future
collected schedules and retrospectively collected matchups. Missing coverage
never establishes that no games were played. Scores, ratings, game finality and
postgame order never affect the default cards' membership, state or ordering.

**Time Machine** is a deliberate second mode. The visible saved cutoff bounds
all game information. The user selects a later UTC cutoff and confirms its
irreversible advancement. Changing date or mode never changes the cutoff.
New profiles start at the earliest supported date, with no automatic advancement;
Browse still opens on today's NBA day. Existing profiles resume unchanged.

## Explicit API contract

`GET /profiles/{profile_id}/guide?date=YYYY-MM-DD&mode=browse|time-machine`
returns only allowlisted pregame card fields and the actual persisted cursor.
Browse takes a server UTC cutoff at request start. Time Machine takes the minimum
of that time and the persisted cursor. Both choose the latest schedule observation
known by that cutoff **before** filtering its Eastern date. There is no replay
exception, no backdating and no requirement that the matchup was collected before
tip. Other pregame fields still require actual pre-tip provenance. The existing
`observed` repository implementation is reused internally, but this is a separate
consumer authorization boundary, not a renamed legacy view. Card state is uniformly
sealed to avoid leaking completion/protection state; even previously opened games
return without outcomes. Legacy API contracts remain available.

`POST /profiles/{profile_id}/guide/disclose` accepts `date`, `mode`, the expected
persisted `time_cursor`, `consent: true`, `level` and an optional `game_id`.
Consent is required before any database lookup. A game ID must belong to the
server reconstructed date/mode slate. At most 32 games are eligible per date.
The server captures one cutoff for the entire operation and rechecks the saved
cursor before writing acknowledgements or returning a response. This is a
READ COMMITTED defensive recheck, not a lock against later concurrent advances.

- `verdict`, `clue`, `rating`: require one game; progressively expose a coarse
  verdict, a deterministic verified signal clue, or exact rating and components.
- `order`: whole-date outcome-based ordering; returns IDs only, no rating details.
- `full`: one game or the whole date; returns eligible scores/results plus exact
  archived rating/details and a watch order for the date. The button itself is
  explicit date-scoped consent; no repeated per-game confirmations.

Full results are timestamp-filtered **before** projection. Old acknowledgements
and the legacy explicit-reveal exception never grant Time Machine post-cutoff
access. Only results actually returned create durable game acknowledgements.
Nothing advances the global media clock. Unavailable/future results stay absent;
the client reports this rather than showing fabricated zero scores.

## Rating integrity and disclosure

Only archived versioned `postgame-v1` scores eligible at the request cutoff can be
shown or ranked. The archive's arithmetic/provenance checks still apply. The guide
additionally re-derives from currently verified canonical evidence using the
existing morning pipeline (or curated ranking-fact reader); value, model and all
components must exactly match the archive. A newer correction, revoked policy,
ambiguous identity or incomplete evidence withholds the stale rating. This read
performs no collection, calibration, archive write or workbench-formula adoption.

The fan breakdown converts each stored weighted contribution into points out of
ten using the sum of available weights. Source reference, observation,
availability, version and score snapshot remain inspectable under Rating evidence.
Clues use explicitly supported signals only when their verified normalized value
is at least 0.5; no winner, score or AI narrative is included. Verdict responses
advertise clue availability only after consent; missing clues render text, never
a dead action. Missing scores remain unrated and never sort as zero.

Favorites include all 30 teams and persist per opaque profile in this browser.
The watch order excludes those teams by default, with their matchups listed
separately. Include my teams filters the same canonical server order without
changing scores or requests. Preferences are not authentication or spoiler consent.
The queue UI is removed; queue APIs and records remain. News is secondary,
explicitly opened, and always reads the saved global cursor, even in Browse.

## Validation

Run frontend tests/build and backend guide/policy tests. PostgreSQL persistence
checks must use disposable local/CI databases, never the owner's database.
See the PR for actual executed checks and browser verification.
