# Project Bible

## 1. Product

NBA Time Machine is for fans who intentionally watch NBA games after they happen, especially users in time zones where games run overnight.

The problem is larger than hiding a final score. A user can be spoiled by standings, player averages, headlines, social posts, thumbnails, "career high" labels, game duration, reordered recommendations, injury follow-ups or a suspiciously high game rating.

The product therefore reconstructs an **NBA world state** at a selected moment.

Example: on Monday morning a user can move the time machine to Sunday before games started. The app should then behave as though later information does not exist.

## 2. Core concepts

### Time cursor

The user has a selected information timestamp, for example Sunday 15:00 ET.

The app resumes at the user's last timeline position rather than automatically snapping to real-world now. The cursor is visible and user-controlled.

For MVP, the timeline is **forward-only** once established. A user can advance the NBA world, but moving the cursor backward to reconstruct an earlier world is deferred to a future "full time machine" mode. Advancing the timeline means the user has intentionally accepted everything that became knowable before the new cursor.

Content learned after the cursor is hidden by default.

### Sealed and acknowledged games

"Watched" is the wrong primitive. A user may watch a game, read the result, or simply decide they no longer care about being protected from it.

A game is therefore either **sealed** or **acknowledged**.

A sealed game protects result-dependent information. The user can acknowledge it explicitly by revealing the game. Advancing the timeline beyond older games also makes those games non-sensitive; the app should not continue protecting games that the user has deliberately moved past.

Acknowledging one game does **not** advance the global media timeline. It can expose that game's result, box score, game-linked stats and other game-specific downstream information while general news/social/podcast feeds remain constrained by the selected time cursor.

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

The user may have multiple favorite teams, but favorites are a separate product concern and never alter the canonical watchability ordering. A favorite-team game can be surfaced separately from the recommendation engine.

The engine may maintain a rich internal postgame score so it can distinguish two games that are both worth watching. The default UI should not expose that numeric score because the magnitude is itself a spoiler signal. A first disclosure layer should be coarse; exact wording and thresholds remain a product-tuning decision.

## 4. Layered game disclosure

Game information should open like layers rather than through one binary spoiler switch.

A sealed game can expose, independently:

1. **Pregame information** — matchup, rosters, injuries, availability, form, standings context and other information knowable before tip-off.
2. **Watchability verdict** — a deliberately coarse signal derived from the hidden postgame-quality model.
3. **Why** — only on explicit request, reveal increasingly specific reasons such as exceptional performance, comeback, chaos or high-level basketball.
4. **Full game reveal** — result, score, box score, recap, highlights and postgame information.

The game list should provide direct actions for watchability and full result reveal; entering a dedicated game page must not be required.

This layered model also supports historic-event hints. Some users want strict ignorance; others would rather accept a soft spoiler than miss a legendary game. The user controls how much of the onion is peeled.

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
- user time cursor, sealed/acknowledged game state, favorite teams and spoiler preferences;
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

- a balanced home dashboard combining games, media/buzz and "What should I watch?";
- Time Machine / Today;
- Games;
- "What should I watch?";
- Standings;
- News / Buzz;
- user spoiler controls;
- sealed/acknowledged game state;
- separate favorite-team surfaces, supporting multiple favorites.

The selected time cursor must be visible and difficult to confuse with real "now".

Game cards should support layered disclosure directly from the list: safe pregame context, a coarse watchability reveal, optional "why" detail, and full-game reveal.

General news, social/X and podcast surfaces remain **strictly timeline-based**. Revealing one game does not inject later media into those feeds.

The UI must avoid secondary spoiler channels such as postgame thumbnails, highlight counts, exact runtime, numeric postgame quality scores or outcome-dependent ordering unless policy permits them.

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

1. persistent, visible, forward-only time cursor;
2. historical schedule/standings/stats/injuries;
3. spoiler-safe game cards with safe pregame information;
4. sealed/acknowledged game state and explicit full-game reveal;
5. deterministic pregame ranking;
6. "what should I watch?" using hidden comparative quality scores and optional time-budget optimization;
7. layered postgame watchability disclosure without exposing numeric scores by default;
8. news, social/X and podcast feeds constrained strictly by the selected timeline;
9. multiple favorite teams surfaced separately from canonical watchability ranking.

Backward time travel/full historical replay is intentionally deferred beyond MVP.

Social breadth, advanced personalization, large-scale transcript processing and cross-sport support can come later.

## 15. Multi-sport direction

The architecture should not assume NBA-specific semantics below the sports-domain layer.

The general abstraction is a sports information time machine. Soccer, NFL, F1 and tennis have different entities and scoring logic, but the temporal provenance, spoiler policy, ingestion and recommendation boundaries are reusable.
