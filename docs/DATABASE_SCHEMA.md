# Database schema

This document describes the persistence model introduced by issue #18. It covers the source registry, collection provenance, raw capture history, and normalized source-item identity. Collector behavior, registry synchronization, retention enforcement, and live Neon validation remain separate work.

## Relationships

```text
sources
  ├──< source_items
  │       └──< raw_captures
  ├──< source_outcomes >── collection_runs
  └──< raw_captures   >── collection_runs
```

A raw capture may link to one normalized `source_item`. The link is nullable because capture can precede normalization.

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
