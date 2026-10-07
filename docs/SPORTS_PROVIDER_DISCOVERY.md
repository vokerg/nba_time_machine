# Structured NBA provider discovery

Issue: #5

Last verified: 2026-10-07.

## Decision

Use **TheSportsDB v1** as the first structured provider integration.

This is a deliberately narrow first provider, not a claim that TheSportsDB is sufficient for every NBA Time Machine data family. The reasons for choosing it first are:

- a documented REST API rather than an undocumented website-internal feed;
- a documented public development key (`123`) that allows bounded live verification without owner secrets;
- explicit API reuse terms;
- stable league/team/player/event identifiers;
- schedule/event, team/player, event-stat and player-stat endpoints;
- a documented 30 requests/minute free-tier rate limit;
- a paid path for broader/full-result limits if this provider remains useful.

The first adapter will normalize schedule/game state and stable team/event identities into the provider-neutral sports persistence layer. Event/player statistics are kept as a supported follow-on surface for temporal facts.

## Provider survey

### NBA-operated feeds / NBA.com

Pros:

- first-party schedule and statistics source;
- canonical NBA terminology and coverage.

Constraints:

- public web/CDN endpoints are not documented as a supported developer API;
- current NBA API-hub terms materially restrict building or redistributing comprehensive, regularly updated NBA-statistics databases without consent;
- automated access can be protected or blocked.

Decision: do not make an undocumented NBA.com feed the initial application contract.

References:

- https://api-hub.nba.com/termsofuse
- https://www.nba.com/schedule

### ESPN website JSON feeds

Pros:

- no API key required for the commonly discovered scoreboard/standings JSON endpoints;
- broad schedule, game, team and standings data is observable.

Constraints:

- the endpoints used by community integrations are undocumented/private website interfaces;
- no published compatibility/SLA or rate-limit contract for those interfaces;
- production/feed access historically has a separate developer/feed process.

Decision: useful as a discovery/reference source, but too unstable as the first durable adapter contract.

### BALLDONTLIE

Pros:

- documented NBA API and OpenAPI schema;
- historical data advertised from 1946-current;
- teams, games, standings, player injuries and statistics are documented;
- lifecycle-oriented `status_state` is a particularly good fit for NBA Time Machine.

Constraints:

- every request requires an account/API key;
- free tier is rate-limited and endpoint access varies by tier;
- there is no repository/owner key available for a live smoke in this issue.

Current public account-plan documentation lists NBA free at 5 req/min, paid at 60 req/min, and paid-plus at 600 req/min. The API documentation also describes trial/GOAT tier behavior; code must therefore treat limits as provider/account configuration rather than a hard-coded invariant.

Decision: strong candidate for a later/alternate provider once credentials are available, but not the first adapter because #5 requires bounded live evidence.

References:

- https://docs.balldontlie.io/
- https://www.balldontlie.io/account/

### TheSportsDB

Pros:

- documented v1 API with public development key `123`;
- documented 30 requests/minute free tier;
- stable IDs for leagues, teams, players and events;
- past/present/future schedule endpoints;
- event and player statistic endpoints;
- terms explicitly allow copying/modifying content returned by official API endpoints, subject to third-party rights and publication/subscription conditions.

Constraints:

- v1 free responses have endpoint-specific result limits; notably a full season schedule is limited to 15 rows on the free key;
- the league-table endpoint is documented as limited to featured soccer leagues, so NBA standings are a coverage gap;
- v2, larger result limits and two-minute live scores require premium;
- free API use is intended for development; publishing an app requires a paid subscription;
- images/logos/artwork have separate licensing/trademark requirements and are therefore out of scope for this adapter.

Decision: selected for the first verified adapter. Production-scale backfills will require either a premium TheSportsDB key or a second provider.

References:

- https://www.thesportsdb.com/docs_api_guide
- https://www.thesportsdb.com/docs_pricing
- https://www.thesportsdb.com/docs_terms_of_use.php

## NBA mapping

TheSportsDB identifies the NBA league as `4387`.

The adapter maps:

- TheSportsDB team ID -> `TeamRecord` + `SportsExternalIdentityRecord(provider_key="thesportsdb", entity_type="team")`;
- TheSportsDB event ID -> `GameRecord` + matching external identity;
- each provider observation -> a new `GameObservationRecord`;
- future structured statistics -> `TemporalFactRecord` snapshots with provider/source provenance.

Provider IDs never become NBA Time Machine primary keys.

## Temporal rules

The adapter must never update a previous game observation to inject a later result.

For every fetch:

- `observed_at` is the time the response was obtained;
- `available_at` initially equals `observed_at` unless the provider exposes an earlier trustworthy publication timestamp;
- schedule/status/score fields are normalized into a new observation;
- a later final observation coexists with the earlier scheduled observation.

This is storage history only. Outcome-bearing fields still require spoiler-safe projection before user or AI output.

## Coverage gaps

The first slice does **not** claim:

- NBA standings from TheSportsDB (the documented v1 table endpoint is soccer-only);
- full-season production backfill using the public free key;
- authoritative injury/availability history;
- real-time SLA;
- permission to redistribute NBA marks, logos, player photos or other third-party artwork;
- a single-provider solution for every Phase 2 fact family.

Those gaps are intentionally explicit so a second structured provider can be added without changing internal IDs or temporal contracts.
