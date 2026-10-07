# Implementation phases

This document is the delivery map for NBA Time Machine. It is intentionally higher-level than GitHub Issues: phases define dependency order and exit conditions; issues are the bounded implementation contracts.

The order is biased toward technical correctness first. Product breadth should not outrun temporal provenance or spoiler safety.

## Phase 0 — Foundation and contracts

**Goal:** establish the repository, product language and agent workflow.

Current foundation PR:
- #1 project bible, architecture, source seed, backend/frontend shells and CI

Exit:
- product vocabulary is explicit
- agent entry points exist
- backend/frontend build
- CI is green

## Phase 1 — Database and runtime substrate

**Goal:** make persistence and backend evolution safe before building features on top.

Issues:
- #2 database-domain tracking / Neon integration
- #12 PostgreSQL migration and integration-test harness
- #6 provider-neutral DeepSeek client can proceed independently because it is unit-testable without live credentials

Recommended order:
1. #12 local/CI PostgreSQL + Alembic foundation
2. first domain migrations under #2
3. connect and smoke-test Neon when owner credentials are available

Exit:
- migrations apply from empty PostgreSQL
- integration tests exercise PostgreSQL semantics
- config/secrets boundaries are stable
- Neon can be connected without changing domain design

## Phase 2 — Structured NBA backbone

**Goal:** establish trustworthy game/team/player identities and temporal sports facts.

Issues:
- #5 first structured NBA provider
- database portions of #2 needed for teams, players, games, seasons and temporal facts

Expected outputs:
- stable game IDs
- schedule/tip/status
- teams/players
- standings/stat snapshots
- injury/availability history where the selected provider supports it
- provenance and observation timestamps

Exit:
- a known historical slate can be reconstructed from structured data
- completed data never overwrites pregame historical state

## Phase 3 — Time and spoiler kernel

**Goal:** make the core product rules executable before exposing real data to the UI.

Issues:
- #13 persistent forward-only timeline state
- #7 deterministic timeline/disclosure policy engine
- #14 game acknowledgement and layered disclosure service
- #15 spoiler-safe game/media read models

Recommended order:
1. #13 timeline service
2. #7 pure policy engine in parallel with/after timeline contracts
3. #15 safe projection schemas
4. #14 application service tying timeline + policy + game state together

Exit:
- backward movement is rejected in MVP
- sealed/acknowledged semantics replace watched/unwatched
- pregame/watchability/reason/full projections are distinct
- general media remains timeline-only
- unsafe fields are absent from safe API models

## Phase 4 — First usable product loop

**Goal:** let a user actually live in the delayed NBA world.

Issues:
- #8 timeline dashboard and layered game disclosure
- API endpoint issues should be seeded from #13–#15 once their contracts stabilize

First usable loop:
1. app resumes at last timeline position
2. user sees spoiler-safe slate and pregame context
3. user can reveal watchability or full game directly from the list
4. user can advance timeline
5. general media stays consistent with that timeline

Exit:
- one end-to-end historical day works with real structured data
- no manual database manipulation is needed
- regression tests cover obvious indirect spoiler channels

## Phase 5 — Ranking and “What should I watch?”

**Goal:** answer the central viewing question without turning the answer into a spoiler.

Issues:
- #10 separate pregame-interest and postgame-watchability models

Expected behavior:
- favorite teams are separate and may be multiple
- canonical ranking never uses fandom
- internal postgame scores can be rich/continuous
- default disclosure is coarse
- “What should I watch?” can rank candidates and optimize against available viewing time without displaying the hidden score

Exit:
- recommendation decisions are reproducible and explainable
- coarse verdict / reason / full reveal layers are all policy-gated
- real historical games can be used to tune weights

## Phase 6 — Media ingestion and historical information world

**Goal:** reconstruct the surrounding NBA information ecosystem, not just structured results.

Issues:
- #3 source registry sync and health
- #4 RSS/web collector runtime
- #9 source-universe verification/expansion
- #11 X/podcast/video adapters

Recommended order:
1. #3 registry persistence
2. #9 verification can run in parallel
3. #4 RSS/web runtime
4. #11 authenticated/social/audio-video families

Exit:
- media can be queried as-of the selected timeline
- source failures are observable and isolated
- retention rules are enforced at persistence time
- publication/availability/capture timestamps remain distinct

## Phase 7 — AI-assisted interpretation

**Goal:** use DeepSeek where it improves synthesis, never as the security/spoiler boundary.

Starts with:
- #6 OpenAI-compatible DeepSeek client

Seed later issues for:
- entity/topic classification
- spoiler-tagging assistance
- media clustering/buzz
- structured extraction
- spoiler-safe summaries built only from already-safe projections
- natural-language parsing for recommendation requests

Exit:
- every AI job has a typed schema, bounded retries and safe logging
- prompts are constructed only from spoiler-cleared inputs
- model output is advisory/derived, never the source of temporal authorization

## Phase 8 — Hardening and expansion

Seed only after the core loop is useful.

Likely tracks:
- authentication/accounts
- deployment and operational monitoring
- data backfills and retention/object storage
- performance/caching
- source-quality scoring
- recommendation calibration tooling
- richer favorite-team surfaces
- backward/full historical replay
- multi-sport extraction from NBA-specific domain logic

## Issue-seeding rule

Do not create every future issue up front.

Create the next issue when:
- its upstream contract is stable enough to avoid guessing;
- it has one primary outcome;
- acceptance criteria can be tested;
- unresolved product language is not being smuggled into implementation.

When a phase is nearing completion, seed the next phase's first 2–4 issues and update this document if the dependency graph changed.
