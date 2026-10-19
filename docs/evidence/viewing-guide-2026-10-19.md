# Viewing guide verification — October 19, 2026 (#111)

## Automated checks executed locally

- Frontend: 40 tests passed; TypeScript check and Vite production build passed.
- Guide backend unit/HTTP and real PostgreSQL persistence: 9 tests passed.
- Full backend on a newly migrated disposable PostgreSQL 16 database:
  569 passed; one existing macOS launcher cleanup test failed with
  `PermissionError: [Errno 1] Operation not permitted` in `os.killpg`.
  A targeted rerun reproduced that host-specific failure. No launcher code
  changed for this issue. The final Linux CI result is linked in PR #112.
- The new PostgreSQL test captures synthetic evidence on an isolated fixture day,
  archives the existing model, verifies safe default cards, honest backfill ranking,
  exact component arithmetic, bulk results, strict-mode isolation after a Browse
  acknowledgement, unchanged cursor and masking after a newer nonfinal revision.
- Frontend regressions cover current-day startup, same-day/direct-date navigation,
  stale date responses, two modes, hidden reloads, one-request reveal-all,
  confirmation focus/Escape, evidence tiers, missing clues, all teams and persisted
  favorites, canonical-order filtering, cursor-bound secondary news and fail-closed
  response validation.

## Actual Chrome + configured database walkthrough

- Browse opened on current NBA/Eastern October 19 in 2026/27, with honest missing
  coverage. Direct date selection and previous/next controls loaded October 14.
- Six matchups appeared in chronological default order without outcomes, ratings,
  finality-based badges or implicit ranking requests.
- Explicit watch order returned five eligible archived ratings and one unrated
  game. No unrated-as-zero fallback appeared.
- Worth watching opened a coarse verdict. No clue button appeared for a game
  without qualifying clue evidence. Show rating & why opened the archived exact
  rating, additive components, provisional-model note and inspectable provenance.
- One Reveal all click displayed available results and ratings across the date,
  including an explicit unrated game. No repeated confirmation dialogs appeared.
- Switching to Time Machine removed disclosures and showed the same pre-existing
  October 15 03:56 UTC cutoff. No advancement was performed. Returning to Browse
  again hid outcomes.
- Keyboard Enter opened the individual confirmation with focus on its confirm
  button; Escape dismissed it and returned focus to Show result.
- All 30 team choices were present. Selecting off-slate Lakers survived a real
  browser reload. Original empty favorite selection was restored after the test.
  Reload opened today's Browse date without prior scores or watch order.
- At 390×844, DOM page width equaled viewport width (390 px); no horizontal
  overflow. Games remain ahead of the secondary viewing tools. The temporary
  viewport override was reset. Desktop and mobile safe default screenshots are
  committed alongside this record; no exposed results are included in them.

[Desktop](viewing-guide-desktop-2026-10-19.png) ·
[Mobile](viewing-guide-mobile-2026-10-19.png)

No collection or scoring calibration was performed. Existing archive values were
read, never replaced by workbench proposals. The consumer test's deliberate full
reveal wrote ordinary per-game acknowledgements on the existing browser profile;
the saved timeline was not changed. Schema and collection configuration were not
modified. Favorites remain browser-local, and coverage/model quality remains
partial/provisional rather than claimed complete.
