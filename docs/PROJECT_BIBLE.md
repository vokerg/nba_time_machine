# Project Bible

## 1. Product

NBA Time Machine is for fans who intentionally watch NBA games after they happen, especially users in time zones where games run overnight.

The problem is larger than hiding a final score. A user can be spoiled by standings, player averages, headlines, social posts, thumbnails, "career high" labels, game duration, reordered recommendations, injury follow-ups or a suspiciously high game rating.

The product therefore reconstructs an **NBA world state** at a selected moment.

Example: on Monday morning a user can move the time machine to Sunday before games started. The app should then behave as though later information does not exist.

## 2. Core concepts

### Time cursor

The user has a selected information timestamp, for example Sunday 15:00 ET.

Content learned after the cursor is hidden by default.

### Watched state

Time alone is insufficient. A user may watch one Sunday game while keeping the rest sealed.

The system tracks watched/unwatched games. Consequences of a watched game may be revealed while consequences of unwatched games remain hidden.

### Spoiler policy

The product supports progressively less strict modes.

- **Time Machine / Strict**: only information safe at the cursor and for watched games.
- **Guide**: adds spoiler-safe pregame recommendation scores.
- **Hints**: may expose bounded postgame signals, explicitly warning that the signal itself can be a spoiler.
- **Full**: results, postgame stats, news and rankings are visible.

Exact UX names may change; the separation must remain.

## 3. Game recommendation model

There are two different scores.

### Pregame Interest

This must be computable entirely from information available before tip-off.

Candidate inputs:

- team strength;
- expected closeness;
- standings leverage;
- star availability;
- recent form;
- rivalry/history;
- rest/travel;
- playoff implications;
- expected lineup quality.

This score is safe in strict spoiler-free mode.

### Postgame Watchability

This uses events from the completed game and is therefore spoiler-bearing.

Candidate inputs:

- clutch minutes;
- lead changes;
- comeback size;
- overtime;
- exceptional individual performance;
- unusual tactical quality;
- historical rarity;
- stakes and consequence.

A jump from a low pregame score to a 9.8 postgame score already tells the user that something unusual happened. Therefore this score is opt-in.

### Canonical recommendation promise

"What should I watch?" means **watchability, not fandom**.

Favorite teams may be a separate filter or subscription, but they do not alter the canonical game-quality ordering.

## 4. Historic-event hints

Some users want strict ignorance. Others would rather accept a soft spoiler than miss a legendary game.

The system can eventually support graduated hints such as:

- "There is one game from last night you probably should not skip."
- "One game contains an exceptional individual performance."
- "MIA-ORL contains an exceptional individual performance."
- full reveal.

The user chooses the leakage level.

## 5. Temporal truth model

Every externally sourced item must preserve when it became knowable.

Important timestamps:

- `published_at`: publisher/platform timestamp when available;
- `discovered_at`: first time our system observed the item;
- `captured_at`: time a concrete payload/content snapshot was stored;
- `available_at`: earliest defensible time the information was publicly knowable;
- `valid_from` / `valid_to`: applicability window for structured facts such as injury status;
- game timestamps such as scheduled tip, actual tip and final state.

We must never silently replace historical state with current state.

## 6. Ingestion philosophy

Borrow the successful shape from `war_reporter`:

```text
registry → parallel adapters → isolated source outcomes → raw-first storage → deterministic downstream layers
```

Differences from War Reporter:

- this is not a public OSINT archive;
- historical replay requires durable raw/near-raw capture;
- content may be stored privately in Neon when permitted;
- spoiler classification and temporal availability are first-class product fields;
- sports structured data joins media content around games, teams and players.

## 7. Source universe

We expect a large canonical source registry containing:

- official NBA and team sources;
- structured league/game/stat providers;
- national sports media;
- beat reporters;
- analysts;
- X accounts;
- RSS feeds;
- podcasts and podcast RSS;
- YouTube/video channels;
- newsletters and blogs;
- injury/transaction sources.

The repository contains a version-controlled seed/desired-state list. Neon becomes the runtime registry and health store once provisioned.

Every source has an adapter type, cadence, auth policy, retention policy, verification status and health state.

## 8. Full-content capture

The desired product benefits from retaining the whole useful item: tweet/post text, article body when allowed, podcast metadata/transcript when available, and original normalized payload.

However, "we can technically fetch it" is not the same as "we may durably store it."

Each source must declare a retention policy:

- `full`: full private capture permitted;
- `normalized_full`: full normalized text permitted, raw response not retained;
- `metadata_excerpt`: metadata plus bounded excerpt only;
- `metadata_only`: no body retention.

Collectors must obey this policy. Terms, robots/rate limits, API licenses and publisher restrictions are part of source configuration.

For MVP, PostgreSQL can hold text/payloads. If volume becomes inefficient, raw blobs can move to object storage while Postgres keeps immutable metadata and hashes.

## 9. Database direction

Target: PostgreSQL on Neon.

Major domains expected:

- source registry and source health;
- collection runs and per-source outcomes;
- raw captures and normalized source items;
- teams, players, games and seasons;
- structured fact history (injuries, standings, stats, transactions);
- item-to-game/team/player links;
- spoiler classification;
- recommendation score versions;
- user time cursor, watched games and spoiler preferences;
- AI jobs/results with prompt/schema/model version metadata.

Schema work is intentionally a separate issue after the Neon project is created.

## 10. AI role

DeepSeek will power interpretation and synthesis through the same general pattern used in the chess repertoire project:

```text
LLM_PROVIDER=openai-compatible
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=<configured model>
LLM_API_KEY=<secret>
```

Good AI jobs:

- classify article/post topic and entities;
- classify spoiler content;
- normalize league buzz;
- create spoiler-safe summaries from already-safe inputs;
- map natural-language "what should I watch?" queries into deterministic filters;
- extract structured facts that are later validated/reconciled;
- summarize podcasts/transcripts where rights and retention policy permit.

AI is **not** the spoiler firewall. The policy engine decides which records/fields may enter AI context.

## 11. Frontend

React web app first.

Initial product surfaces:

- Time Machine / Today;
- Games;
- "What should I watch?";
- Standings;
- News / Buzz;
- user spoiler controls;
- watched-game state.

The selected time cursor must be visible and difficult to confuse with real "now".

The UI must avoid secondary spoiler channels such as postgame thumbnails, highlight counts and exact runtime unless policy permits them.

## 12. Backend

Python + FastAPI.

Major modules should remain separated:

- `ingestion`: registry, adapters, collection orchestration;
- `sports`: structured NBA domain ingest/normalization;
- `temporal`: historical state and availability semantics;
- `spoilers`: policy evaluation and safe projections;
- `ranking`: pregame and postgame models;
- `ai`: DeepSeek-compatible client, schemas and AI use cases;
- `api`: application routes;
- `db`: Neon/Postgres models/repositories/migrations.

## 13. Development model

Development is performed by agents through GitHub Issues.

Issues are small contracts with:

- context and desired behavior;
- required reading;
- dependencies;
- allowed/expected paths;
- acceptance criteria;
- tests/validation;
- explicit out-of-scope items.

Architecture changes update this bible or an architecture document in the same PR.

## 14. MVP boundary

The first useful MVP should provide:

1. selectable time cursor;
2. historical schedule/standings/stats/injuries;
3. spoiler-safe game cards;
4. deterministic pregame ranking;
5. "what should I watch?";
6. watched-game tracking;
7. news/media constrained by time and watched state;
8. explicit optional postgame-quality signal.

Social breadth, advanced personalization, large-scale transcript processing and cross-sport support can come later.

## 15. Multi-sport direction

The architecture should not assume NBA-specific semantics below the sports-domain layer.

The general abstraction is a sports information time machine. Soccer, NFL, F1 and tennis have different entities and scoring logic, but the temporal provenance, spoiler policy, ingestion and recommendation boundaries are reusable.
