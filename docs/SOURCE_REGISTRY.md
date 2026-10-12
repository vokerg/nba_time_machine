# Source registry synchronization and health

The reviewed desired-state file is `config/sources.seed.json`. The Postgres
`sources` table is the runtime registry; **the seed is not evidence that an
adapter works or that a source may be enabled**. Most starter sources are
disabled and unverified.

## Validate and synchronize

Run from the repository's `backend/` directory after installing `.[dev]`:

```bash
python scripts/sync_sources.py --validate-only
# Requires DATABASE_URL and an Alembic-migrated PostgreSQL database:
python scripts/sync_sources.py --health
```

`--seed /path/to/reviewed.json` selects another desired-state file. Invalid
source kinds, verification states, retention policies, access booleans,
cadences, source identifiers, unrecognized fields and duplicate IDs fail
validation before any DB write. `adapter_settings` may contain non-secret
adapter configuration; store credentials only in environment/secrets management.

The upsert is transactional and idempotent: unchanged rows are not rewritten.
Only `SourceDefinition` fields are Git-owned. Existing `runtime_cursor`,
creation timestamps, collection-run history and source-outcome records survive
sync. **Removing an ID from the seed does not delete or disable the stored
source**: explicitly set `enabled: false` to disable it. Sync does not run a
collector or certify a source.

`enabled`, `verification_status`, and DB existence/configuration are
independent properties. For example, a verified source may remain disabled.
A caller running collection must separately check access/verification and
credentials, and report `skipped_config` when it cannot run.

## Health projection

`list_source_health(session)` returns a stable ID-sorted view of every
configured source (including sources never collected), with enabled/verified
flags, verification status, the latest outcome by run start time, and cumulative
outcome counts. Counts use:

- **attempted:** all persisted source outcomes;
- **succeeded:** `ok` and `idle`;
- **skipped:** `skipped_config`;
- **failed:** `partial`, `rate_limited`, `auth_error`, `blocked`,
  `parse_error`, `network_error`.

A source with no outcomes has counts of zero and no last status, rather than
claiming to be healthy. `--health` prints this projection as JSON Lines after
a successful sync.

Unit validation works offline. Integration tests exercise sync/health with
migrated PostgreSQL in CI; **a production Neon smoke test is not claimed**.
Collectors, source verification and ingestion health UI are separate issues.

## Official team-site discovery (Issue #9)

All 30 NBA teams now have canonical official homepage entries in the seed.
See [SOURCE_TEAM_COVERAGE.md](SOURCE_TEAM_COVERAGE.md) for the 2026-10-11
identity research, team-by-team URLs, access caveats and next verification
checks. **These 30 entries are disabled and unverified for collection**;
identifying a public website is not equivalent to a passing collector smoke,
rights approval, a reliable news feed or historical availability provenance.
No existing sources were auto-enabled by this expansion.

## Feed-access research (Issue #9)

[Source feed-access research](SOURCE_FEED_ACCESS.md) tracks a distinct NBA
Communications RSS candidate and a now-redirecting Celtics legacy RSS URL.
The candidate remains disabled and unverified pending bounded feed parsing,
terms/retention review and an operator-approved live collector smoke.

## Official injury and transaction publication surfaces (Issue #9)

[Official league data-access research](SOURCE_OFFICIAL_DATA_ACCESS.md) records
2026-10-12 source-page inspection for NBA player transactions and the
**2025-26** official injury-report season page. The discovered URLs replace
non-addressable seed placeholders; both records remain `enabled=false`,
`verification_status=unverified`, and `retention_policy=metadata_only`.
They are **not** validated structured NBA feeds. There is no verified 2026-27
injury-report URL, item-level extraction, archival history, publisher rights
clearance or live adapter smoke from this research. Do not enable them through
seed sync on the strength of a browser-readable page.


## National-media NBA landing pages (Issue #9)

Four national publisher NBA section URLs have been inspected and substituted
for seed placeholders: CBS Sports, NBC Sports, Bleacher Report and The Ringer.
See [SOURCE_NATIONAL_MEDIA_ACCESS.md](SOURCE_NATIONAL_MEDIA_ACCESS.md)
for dated observations, item-level and rights gaps, and cross-platform
identity caveats. The four sources remain disabled/unverified with
`metadata_only` retention; `rss_or_web` remains an access-method
placeholder, **not** a validated collector. No RSS discovery, item parser,
historical replay or production source-health claim is made.
