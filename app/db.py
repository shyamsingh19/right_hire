from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    pass


def _make_engine(url: str):
    connect_args = {}
    if "sqlite" in url:
        connect_args["check_same_thread"] = False
    # filess.io caps this account at 5 concurrent connections total, shared with the
    # worker's sync engine (app/workers/tasks.py) — keep this pool small rather than
    # SQLAlchemy's default (5 + 10 overflow), which alone would exceed the quota.
    pool_kwargs = {} if "sqlite" in url else {"pool_size": 3, "max_overflow": 0}
    return create_async_engine(
        url,
        echo=False,
        pool_pre_ping=True,
        pool_recycle=280,
        connect_args=connect_args,
        **pool_kwargs,
    )


engine = _make_engine(settings.async_database_url)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
