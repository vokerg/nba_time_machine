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

## Desired-state sync (Issue #3)

`backend/scripts/sync_sources.py` validates `config/sources.seed.json` and
upserts seed-owned fields into PostgreSQL. See
[`docs/SOURCE_REGISTRY.md`](../SOURCE_REGISTRY.md) for its offline validation
command, sync semantics, and source-health query surface.

Runtime collection cursors and historical outcomes are not seeded. Missing
source IDs are retained, not implicitly deleted; disabling requires an
explicit `enabled: false` desired-state change. Verified and enabled are
separate flags. Source health is derived from actual collection outcomes, not
from desired-state flags.


## First RSS/Atom and web collector runtime (Issue #4)

`backend/src/nba_time_machine/ingestion/adapters.py` supports explicit
`rss`, `atom`, `rss_or_web`, and `web` adapters. RSS/Atom entries use GUID/Atom
ID when available, otherwise a canonical HTTP(S) item URL. A web source fetches
**one explicitly configured page only**; no link following, general crawling,
remote redirects, JavaScript, or paywall bypass. Tracking query parameters and
fragments are omitted from canonical URLs, but meaningful query keys remain.

The collector makes requests **only when a source is both enabled and verified**
and has no unresolved auth requirement. Existing seed entries remain disabled;
verification requires separate evidence from a bounded source smoke. The
single-response limit is 512 KB, the feed is capped at 50 entries, text at
20,000 characters, each HTTP attempt at 10 seconds, and retry count at three
for transport errors and 5xx responses (with bounded backoff). No redirects
are followed; non-public IP literals and localhost hosts are rejected.
Network access to unverified sources never starts. The eligibility guard is
enforced **both** by the collection orchestrator and by the lower-level
`collect_source` adapter, so direct/manual adapter calls cannot bypass
`enabled=true` and `verification_status=verified`.

The runtime also **rechecks the source's current authorization and capture
policy under a PostgreSQL row lock immediately before storing a fetch result**.
If a source was disabled/unverified, started requiring authentication, or its
locator, adapter, adapter settings or retention policy changed while the
request was in flight, the fetched captures are discarded. A
`skipped_config / source_policy_changed` outcome is persisted without
advancing the source's attempt cursor. This prevents a stale response from
being retained after an operator changes source access or retention rules.
It does not cancel a request already underway, detect a policy changed and
restored between checks, or substitute for network egress restrictions.

The URL guard also rejects trailing-dot localhost/internal hostnames and
numeric loopback aliases (including one-integer, octal, and hexadecimal
IPv4 spellings) that operating-system resolvers can interpret as private
addresses. These checks are **not** a complete DNS-rebinding defense:
DNS hostnames are not currently resolved and pinned to public IP addresses.
Production deployments must restrict collector network egress, and a source
must remain disabled until its access method and policy have been reviewed.

Run from `backend/` after `python scripts/sync_sources.py` and migrations:

```bash
python scripts/collect_sources.py --source-id VERIFIED_ID
python scripts/collect_sources.py --source-id VERIFIED_ID --force
```

With no explicit ID, the runtime considers enabled sources only. `--force`
bypasses cadence but never verification/auth requirements. PostgreSQL stores a
collection run and one outcome per attempted source, under bounded concurrency
(default 4, max 16). Non-due sources are excluded rather than generating
false skipped/idle outcomes. A failed adapter is recorded independently and
cannot roll back another source's transaction. Exceptions are reported through
non-content-bearing codes; persistence failures are surfaced in command output
and **not** falsely claimed as stored outcomes.

At the **persistence boundary**, the source's retention policy governs the
captured text: `full` stores text + raw payload, `normalized_full` text only,
`metadata_excerpt` a 280-character excerpt, and `metadata_only` neither.
Raw adapter metadata cannot bypass that boundary. Same-hash item captures
are not redundantly stored across runs, while changed hashes append a new
raw revision. First-discovered normalized item facts are not retroactively
overwritten by later edits. Publication timestamps are stored separately from
collection and defensible availability timestamps; availability defaults
conservatively to first system observation, **not** unverified backdated
publisher dates. These records are ingestion data, not spoiler-safe reads.

Fixture tests use a mocked HTTP transport; PostgreSQL integration tests cover
retention, replay, source isolation, cadence, and revision history. The command
is a bounded live smoke entry point but a live source/Neon smoke **has not been
performed**. Work outside this issue (authenticated social/podcasts/video,
production scheduling, and timeline-aware media API projection) remains separate.

## Podcast RSS episode metadata (Issue #11 — first adapter slice)

The reviewed RSS/Atom collector now accepts `adapter="podcast_rss"` **only**
with `kind="podcast"`. It fetches one explicitly configured HTTP(S) feed URL
through the existing bounded transport (10-second request timeout, at most
512 KB per response, no redirect following, limited retry behavior and 50
parsed entries). Unverified or disabled podcast definitions, and sources
requiring unavailable authentication, fail closed **before** any request.
The collector does not discover podcast feeds from webpages.

Episode metadata uses the same deterministic extraction and temporal contract
as other RSS items: stable feed GUID (or a public canonical episode permalink
when the GUID is missing), title, author, feed description and any parseable
`pubDate` / Atom publication timestamp. Duplicate GUIDs within a batch are
ignored. The publisher timestamp is not trusted as the item's first-known
time: new source items and raw revisions remain available no earlier than
their actual collection/discovery time. Empty or invalid feed payloads do
not silently become HTML page captures.

**No media fetch:** RSS `enclosure` links, podcast transcript/caption
locators and linked episode pages are never followed. This first slice does
not download audio/video, retrieve transcripts, store binaries, discover
episode redirects, validate rights, or extract transcript text. Feed XML
may contain media and transcript **URLs**, so retention policy is still
enforced at PostgreSQL persistence. Use `metadata_only` unless a separate
source-specific legal/access review explicitly approves further retention.
No collector output is automatically safe for spoiler-free display.

The existing `pod-no-dunks` and other podcast seed entries remain disabled
and unverified, with unresolved feed addresses where documented. A real feed
must be identity/access/terms-reviewed and pass a bounded operator smoke
before any source is enabled; this change makes no live-feed, subscription,
transcript-rights, production ingestion or Neon claim. Authenticated podcast
feeds, permitted transcript discovery/capture, X and video adapters remain
open under #11.

Regression checks:
`cd backend && pytest -q tests/test_podcast_rss_adapter.py`.
They use a mocked HTTP transport, not the actual podcast publisher.

## NBA season collection (#73)

See [NBA collection](../NBA_COLLECTION.md) for the bounded TheSportsDB entry
point, additive Neon writes, idempotent capture revisions and explicit coverage
reports. Historical backfill availability is actual observation time; it never
creates pre-tip knowledge. Full season/live/player-stat coverage is provider-gated.
