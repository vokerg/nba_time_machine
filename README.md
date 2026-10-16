# NBA Time Machine

A spoiler-controlled NBA information environment for people who watch games later.

NBA Time Machine reconstructs what the league looked like at a selected moment: schedule, standings, stats, injuries, news, media and buzz are filtered by when they became knowable and by which games the user has already watched.

## Product principle

This is not a score-hiding app. The invariant is **information-time consistency**.

A user frozen at Sunday 15:00 ET must not receive information learned after that point unless an explicit spoiler policy allows it. Game results, updated standings, postgame headlines, thumbnails, runtime clues, rankings and AI summaries can all leak outcomes.

## Stack

- Frontend: React + TypeScript + Vite.
- Backend: Python + FastAPI.
- Database: PostgreSQL on Neon.
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

1. `docs/PROJECT_BIBLE.md`, `docs/IMPLEMENTATION_PHASES.md`, and `docs/AGENT_FACTORY.md`
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

After installing both sets of dependencies above, start both servers from the repository root:

```bash
./dev.py
```

The launcher requires Python 3 and Node.js/npm on macOS or Linux. It automatically uses `backend/.venv/bin/python` when present, otherwise the Python running the launcher. Both servers' logs appear in the same terminal. Open the frontend URL printed by Vite (normally <http://localhost:5173>); the backend runs at <http://127.0.0.1:8000>. Press Ctrl+C to stop both servers. If either server exits, the launcher stops the other one and its child processes too.

For database connection configuration, migrations and source-registry bootstrap, see [Development](docs/DEVELOPMENT.md#neon-setup). The frontend connects to profile-scoped backend data through a same-origin proxy. See [Frontend integration](docs/FRONTEND_INTEGRATION.md) for initialization, season browsing and historical coverage; ingestion is a separate operation.

For daily ESPN game evidence with CBS backup, see [Morning NBA collection](docs/NBA_MORNING_COLLECTION.md). The CLI defaults to read-only diagnostics; explicit write mode uses the existing PostgreSQL capture and temporal records. The separate [ranking processor](docs/MORNING_RANKING_PIPELINE.md) derives traceable features and hidden watchability ratings from complete stored trajectories.


For local rating inspection and tuning against your configured database, run
`backend/.venv/bin/python backend/scripts/run_scoring_workbench.py` and open
<http://127.0.0.1:8765>. This separate developer tool uses read-only previews and explicit day collection. It exposes full score
breakdowns and evidence; see [Scoring workbench](docs/SCORING_WORKBENCH.md).

For separate local read-only ingestion health and Eastern-day game evidence, run
`backend/.venv/bin/python backend/scripts/run_operator_dashboard.py` and open
<http://127.0.0.1:8766>. See [Operator dashboard](docs/OPERATOR_DASHBOARD.md).

## Agent entry

When a coding agent is told only **`Go`**, it must follow the recovery-first factory protocol in `AGENTS.md`: finish/recover unfinished PR work first, otherwise select the next unblocked issue, and leave all partial work resumable from GitHub-visible state.
