from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

from nba_time_machine.db import DatabaseSettings, create_database_engine


@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_postgres_and_current_migration_head() -> None:
    settings = DatabaseSettings(_env_file=None)
    if not settings.is_configured:
        pytest.skip("DATABASE_URL is not configured")

    alembic_config = Config(str(Path(__file__).parents[2] / "alembic.ini"))
    expected_head = ScriptDirectory.from_config(alembic_config).get_current_head()

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
        assert expected_head is not None
        assert migration_revision == expected_head
    finally:
        await engine.dispose()
