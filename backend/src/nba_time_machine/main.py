from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI

from nba_time_machine.api import game_disclosure_router, timeline_router
from nba_time_machine.db import (
    DatabaseSettings,
    create_database_engine,
    create_session_factory,
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = DatabaseSettings()
    engine = None
    app.state.session_factory = None

    if settings.is_configured:
        engine = create_database_engine(settings)
        app.state.session_factory = create_session_factory(engine)

    try:
        yield
    finally:
        if engine is not None:
            await engine.dispose()


app = FastAPI(
    title="NBA Time Machine API",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(timeline_router)
app.include_router(game_disclosure_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/meta")
def meta() -> dict[str, str]:
    return {
        "product": "NBA Time Machine",
        "spoiler_policy": "deterministic-firewall",
        "database": "neon-postgres-not-configured",
    }
