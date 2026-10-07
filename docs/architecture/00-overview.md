# Architecture: overview

## System shape

```text
version-controlled source seed
          ↓
runtime source registry (Postgres)
          ↓
collection scheduler
          ↓
adapter workers ───────────────┐
          ↓                    │
raw captures                   │ per-source health/outcome
          ↓                    │
normalization + entity links ──┘
          ↓
temporal facts / availability
          ↓
spoiler policy engine
          ↓
safe projection
     ↙           ↘
ranking         AI use cases
     ↘           ↙
         FastAPI
            ↓
         React UI
```

## Boundary rules

### Collection boundary

Collectors answer: "what did this configured source return?"

They do not answer: "is this true?" or "may the user see this?"

### Normalization boundary

Normalization creates stable identities, canonical URLs, hashes, timestamps and entity links while retaining provenance.

### Temporal boundary

The temporal layer determines when an item/fact became available and, for mutable facts, when it was valid.

### Spoiler boundary

The spoiler policy engine is deterministic and fail-closed. Unsafe records/fields are excluded before ranking explanations and AI prompts.

### AI boundary

AI enriches and summarizes allowed context. Model output is schema validated and carries model/prompt/schema version metadata.

## Technology

- FastAPI Python service.
- React/TypeScript/Vite frontend.
- PostgreSQL on Neon.
- Scheduled/background ingestion workers (deployment mechanism TBD).
- DeepSeek via OpenAI-compatible HTTP API.

We will prefer boring explicit modules and relational history over premature microservices.
