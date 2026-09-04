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
    # filess.io caps this account at 5 concurrent connections for the whole ACCOUNT —
    # not per process, per host, or per deployment. Every uvicorn, every RQ worker (plus
    # each of its forked work horses) and every `alembic upgrade head` draws from the
    # same 5. Pooled connections are held while idle, so a generous pool_size silently
    # squats slots the rest of the account then can't get. Budget per process:
    #   API 1+1  |  worker 1 (x parent + work horse)  |  alembic 1 transient (NullPool)
    # which leaves room for a second deployment (e.g. local dev against the same DB).
    pool_kwargs = {} if "sqlite" in url else {"pool_size": 1, "max_overflow": 1}
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
