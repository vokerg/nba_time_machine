"""PostgreSQL constraints for AI result metadata (issue #2)."""
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from nba_time_machine.db import (
    AIResultMetadataRecord, DatabaseSettings,
    create_database_engine, create_session_factory,
)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ai_result_metadata_tracks_versions_without_retaining_output() -> None:
    settings = DatabaseSettings(_env_file=None)
    if not settings.is_configured:
        pytest.skip("DATABASE_URL is not configured")
    engine = create_database_engine(settings)
    factory = create_session_factory(engine)
    row_id = uuid4()
    as_of = datetime(2026, 10, 12, 12, tzinfo=timezone.utc)
    try:
        async with factory() as session:
            session.add(AIResultMetadataRecord(
                id=row_id,
                use_case="spoiler_safe_summary",
                model_name="configured-provider-model",
                prompt_version="summary-v1",
                schema_version="safe-summary-v1",
                input_as_of=as_of,
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
            ))
            await session.commit()

        async with factory() as session:
            rows = (await session.scalars(select(AIResultMetadataRecord).where(
                AIResultMetadataRecord.id == row_id,
            ))).all()
            assert len(rows) == 1
            assert rows[0].input_as_of == as_of
            assert rows[0].prompt_version == "summary-v1"
            assert rows[0].created_at.tzinfo is not None
            assert "output" not in rows[0].__table__.columns
            assert "prompt" not in rows[0].__table__.columns

        async with factory() as session:
            session.add(AIResultMetadataRecord(
                use_case="spoiler_safe_summary",
                model_name="configured-provider-model",
                prompt_version="summary-v1",
                schema_version="safe-summary-v1",
                prompt_tokens=-1,
            ))
            with pytest.raises(IntegrityError):
                await session.commit()

        async with factory() as session:
            session.add(AIResultMetadataRecord(
                use_case=" ",
                model_name="configured-provider-model",
                prompt_version="summary-v1",
                schema_version="safe-summary-v1",
            ))
            with pytest.raises(IntegrityError):
                await session.commit()
    finally:
        await engine.dispose()
