"""Separate loopback-only workbench. NEVER import routes into the consumer app."""
import ipaddress
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import AwareDatetime, BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from nba_time_machine.db import DatabaseSettings, create_database_engine, create_session_factory
from nba_time_machine.workbench.calculations import TuningConfig
from nba_time_machine.workbench.service import inspect_slate

STATIC = Path(__file__).parent / "static"
DEFAULT_CONFIG = Path(__file__).resolve().parents[4] / "config/ranking/trajectory-baseline-v1.json"


@asynccontextmanager
async def lifespan(app):
    engine = create_database_engine(DatabaseSettings())
    app.state.session_factory = create_session_factory(engine)
    app.state.baseline = TuningConfig.model_validate_json(DEFAULT_CONFIG.read_text())
    try:
        yield
    finally:
        await engine.dispose()


app = FastAPI(title="NBA scoring workbench (local only)", lifespan=lifespan,
              docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def local_only(request: Request, call_next):
    try:
        local = ipaddress.ip_address(request.client.host).is_loopback
    except (ValueError, AttributeError):
        local = False
    host = request.url.hostname
    origin = request.headers.get("origin")
    same_origin = not origin or (urlsplit(origin).scheme in ("http", "https")
        and urlsplit(origin).netloc == request.headers.get("host"))
    if not local or host not in ("127.0.0.1", "localhost", "::1") or not same_origin:
        return JSONResponse({"detail": "Local workbench only"}, status_code=403)
    if request.method == "POST":
        try:
            size = int(request.headers.get("content-length", "0"))
        except ValueError:
            return JSONResponse({"detail": "Invalid request size"}, status_code=400)
        if size > 16384 or len(await request.body()) > 16384:
            return JSONResponse({"detail": "Configuration request too large"}, status_code=413)
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
    return response


async def read_session(request: Request):
    factory = request.app.state.session_factory
    async with factory() as session:
        async with session.begin():
            # A bug in inspection cannot mutate the owner's canonical database.
            await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
            await session.execute(text("SET LOCAL statement_timeout = '15000ms'"))
            try:
                yield session
            except SQLAlchemyError:
                raise HTTPException(503, "Database inspection unavailable; no source bodies or credentials logged") from None


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slate_date: date
    as_of: AwareDatetime
    config: TuningConfig


@app.get("/api/slate")
async def slate(request: Request, date: date = Query(), as_of: AwareDatetime | None = None,
                session=Depends(read_session)):
    baseline = request.app.state.baseline
    return await inspect_slate(session, date, as_of or datetime.now(timezone.utc), baseline, baseline)


@app.post("/api/preview")
async def compare(payload: PreviewRequest, request: Request, session=Depends(read_session)):
    return await inspect_slate(session, payload.slate_date, payload.as_of,
                               request.app.state.baseline, payload.config)


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
