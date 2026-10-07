# Architecture: ingestion

## Pattern inherited from war_reporter

The useful pattern is:

- one canonical registry;
- platform-specific adapters;
- parallel collection;
- per-source cadence;
- isolated failures;
- raw-first capture;
- explicit source/run health;
- deterministic downstream processing.

NBA Time Machine keeps that shape.

## Registry

The runtime registry will eventually live in Postgres. The repository keeps a reviewed seed/desired-state file at `config/sources.seed.json`.

Why both?

- source changes remain reviewable in Git;
- agents have a deterministic configuration entry point;
- runtime health/cursors belong in the database;
- DB bootstrap/sync can be idempotent.

A source definition includes:

- stable ID and display name;
- source kind/platform;
- access URL/handle/feed identifier;
- adapter;
- category and optional team/player scope;
- cadence;
- auth requirement;
- retention policy;
- verification status;
- enabled state;
- adapter-specific settings.

## Adapter families

Planned:

- NBA/structured sports API;
- RSS/Atom;
- generic web/article;
- X account/search;
- podcast RSS;
- YouTube/video metadata/transcript;
- manually curated or API-specific providers.

Do not make one universal scraper.

## Capture layers

### Raw capture

Represents one concrete response/item as obtained from a source.

Keep:

- source ID;
- external item ID;
- canonical URL;
- publication/discovery/capture timestamps;
- content type;
- raw/normalized content according to retention policy;
- content hash;
- source-specific metadata;
- collection run ID.

### Normalized source item

Stable logical content identity across repeated captures/edits.

Keep:

- canonical identity;
- latest/selected text;
- revision links;
- author;
- entity links;
- topic/spoiler classification;
- temporal availability.

Repeated collection should not create duplicate logical items.

## Full-content retention

Retention is source policy, not an adapter shortcut.

Allowed values:

- `full`;
- `normalized_full`;
- `metadata_excerpt`;
- `metadata_only`.

The collector must not persist more than the source policy allows.

For podcasts, storing episode metadata and a permitted transcript is usually more useful than storing large audio binaries. Audio archival is out of MVP scope.

## Source health

Each collection run records per-source outcome:

- ok;
- idle/no new items;
- skipped_config;
- rate_limited;
- auth_error;
- blocked;
- parse_error;
- network_error;
- partial.

The system must expose configured/attempted/succeeded/failed/skipped counts separately.

## Initial source seed

The seed file in this PR is a **research backlog**, not a claim that every listed source has a stable legal/technical collector. Entries begin disabled/unverified until an issue verifies access, identifiers, retention and smoke behavior.
