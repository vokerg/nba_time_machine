# Local ingestion & coverage dashboard (#89)

The **operator dashboard** is a separate, spoiler-visible local inspection tool. It is neither the consumer API nor the scoring workbench and has **no collector, scheduler, status-mutating route, or public administrative authentication**.

## Launch

Set up the backend virtual environment, database connection and migrations as described in [Development](DEVELOPMENT.md). From the repository root:

    backend/.venv/bin/python backend/scripts/run_operator_dashboard.py --port 8766

Open http://127.0.0.1:8766. The launcher binds **only** to 127.0.0.1, with no forwarded proxy headers. Request middleware also checks the client IP, Host and Origin. This is **not** a remotely secured admin service. Do not reverse-proxy or deploy it publicly. The PostgreSQL read session sets REPEATABLE READ, READ ONLY and a 15-second statement timeout. A separately provisioned database read-only role is recommended for defense in depth; the app still enforces read-only transactions with normal database credentials.

Use filters for an Eastern NBA calendar day, season label, source ID and source-outcome status. **Source filtering also restricts games and normalized evidence facts to that source**; status filters apply to outcomes and runs (not game finality). Refresh performs no HTTP collection. JSON/CSV exports contain only the same sanitized operational metadata, not raw feeds, captures, event arrays, URLs, credentials, descriptions or exception text. CSV cells are protected against spreadsheet-formula interpretation.

## Interpretation

- Source configuration is not evidence of a working collector. Verification, enablement, authentication requirements, cadence and last outcomes are separate fields. Last successful source outcome only means an ok report, **not** complete data coverage. Idle is its own state; a recent idle check is not a new capture.
- Freshness is **disabled**, **unverified**, **unknown**, **failing**, **stale**, **idle_recent** or **recent_check**. The latter two require a recorded finished ok/idle outcome within twice the configured cadence. Unknown timestamps never become zero minutes or healthy by inference. A last error is displayed only when it is a restricted diagnostic code.
- The game table displays **stored, dated NBA game observations** for the selected Eastern day, taking the latest observation per canonical game (or the latest observation from the filtered source). Missing scheduled tip timestamps have no defensible Eastern date and cannot appear in this view. The absence of a stored game is **not** proof of an empty slate.
- For the existing provider_game_evidence facts, play-by-play and player box show complete, partial, not_final, or not_collected with individual provider provenance. A complete family must have actual final evidence and usable rows without parser/coverage errors. Unfinished schedule-only games may lack facts. Validated separate **team box** coverage is not recorded by this family and is displayed as unsupported, not silently inferred from player rows or the scoreboard. These are structural provider checks, not guarantees of factual accuracy.
- Scheduled tip and final status are **provider claims**. observed_at/available_at record actual collection/availability; game finality or publisher timestamps are not retroactively asserted from present-day data.
- For bounded queries, the report caps registry entries at 500, collection runs at 60, recent outcomes at 2,000, dated observations at 1,000, and provider evidence facts at 2,500. An exceeded cap returns an error rather than silently presenting totals as complete. The dashboard lists only up to 50 run rows and 80 filtered outcome rows. Very old source outcomes beyond the bounded window may appear unknown; inspect canonical records for exhaustive audits.
- Unknown, unsupported and not collected are **not** zero. A failed source does not invalidate unrelated source observations.

## Validation status

Focused synthetic tests cover disabled/unverified sources, recent idle, failed and stale outcomes, no PBP, partial box scores, independent provider coverage, safe CSV and loopback/consumer route isolation. The integration test runs only against disposable local or CI PostgreSQL, verifies persisted morning evidence through the read-only report and checks transaction read-only mode.

**Validation checkpoint:** This PR is initially developed through GitHub-only remote edits. Test execution on a migrated disposable database and hosted CI must be checked before considering merge; tests listed above are authored, not represented as already passed. No real data coverage or collection freshness is claimed by this feature until verified against the configured database.
