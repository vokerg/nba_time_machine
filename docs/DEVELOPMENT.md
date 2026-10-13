# Development

## Repository shape

```text
backend/                     FastAPI application
frontend/                    React application
config/                      version-controlled desired-state configuration
docs/                        product and architecture contracts
.github/ISSUE_TEMPLATE/      agent task contract
AGENTS.md                    agent operating rules
```

## Environment

Copy `.env.example` to `.env` at the repository root and fill in local credentials. Backend settings read `.env` relative to the command's working directory. On macOS/Linux, link the root file into `backend/` so Uvicorn, Alembic and backend scripts all use the same configuration:

```bash
cp .env.example .env  # Only when .env does not already exist.
chmod 600 .env
cd backend
ln -s ../.env .env  # Only when backend/.env does not already exist.
```

Both files are ignored by Git. Keep database credentials on the backend; do not put them in frontend environment variables.

## Backend

```bash
cd backend
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
pytest
uvicorn nba_time_machine.main:app --reload
```

The API can start without PostgreSQL configured. With `DATABASE_URL` configured, startup creates a lazy connection pool; database-backed requests open connections as needed.

## Local PostgreSQL and migrations

Tests that exercise persistence use real PostgreSQL semantics; SQLite is not a substitute.

A minimal local database can be started with Docker:

```bash
docker run --rm --name nba-time-machine-postgres \
  -e POSTGRES_DB=nba_time_machine_test \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=postgres \
  -p 5432:5432 \
  postgres:17
```

In another shell:

```bash
export DATABASE_URL=postgresql://postgres:postgres@localhost:5432/nba_time_machine_test
export DIRECT_DATABASE_URL=$DATABASE_URL

cd backend
alembic upgrade head
# Optional rollback smoke for the latest revision:
alembic downgrade -1
alembic upgrade head
alembic check
pytest -q
```

`DATABASE_URL` is the application connection. `DIRECT_DATABASE_URL` is preferred for migrations/admin operations and may point at a non-pooled Neon endpoint. If `DIRECT_DATABASE_URL` is absent, migrations fall back to `DATABASE_URL`.

CI starts PostgreSQL, applies all Alembic migrations from an empty database, rolls the latest revision back and forward again, verifies SQLAlchemy metadata with `alembic check`, then runs the backend test suite including PostgreSQL integration coverage.

See `docs/DATABASE_SCHEMA.md` for the current source/collection/capture persistence model.

## Neon setup

In the Neon console, select the intended project, branch, database and role. Copy the connection string with pooling enabled into `DATABASE_URL` in the local `.env`. Copy the same connection with pooling disabled into `DIRECT_DATABASE_URL`. Retain the console's TLS parameters (`sslmode=require` and `channel_binding=require`); the backend accepts standard `postgresql://` URLs.

With backend dependencies installed, run from `backend/`:

```bash
.venv/bin/alembic current
.venv/bin/alembic upgrade head
.venv/bin/alembic check
.venv/bin/python scripts/sync_sources.py
```

Inspect the target before migrating an existing database. Source synchronization loads the reviewed registry without launching collectors; configured sources are not evidence of working collection. Repeating the sync is idempotent.

On October 13, 2026, issue #71 validated the owner's Neon database: the existing `0006_recommendation_scores` revision was upgraded to `0008_source_item_entity_links`, `alembic check` reported no differences, and 70 source definitions were synchronized (a second sync changed zero rows). The pooled application connection passed timeline initialize/read/advance/backward-rejection checks in a rolled-back transaction, and the backend's database-backed HTTP timeline lookup returned the expected response. Client TLS was active.

The frontend still uses synthetic demonstration fixtures. Database setup does not connect those screens or ingest historical NBA data. Run destructive migration rollback checks and integration tests against a separate disposable PostgreSQL database, as in the local test workflow above, rather than the owner's Neon database.

## Frontend

```bash
cd frontend
npm install
npm run build
npm run dev
```

## Agent factory behavior

GitHub is the durable coordination plane. A new coding agent receiving only `Go` should not need the previous chat.

Selection order:

1. recover/finish an existing unfinished PR after reviewing its issue, diff, reviews and CI;
2. otherwise choose the next unblocked issue from `docs/IMPLEMENTATION_PHASES.md`;
3. if blocked by an external dependency, record the blocker and continue with the next independent executable task.

Substantial work must not exist only in local state. Push coherent checkpoints and open a draft PR early enough that another engine can resume the work.

The detailed protocol is in `AGENTS.md`.

## Issue-driven delivery

Read `docs/IMPLEMENTATION_PHASES.md` before seeding or selecting larger work. It defines dependency order and phase exit criteria.

Use the `Agent task` GitHub Issue template.

An issue should be implementable without the agent inventing missing product decisions. If a decision is genuinely unresolved, create a discovery/architecture issue first.

PRs should include:

- issue reference;
- summary of changed contract/behavior;
- validation actually run;
- screenshots only when UI behavior changed;
- known gaps;
- migration/rollback notes when applicable.

## Secrets

Never commit real Neon credentials, X/API tokens or DeepSeek keys.
