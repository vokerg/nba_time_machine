"""Real PostgreSQL/API media review and spoiler-policy regressions (#91)."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from nba_time_machine.api.media_feed import router
from nba_time_machine.db import (
    CollectionRunRecord, DatabaseSettings, GameObservationRecord, GameRecord,
    RawCaptureRecord, SeasonRecord, SourceItemRecord, SourceRecord, TeamRecord,
    create_database_engine, create_session_factory,
)
from nba_time_machine.db.acknowledgement_models import GameAcknowledgementRecord
from nba_time_machine.db.entity_link_models import SourceItemEntityLinkRecord
from nba_time_machine.db.media_models import MediaReviewRecord
from nba_time_machine.temporal import SqlAlchemyTimelineRepository, TimelineService

CURSOR = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)
TIP = CURSOR - timedelta(days=1)
FINAL = CURSOR + timedelta(hours=2)
OBS = CURSOR - timedelta(hours=3)
REVIEW = CURSOR - timedelta(hours=1)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_api_cursor_revision_mixed_game_and_pagination_fail_closed():
    settings = DatabaseSettings(_env_file=None)
    if not settings.is_configured:
        pytest.skip("DATABASE_URL is not configured")
    engine = create_database_engine(settings)
    factory = create_session_factory(engine)
    profile, other_profile, season, home, away, a, b, run_id = (uuid4() for _ in range(8))
    source_id = f"media-review-test-{uuid4()}"
    ids = {}
    app = FastAPI()
    app.state.session_factory = factory
    app.include_router(router)

    try:
        async with factory() as session:
            session.add_all([
                SeasonRecord(id=season, league="NBA", label=f"media-test-{season}"),
                TeamRecord(id=home, league="NBA", name="Home"),
                TeamRecord(id=away, league="NBA", name="Away"),
                SourceRecord(
                    id=source_id, name="Reviewed RSS publisher", kind="web",
                    adapter="rss", category=[], locator="https://example.org/rss",
                    enabled=False, verification_status="verified", cadence_minutes=60,
                    requires_auth=False, retention_policy="metadata_excerpt",
                ),
                CollectionRunRecord(id=run_id, started_at=OBS),
            ])
            await session.flush()
            session.add_all([
                GameRecord(id=id, season_id=season, home_team_id=home, away_team_id=away)
                for id in (a, b)
            ])
            await session.flush()
            for game in (a, b):
                session.add(GameObservationRecord(
                    id=uuid4(), game_id=game, source_id=source_id,
                    observed_at=TIP-timedelta(days=1), available_at=TIP-timedelta(days=1),
                    scheduled_tip_at=TIP, status="scheduled",
                ))
                session.add(GameObservationRecord(
                    id=uuid4(), game_id=game, source_id=source_id,
                    observed_at=FINAL, available_at=FINAL,
                    scheduled_tip_at=TIP, final_at=FINAL,
                    status="final", home_score=100, away_score=90,
                ))
            await session.flush()
            def add_item(name, *, sensitivity="general", games=(), observed=OBS, reviewed=REVIEW, cleared=True):
                item_id, capture_id = uuid4(), uuid4()
                ids[name] = (item_id, capture_id)
                session.add(SourceItemRecord(
                    id=item_id, source_id=source_id, canonical_identity=f"external:{name}",
                    title=name, canonical_url=f"https://example.org/{name}",
                    discovered_at=observed, captured_at=observed, available_at=observed,
                ))
                session.add(RawCaptureRecord(
                    id=capture_id, source_id=source_id, source_item_id=item_id,
                    collection_run_id=run_id, external_id=name,
                    canonical_url=f"https://example.org/{name}",
                    discovered_at=observed, captured_at=observed, available_at=observed,
                    content_type="application/rss+xml", title=name,
                    text_content=f"{name} excerpt", content_hash=name,
                ))
                if reviewed is not None:
                    session.add(MediaReviewRecord(
                        capture_id=capture_id, reviewed_at=reviewed, sensitivity=sensitivity,
                        game_ids=list(games), rights_cleared=cleared, link_cleared=True,
                    ))
            add_item("a-result", sensitivity="outcome_dependent", games=(a,))
            add_item("b-result", sensitivity="outcome_dependent", games=(b,))
            add_item("a-b-mixed", sensitivity="outcome_dependent", games=(a, b))
            add_item("league-preview")
            add_item("future", observed=CURSOR+timedelta(hours=1), reviewed=CURSOR+timedelta(hours=2))
            add_item("unreviewed", reviewed=None)
            add_item("uncleared", cleared=False)
            add_item("revised")
            add_item("unlinked-result", sensitivity="outcome_dependent", games=(a,))
            await session.flush()
            # Only the earlier revision is reviewed. The newer revision
            # invalidates an earlier safe headline at this same cursor.
            revised_id = ids["revised"][0]
            session.add(RawCaptureRecord(
                id=uuid4(), source_id=source_id, source_item_id=revised_id,
                collection_run_id=run_id, external_id="revised",
                canonical_url="https://example.org/revised",
                discovered_at=OBS, captured_at=CURSOR-timedelta(minutes=10),
                available_at=CURSOR-timedelta(minutes=10),
                content_type="application/rss+xml", title="Shocking future result",
                content_hash="revised-2",
            ))
            session.add(SourceItemEntityLinkRecord(
                id=uuid4(), source_item_id=ids["unlinked-result"][0],
                entity_type="game", game_id=b, link_state="present",
                derivation_method="rule", observed_at=OBS, available_at=OBS,
            ))
            session.add(GameAcknowledgementRecord(profile_id=profile, game_id=a))
            await session.commit()
            t = TimelineService(SqlAlchemyTimelineRepository(session))
            await t.initialize(profile, CURSOR)
            await t.initialize(other_profile, CURSOR)

        url = f"/profiles/{profile}/media"
        params = {"time_cursor": CURSOR.isoformat(), "limit": 1}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            entries, pages = [], set()
            page = None
            for _ in range(6):
                result = await client.get(url, params={**params, **({"page": page} if page else {})})
                assert result.status_code == 200, result.text
                body = result.json()
                assert body["time_cursor"] == "2026-10-15T12:00:00Z"
                assert len(body["items"]) <= 1
                entries.extend(body["items"])
                page = body.get("next_page")
                if not page:
                    break
                assert page not in pages
                pages.add(page)
            else:
                pytest.fail("pagination did not terminate")
            assert {item["headline"] for item in entries} == {"a-result", "league-preview"}
            assert all(item["source"] == "Reviewed RSS publisher" and item["url"].startswith("https://") for item in entries)
            assert all("home_score" not in str(item) and "thumbnail_url" not in str(item) for item in entries)
            assert all(item["known_at"] == REVIEW.isoformat().replace("+00:00", "Z") for item in entries)
            if pages:
                assert (await client.get(url, params={**params, "page": next(iter(pages)), "time_cursor": (CURSOR+timedelta(seconds=1)).isoformat()})).status_code == 409
            before_reveal = await client.get(f"/profiles/{other_profile}/media", params={"time_cursor": CURSOR.isoformat()})
            assert [v["headline"] for v in before_reveal.json()["items"]] == ["league-preview"]
            assert (await client.get(url, params={"time_cursor": (CURSOR-timedelta(seconds=1)).isoformat()})).status_code == 409
        # Cursors and acknowledgements were never modified by general feed reads.
        async with factory() as session:
            stored = await session.scalar(select(GameAcknowledgementRecord).where(GameAcknowledgementRecord.profile_id == profile, GameAcknowledgementRecord.game_id == a))
            assert stored is not None
            state = await TimelineService(SqlAlchemyTimelineRepository(session)).resume(profile)
            assert state.time_cursor == CURSOR
    finally:
        await engine.dispose()
