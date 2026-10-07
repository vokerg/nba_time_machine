from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .config import DatabaseSettings


def create_database_engine(
    settings: DatabaseSettings,
    *,
    echo: bool = False,
) -> AsyncEngine:
    """Create an async engine without opening a connection eagerly."""

    return create_async_engine(
        settings.application_sqlalchemy_url(),
        echo=echo,
        pool_pre_ping=True,
    )


def create_session_factory(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
