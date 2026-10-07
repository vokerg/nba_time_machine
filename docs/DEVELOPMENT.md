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

Copy `.env.example` to a local untracked file when implementation starts.

Neon is intentionally not configured in the foundation PR.

## Backend

```bash
cd backend
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
pytest
uvicorn nba_time_machine.main:app --reload
```

## Frontend

```bash
cd frontend
npm install
npm run build
npm run dev
```

## Issue-driven delivery

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
