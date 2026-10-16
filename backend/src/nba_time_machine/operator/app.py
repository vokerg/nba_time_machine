"""Separate read-only operator service. Never mount this app in the consumer API."""
from __future__ import annotations

import csv
import io
import ipaddress
import json
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from nba_time_machine.db import DatabaseSettings, create_database_engine, create_session_factory
from nba_time_machine.operator.report import build_report

ROOT = Path(__file__).parent


@asynccontextmanager
async def lifespan(app):
    engine = create_database_engine(DatabaseSettings())
    app.state.session_factory = create_session_factory(engine)
    try:
        yield
    finally:
        await engine.dispose()


app = FastAPI(title="NBA local ingestion coverage", lifespan=lifespan,
              docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def local_only(request: Request, call_next):
    try:
        local_client = ipaddress.ip_address(request.client.host).is_loopback
    except (AttributeError, ValueError):
        local_client = False
    origin = request.headers.get("origin")
    try:
        parts = urlsplit(origin) if origin else None
    except ValueError:
        return JSONResponse({"detail": "Local operator view only"}, status_code=403)
    same_origin = parts is None or (parts.scheme in ("http", "https")
                                   and parts.netloc == request.headers.get("host"))
    if not local_client or request.url.hostname not in ("127.0.0.1", "localhost", "::1") or not same_origin:
        return JSONResponse({"detail": "Local operator view only"}, status_code=403)
    if request.method != "GET" and request.method != "HEAD":
        return JSONResponse({"detail": "Read-only operator view"}, status_code=405)
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
        "frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
    )
    return response


async def read_session(request: Request):
    async with request.app.state.session_factory() as session:
        async with session.begin():
            await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
            await session.execute(text("SET LOCAL statement_timeout = '15000ms'"))
            yield session


@app.get("/")
async def home():
    return FileResponse(ROOT / "index.html", media_type="text/html")


@app.get("/operator.js")
async def script():
    return FileResponse(ROOT / "operator.js", media_type="text/javascript")


@app.get("/operator.css")
async def styles():
    return FileResponse(ROOT / "operator.css", media_type="text/css")


async def report(day, season, source, status, session):
    try:
        return await build_report(session, day=day, season=season, source=source, status=status)
    except ValueError as exc:
        if str(exc).startswith("invalid_"):
            raise HTTPException(422, "Invalid filter") from None
        raise HTTPException(503, "Operational query limit exceeded") from None
    except SQLAlchemyError:
        raise HTTPException(503, "Read-only database inspection unavailable") from None


@app.get("/api/report")
async def inspect(day: date | None = None, season: str | None = None,
                  source: str | None = None, status: str | None = None,
                  session=Depends(read_session)):
    return await report(day, season, source, status, session)


def escape_spreadsheet(value):
    """Prevent exported text from becoming formulas when CSV is opened in a spreadsheet."""
    data = "" if value is None else str(value)
    return "'" + data if data.startswith(("=", "+", "-", "@", "\t", "\r", "\n")) else data


def to_csv(data):
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(("section", "id", "day", "source", "status", "observed_at", "detail"))
    for row in data["sources"]:
        writer.writerow([escape_spreadsheet(x) for x in (
            "source", row["id"], "", row["id"], row["freshness"],
            row["last_attempt_at"], row["last_outcome"] or "unknown")])
    for row in data["outcomes"]:
        writer.writerow([escape_spreadsheet(x) for x in (
            "outcome", row["run_id"], "", row["source_id"], row["status"],
            row["finished_at"], row["error_code"] or "")])
    for row in data["runs"]:
        writer.writerow([escape_spreadsheet(x) for x in (
            "run", row["id"], "", "", "finished" if row["finished_at"] else "unfinished",
            row["started_at"], row["collector"] or "")])
    for row in data["games"]:
        writer.writerow([escape_spreadsheet(x) for x in (
            "game", row["game_id"], row["day"], row["observation_source"],
            row["status"], row["last_observed_at"],
            "PBP:" + row["play_by_play"]["status"] + " BOX:" + row["player_box"]["status"])])
    return out.getvalue()


@app.get("/api/export")
async def export(day: date | None = None, season: str | None = None,
                 source: str | None = None, status: str | None = None,
                 file_format: str = Query("json", alias="format"),
                 session=Depends(read_session)):
    if file_format not in ("json", "csv"):
        raise HTTPException(422, "Invalid export format")
    data = await report(day, season, source, status, session)
    if file_format == "csv":
        return Response(to_csv(data), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": "attachment; filename=nba-coverage.csv"})
    return Response(json.dumps(data, ensure_ascii=False), media_type="application/json",
                    headers={"Content-Disposition": "attachment; filename=nba-coverage.json"})
