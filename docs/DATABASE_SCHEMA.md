# Database schema

This document describes the current PostgreSQL persistence model. It covers source/collection provenance plus the structured sports identity and temporal-history substrate. Collector behavior, provider adapters, spoiler policy, retention enforcement, and live Neon validation remain separate work.

## Relationships

```text
sources
  ├──< source_items
  │       └──< raw_captures
  ├──< source_outcomes >── collection_runs
  └──< raw_captures   >── collection_runs
```

A raw capture may link to one normalized `source_item`. The link is nullable because capture can precede normalization.

The structured sports domain adds:

```text
seasons ──< games >── teams
                    ↗
teams/players/seasons/games
  ├──< sports_external_identities
  └──< temporal_facts

games ──< game_observations >── sources
temporal_facts >── sources
```

Sports entities use internal UUIDs. Provider IDs live in a separate mapping table so a provider switch does not redefine internal identity.

## Tables

### `sources`

The runtime registry record for a configured source.

Important fields:

- stable string `id`;
- source `kind`, `adapter`, `category`, and `locator`;
- `enabled` and `verification_status` as distinct states;
- `cadence_minutes`, `requires_auth`, and `retention_policy`;
- JSONB `adapter_settings` for provider-specific configuration;
- nullable JSONB `runtime_cursor` for collection state that must survive desired-state seed synchronization.

The retention policy is constrained to the documented values: `full`, `normalized_full`, `metadata_excerpt`, and `metadata_only`.

### `collection_runs`

One execution of collection work.

It records start/end timestamps, an optional collector version, and JSONB run metadata. Per-source success or failure is not collapsed into the run row.

### `source_outcomes`

One outcome per source per collection run.

Status is constrained to the ingestion contract: `ok`, `idle`, `skipped_config`, `rate_limited`, `auth_error`, `blocked`, `parse_error`, `network_error`, or `partial`.

This separation lets one source fail without treating unrelated sources as failed.

### `source_items`

The stable logical identity for normalized content from a source.

`(source_id, canonical_identity)` is unique. The record can hold normalized text and metadata plus distinct temporal fields:

- `published_at`: source/platform publication time when known;
- `discovered_at`: first reliable observation by NBA Time Machine;
- `captured_at`: capture chosen for the current normalized representation;
- `available_at`: conservative earliest time the information is safe to treat as publicly knowable.

These timestamps are deliberately not interchangeable.

### `raw_captures`

An immutable capture/snapshot obtained during one collection run.

Each row preserves source/run provenance, content hash, source identity fields, publication/discovery/capture/availability timestamps, and optional retained text/raw payload. The schema permits nullable content fields; later persistence code must still enforce each source's retention policy before writing them.

A unique constraint on `(collection_run_id, source_id, external_id, content_hash)` rejects an exact duplicate when a source provides an external ID. The same payload captured in a later run remains a separate row, preserving observation history. Sources without a stable external ID require deterministic deduplication logic at the persistence boundary rather than relying on this nullable-key constraint alone.

## History and idempotency

The model intentionally separates two concerns:

- `source_items` prevent duplicate logical identities for a source;
- `raw_captures` preserve repeated observations and revisions over time.

A later capture must not overwrite the earlier capture that established historical state. This is required for time-machine reconstruction.

## Migration contract

Alembic metadata is wired to the SQLAlchemy model metadata. CI validates migrations against PostgreSQL by:

1. upgrading an empty database to `head`;
2. downgrading the latest revision by one step;
3. upgrading back to `head`;
4. running the backend suite, including PostgreSQL integration tests.

Live Neon migration/smoke validation remains tracked under issue #2 and requires owner-provided credentials.


## Structured sports domain

### `seasons`, `teams`, `players`, and `games`

These tables hold stable internal identities, not provider IDs.

A game references one season plus distinct home/away team UUIDs. Mutable schedule/status/result state is intentionally not stored by overwriting the `games` row.

Season boundaries are calendar dates. Observation, availability, validity, tip, and final timestamps are timezone-aware instants.

### `sports_external_identities`

Maps one provider namespace and external ID to exactly one internal season, team, player, or game.

The database enforces:

- uniqueness of `(provider_key, entity_type, external_id)`;
- exactly one internal target column per mapping;
- agreement between `entity_type` and the populated target.

This lets #5 normalize multiple providers into stable internal identities without coupling core IDs to one provider.

### `game_observations`

Append-only snapshots of schedule/status/result state from a structured source.

Each observation carries:

- `observed_at`: when NBA Time Machine obtained/confirmed the state;
- `available_at`: when that state can conservatively be treated as publicly knowable;
- normalized game `status`;
- optional scheduled/actual tip and final timestamps;
- optional scores;
- source provenance.

A scheduled observation remains stored after a final observation arrives. This is the key persistence guarantee that prevents completed-game data from destroying the historical pregame world.

Outcome-bearing fields in this table are not authorization to display them. Spoiler policy must still choose a safe projection before any user or AI output.

### `temporal_facts`

Append-only structured facts for one season, team, player, or game.

Examples include standings records, player/team statistics, injury/availability state, or other provider-normalized facts. A fact carries:

- `fact_type` plus a JSONB `value`;
- exactly one typed subject;
- source provenance;
- `valid_from` and nullable `valid_to` for domain validity;
- `observed_at` for collection/provenance time;
- `available_at` for time-machine visibility.

The database rejects non-forward validity intervals. New versions are inserted instead of overwriting the older version.

## Structured-data history rules

For structured sports data:

- internal entity IDs are provider-neutral;
- provider identifiers are mappings, not primary keys;
- scheduled/pregame game observations remain queryable after later live/final observations;
- mutable standings/stats/availability facts keep validity history;
- source provenance and public-availability time remain explicit;
- deleting a referenced sports entity is restricted while identity mappings, observations, or facts still depend on it.
