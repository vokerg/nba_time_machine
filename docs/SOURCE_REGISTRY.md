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
