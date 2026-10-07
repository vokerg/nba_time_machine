# NBA Time Machine

A spoiler-controlled NBA information environment for people who watch games later.

NBA Time Machine reconstructs what the league looked like at a selected moment: schedule, standings, stats, injuries, news, media and buzz are filtered by when they became knowable and by which games the user has already watched.

## Product principle

This is not a score-hiding app. The invariant is **information-time consistency**.

A user frozen at Sunday 15:00 ET must not receive information learned after that point unless an explicit spoiler policy allows it. Game results, updated standings, postgame headlines, thumbnails, runtime clues, rankings and AI summaries can all leak outcomes.

## Stack

- Frontend: React + TypeScript + Vite.
- Backend: Python + FastAPI.
- Database: PostgreSQL on Neon (to be provisioned later).
- AI: DeepSeek through an OpenAI-compatible JSON boundary.
- Development: issue-driven, agent-friendly GitHub workflow.

## Architecture

```text
source registry
      ↓
parallel collectors (NBA data / web / RSS / X / podcasts / video)
      ↓
raw capture + normalized source items
      ↓
temporal enrichment (published_at / available_at / captured_at)
      ↓
PostgreSQL / Neon
      ↓
spoiler-policy firewall
      ↓
ranking + AI synthesis
      ↓
FastAPI
      ↓
React
```

The ingestion model deliberately borrows the raw-first, per-source-isolation pattern from `war_reporter`. Unlike that public repository, this product needs durable historical reconstruction, so full captured content may be retained privately when the source's access method and terms permit it.

## Start here

Humans and agents should read, in order:

1. `docs/PROJECT_BIBLE.md`
2. `docs/architecture/00-overview.md`
3. `docs/architecture/01-temporal-and-spoiler-model.md`
4. `docs/architecture/02-ingestion.md`
5. `docs/architecture/03-ai.md`
6. `AGENTS.md`
7. `docs/AGENT_ENTRYPOINTS.md`

## Local skeleton

Backend:

```bash
cd backend
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
uvicorn nba_time_machine.main:app --reload
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

The initial scaffold intentionally does not connect to Neon, collect live sources, or call DeepSeek. Those are separate GitHub Issues so agents can implement and review them independently.
