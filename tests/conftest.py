from __future__ import annotations

import asyncio
from typing import Generator

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db import Base, get_db
from app.llm.base import LLMProvider
from app.schemas import JudgeOutput, ParsedJD, ParsedResume

# ── FakeLLMProvider ──────────────────────────────────────────────────────────


class FakeLLMProvider(LLMProvider):
    """Returns deterministic canned outputs. No GPU, no network required."""

    _RESUME = ParsedResume(
        name="Alice Dev",
        email="alice@example.com",
        yoe=5.0,
        location="San Francisco, CA",
        skills=["Python", "FastAPI", "PostgreSQL", "Docker", "Redis"],
        bullets=[
            "Built REST API serving 10k req/s using FastAPI and PostgreSQL",
            "Containerised entire stack with Docker Compose",
        ],
    )
    _JD = ParsedJD(
        title="Senior Python Engineer",
        required_skills=["Python", "PostgreSQL", "Docker"],
        preferred_skills=["Redis", "Kubernetes"],
        min_yoe=4.0,
        location="San Francisco, CA",
        must_haves=[],
    )
    _JUDGE = JudgeOutput(
        scores={"technical_fit": 0.9, "experience_depth": 0.8},
        reasons={
            "technical_fit": "Matches all 3 required skills",
            "experience_depth": "5 years with strong project ownership",
        },
        overall_score=0.85,
        verdict="Fit",
    )

    def complete_json(self, prompt: str, schema, max_tokens: int = 256):
        if schema is ParsedResume:
            return self._RESUME
        if schema is ParsedJD:
            return self._JD
        if schema is JudgeOutput:
            return self._JUDGE
        return schema()

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.1] * 384 for _ in texts]


@pytest.fixture
def fake_provider() -> FakeLLMProvider:
    return FakeLLMProvider()


# ── In-memory SQLite DB for tests ────────────────────────────────────────────

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def test_db() -> AsyncSession:
    engine = create_async_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


# ── TestClient with provider override ────────────────────────────────────────


@pytest.fixture
def client(fake_provider) -> Generator:
    from app import db as db_module
    from app.main import app
    from app.llm.factory import get_provider

    app.dependency_overrides[get_provider] = lambda: fake_provider

    # Override DB with SQLite — swap the module-level engine so the app's own
    # lifespan (Base.metadata.create_all) runs against the test DB too,
    # instead of the real DATABASE_URL from settings.
    engine = create_async_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _override_db():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_db

    original_engine = db_module.engine
    db_module.engine = engine
    try:
        with TestClient(app, raise_server_exceptions=True) as c:
            # TestClient reuses the same client host across every test in this process,
            # so the per-IP signup rate limiter (app/api/auth.py) would otherwise trip
            # partway through the suite. Reset it per test — each test is its own "IP".
            from app.api.auth import _signup_attempts

            _signup_attempts.clear()

            # All routes require an API key — sign up a default user so existing
            # tests that don't care about auth (most of them) work unmodified.
            signup = c.post("/auth/signup", json={"email": "test@example.com"})
            c.headers["X-API-Key"] = signup.json()["api_key"]
            yield c
    finally:
        db_module.engine = original_engine
        app.dependency_overrides.clear()
        asyncio.run(engine.dispose())


@pytest.fixture
def other_user_headers(client) -> dict:
    """A second, distinct user's auth header — for cross-user isolation tests."""
    signup = client.post("/auth/signup", json={"email": "other@example.com"})
    return {"X-API-Key": signup.json()["api_key"]}
