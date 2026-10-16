"""Separate loopback-only workbench. NEVER import routes into the consumer app."""
import ipaddress
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import AwareDatetime, BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from nba_time_machine.db import DatabaseSettings, create_database_engine, create_session_factory
from nba_time_machine.workbench.calculations import TuningConfig
from nba_time_machine.workbench.service import inspect_slate
from nba_time_machine.workbench.collection import DayVerification

STATIC = Path(__file__).parent / "static"
DEFAULT_CONFIG = Path(__file__).resolve().parents[4] / "config/ranking/trajectory-baseline-v1.json"
CANDIDATE_CONFIG = DEFAULT_CONFIG.with_name("entertainment-stars-v5.json")


@asynccontextmanager
async def lifespan(app):
    engine = create_database_engine(DatabaseSettings())
    app.state.session_factory = create_session_factory(engine)
    app.state.baseline = TuningConfig.model_validate_json(DEFAULT_CONFIG.read_text())
    app.state.candidate = TuningConfig.model_validate_json(CANDIDATE_CONFIG.read_text())
    app.state.verification = DayVerification(app.state.session_factory)
    try:
        yield
    finally:
        await app.state.verification.close()
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


class VerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slate_date: date


@app.post("/api/verify", status_code=202)
async def verify(payload: VerifyRequest, request: Request):
    # A custom header plus JSON prevents cross-origin form submissions even when
    # Origin is absent. The loopback middleware also checks Host/Origin.
    if request.headers.get("x-workbench-action") != "collect-day":
        raise HTTPException(403, "Explicit local collection action required")
    job = request.app.state.verification
    if not job.start(payload.slate_date):
        raise HTTPException(409, "Day verification already running")
    return job.result


@app.get("/api/verify")
async def verification_status(request: Request, job_id: UUID | None = None):
    result = request.app.state.verification.result
    if job_id is not None and str(job_id) != result.get("job_id"):
        raise HTTPException(409, "Verification result replaced or server restarted; load stored games")
    return result


@app.get("/api/slate")
async def slate(request: Request, date: date = Query(), as_of: AwareDatetime | None = None,
                session=Depends(read_session)):
    baseline = request.app.state.baseline
    return await inspect_slate(session, date, as_of or datetime.now(timezone.utc), baseline,
                               request.app.state.candidate, request.app.state.candidate)


@app.post("/api/preview")
async def compare(payload: PreviewRequest, request: Request, session=Depends(read_session)):
    return await inspect_slate(session, payload.slate_date, payload.as_of,
                               request.app.state.baseline, payload.config, request.app.state.candidate)


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
