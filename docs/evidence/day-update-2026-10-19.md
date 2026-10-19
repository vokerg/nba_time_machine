# Viewing guide date update — October 19, 2026

## Executed verification

- Full backend suite on migrated disposable PostgreSQL: **578 passed**.
- Frontend suite: **46 passed**; TypeScript and Vite production build passed.
- New synthetic PostgreSQL test exercises the actual protected POST/background
  job/status flow, normalized capture persistence, production rating archive,
  safe slate refresh, opt-in watch order, unchanged timeline/acknowledgements,
  run processing metadata and repeat capture deduplication.
- Unit tests cover single-flight duplicate requests, other-date conflicts,
  cross-profile status isolation, loopback/Host/Origin gates, missing action
  header, stale cursor, mode restrictions, timeout and shutdown cancellation,
  generic errors without source/credential bodies, and score-opaque responses.
- Rendered frontend tests cover explicit-only POST, safe polling, terminal refresh,
  arbitrary-date recovery after reload without POST, server-restart guidance,
  stale responses after date switches, no collection in Time Machine and
  preventing an old tab from deleting a newer recovery handle.

## Actual Chrome and configured owner database

The new button was used for October 18 and October 16. October 18 returned without
stored matchups; the UI did not invent games or ratings. The October 16 action
showed Fetching game evidence and Updating verified ratings, then finished and
refreshed the twelve stored matchups. A real browser reload during publishing
restored October 16 and reconnected to the same job, finishing without manual
terminal commands or an additional automatic collection request.

Only a subsequent deliberate watch-order request revealed the ranked selection:
eleven games had eligible production ratings; one remained unrated. The existing
Lakers favorite was excluded from the presented order, leaving ten visible picks.
No score/result or ranking was exposed merely by collecting. Switching modes
cleared the disclosed ordering; Time Machine retained October 15 03:56 UTC, and
the collection action was absent there. The user's favorite was left unchanged.

These are real canonical captures and production archive writes authorized by
the explicit date action. No source was enabled, no retention policy changed,
no timestamps were backdated, and no workbench formula was promoted. The
remaining unrated game was not assigned an invented score. Daily scheduling
was not installed. Screenshots show the safe default view and the new action.

Final hosted CI is linked from PR #112.

Desktop and 390×844 mobile screenshots were saved after clearing the consented
watch order. All scores/ratings are hidden in them; page width equals viewport
width on mobile. The viewport override was reset after inspection.

[Desktop action](day-update-desktop-2026-10-19.png) ·
[Mobile action](day-update-mobile-2026-10-19.png)
