# Agent entry points

Choose the smallest path that matches the GitHub Issue.

Start with `docs/IMPLEMENTATION_PHASES.md` when an issue's place in the dependency graph is unclear.

## Product or spoiler behavior

Read:

1. `docs/PROJECT_BIBLE.md`
2. `docs/architecture/01-temporal-and-spoiler-model.md`
3. relevant backend/frontend modules

Expected tests: policy fixtures around pregame/in-game/postgame leakage, timeline advancement, explicit acknowledgement and layered disclosure.

## Collection/source work

Read:

1. `docs/architecture/02-ingestion.md`
2. `config/sources.seed.json`
3. ingestion code and source-specific tests

A source is not "working" until a bounded smoke test has demonstrated the configured access method. Record auth/rate-limit restrictions rather than hiding them.

## AI work

Read:

1. `docs/architecture/03-ai.md`
2. spoiler policy docs
3. the AI configuration/client modules once implemented

Never construct AI context directly from unrestricted raw captures.

## Database work

Read:

1. `docs/PROJECT_BIBLE.md` sections 5, 8 and 9
2. all architecture docs that define timestamp/provenance semantics

Use migrations. Do not silently mutate historical records to current state.

## Frontend work

Read:

1. product bible sections 1-4 and 11
2. temporal/spoiler architecture
3. API contracts for the issue

The visible time cursor and spoiler state are part of correctness, not decoration. Do not model "watched" as the core state; use sealed/acknowledged semantics and layered reveal contracts.

## Ranking work

Keep pregame and postgame models separate. A postgame quality score is itself a spoiler signal.

## Documentation changes

If implementation changes a durable contract, update the nearest architecture document and, when it changes the product model, `docs/PROJECT_BIBLE.md`.
