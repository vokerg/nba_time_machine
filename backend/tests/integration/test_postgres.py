import pytest
from sqlalchemy import text

from nba_time_machine.db import DatabaseSettings, create_database_engine


@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_postgres_and_baseline_migration() -> None:
    settings = DatabaseSettings(_env_file=None)
    if not settings.is_configured:
        pytest.skip("DATABASE_URL is not configured")

    engine = create_database_engine(settings)
    try:
        async with engine.connect() as connection:
            version_num = await connection.scalar(
                text("select current_setting('server_version_num')::int")
            )
            migration_revision = await connection.scalar(
                text("select version_num from alembic_version")
            )

        assert isinstance(version_num, int)
        assert version_num > 0
        assert migration_revision == "0001_baseline"
    finally:
        await engine.dispose()
