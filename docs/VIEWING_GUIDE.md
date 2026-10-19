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

Guide reads batch the date's game snapshots and acknowledgement state. After a
consented disclosure, the server retains the internally prepared day's snapshots
and verified archived ratings in a bounded process-local cache (32 entries,
one-hour maximum age). Other games and layers reuse that preparation. Only the
specifically consented response fields are serialized; loading watch order never
sends hidden results or exact ratings to the browser.

Every server request still resumes the persisted cursor and checks a PostgreSQL
revision signature. It contains row IDs and MVCC row versions for structured
sports identities, schedules, evidence, source policies and archived ratings.
Inserts, in-place corrections and deletes invalidate preparation. Knowability and
fact-validity boundaries also change the signature as time advances without any
write. The signature deliberately covers all structured sports data, so unrelated
sports updates may invalidate a day too. Profile, mode, date and saved cursor are
part of the cache key. A disclosure always rechecks the cursor before returning
or acknowledging results; prior consent and acknowledgements never grant later
Time Machine access. Permission checks and response layers are not cached.

The browser reuses already disclosed layers (including unavailable answers and
empty orders) without any request. A newly requested layer still needs consented
server access but reuses the prepared day. Failures remain retryable. Changing
date, mode or cursor, reloading the browser, or completing **Fetch games & update
ratings** clears browser disclosures. This existing action is the explicit master
day refresh; ordinary spoiler buttons never fetch providers or write new ratings.
A cold/evicted server entry verifies existing archive evidence once; unchanged
warm entries perform no trajectory derivation, archive read or snapshot reload.

`test_guide_performance.py` proves warm disclosures use three SELECTs (saved
cursor, revision signature, final cursor recheck), versus the original eight-game
implementation's 124 for order, 54 for a single verdict and 58 for a result.
Initial cold preparation uses at most 15 reads independent of one/eight games.
Full disclosure additionally writes one idempotent acknowledgement per returned
result. Browser repeat-click tests require zero requests. These are query counts,
not a claim about end-to-end latency or database connection cold starts.

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

## Fetch games & update ratings (owner follow-up)

In Browse, choose a supported date up to today's Eastern NBA day and press
**Fetch games & update ratings**. This explicit action runs the existing bounded
ESPN/CBS morning collector, then publishes the existing production model from
verified canonical evidence. The current workbench formula is not adopted. No
scheduler is installed and selecting a date alone still performs no collection.

`POST /profiles/{profile_id}/guide/update` requires JSON, the custom
`X-Guide-Action: update-day` header, `date`, `mode: browse` and the expected saved
`time_cursor`. This unauthenticated personal write action is **loopback-only**, with
Host and same-origin checks; it is not a public administrative API. The saved
profile cursor is checked but never advanced. The existing source policy, manual
collection eligibility and PostgreSQL sports lock remain authoritative. This
cannot enable sources or override verification, retention or provider failures.

A 202 response returns an opaque job UUID, date and phase. Poll
`GET /profiles/{profile_id}/guide/update/{job_id}` for collecting, publishing,
finished or failed. A repeated start while that profile/date runs joins the same
job; a different concurrent date is rejected. One job per application process,
40 provider requests, 20 games, and four minutes bound the action. Per-game
transactions preserve valid captures/ratings when unrelated games fail.

Consumer status deliberately excludes results, rating availability counts,
completion counts, source payloads and per-game diagnostics. Collection consent
is not spoiler consent. The completed update refreshes safe cards and clears
previous disclosures; revealing watch order or results remains a separate action.
Pending or invalid evidence stays unrated. The collector still skips unfinished
game summaries; this action does not promise live coverage or a complete schedule.

Only the current job's opaque ID/date is saved in browser storage to reconnect
GET polling after reload. No POST occurs on reload. Job state is process-local;
a server restart/replaced job yields an explicit reconnect/retry message. Canonical
captures, source health and per-game rating snapshots remain durable. Processing
counts/as-of are retained in the existing collection run's `rating_update`
metadata for operator inspection. Timeout/interruption can leave useful partial
work saved. Application shutdown cancels and awaits the job before closing DB
connections. Time Machine does not expose the fresh-data action; newly collected
facts cannot become knowledge before their actual observation time.

## Typography (owner readability revision)

Use 18px-equivalent body text, 17px controls, 16px secondary content and no text
below 15px-equivalent metadata. Shared rem-based sizes follow browser font
preferences. Matchup names stay 24px on mobile as well as desktop. Do not restore
the original 9–12px labels, compact hint text or mobile type reductions. Let
controls, metadata and section headings wrap as needed; provide roomier line
spacing and touch targets instead of squeezing text to fit.

## Open pregame expectation (#10)

The guide now exposes an independently allowlisted `expectations` map in Browse.
It shows record-only reconstructed expectations and reasons openly, including
entering W–L, sample confidence and missing families. Time Machine never admits
this reconstruction. The same shared record-strength calculation supplies the
workbench bonus and new `postgame-records-v2` production ratings; archived v1
ratings remain immutable. Both supported production versions require current
verified evidence and explicit postgame consent. See
[Pregame expectation](PREGAME_EXPECTATION.md) for coverage, formulas and timing.


### Shared pregame Star Power (#10 owner follow-up)

The fan guide now includes an independent, openly explained roster-star potential
component, including preseason and upcoming observed games. Missing team records
do not suppress eligible stars. Only ranking/roster evidence genuinely known
before tip is admitted; confirmed availability remains unknown. Time Machine
also requires that evidence before its saved cutoff. The same rank/slot/team
functions serve the workbench and new `postgame-stars-v3` archive model, which
uses actual verified minutes instead of adding potential and realized stars twice.
The earlier record-only limitation is superseded for this component. No
first-snapshot consumer backfill, new collection, old-archive rewrite or global
media exception is introduced. See [Pregame expectation](PREGAME_EXPECTATION.md).
