from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI

from nba_time_machine.api import (
    game_disclosure_router, game_list_router, media_feed_router, recommendation_router, timeline_router,
    watch_queue_router,
)
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
    app.state.day_updates = None

    if settings.is_configured:
        engine = create_database_engine(settings)
        app.state.session_factory = create_session_factory(engine)
        from nba_time_machine.sports.day_update import DayUpdateJobs
        app.state.day_updates = DayUpdateJobs(app.state.session_factory)

    try:
        yield
    finally:
        if app.state.day_updates is not None:
            await app.state.day_updates.close()
        if engine is not None:
            await engine.dispose()


app = FastAPI(
    title="NBA Time Machine API",
    version="0.1.0",
    lifespan=lifespan,
)
from nba_time_machine.api.viewing_guide import router as viewing_guide_router

from nba_time_machine.api.day_update import router as day_update_router

app.include_router(day_update_router)
app.include_router(viewing_guide_router)
app.include_router(timeline_router)
app.include_router(game_disclosure_router)
app.include_router(game_list_router)
app.include_router(recommendation_router)
app.include_router(watch_queue_router)
app.include_router(media_feed_router)


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
