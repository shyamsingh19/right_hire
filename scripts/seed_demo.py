#!/usr/bin/env python
"""Seed the database with a sample job and 5 candidates, and enqueue them."""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth import generate_api_key, hash_api_key
from app.config import settings
from app.db import Base
from app.llm.factory import get_provider
from app.models import Candidate, CandidateStatus, Job, User
from app.pipeline.parse import parse_jd

DEMO_EMAIL = "demo@right-hire.local"

SAMPLE_JD = """
We are looking for a Senior Python Engineer to join our backend team.

Requirements:
- 4+ years of professional Python experience
- Strong knowledge of PostgreSQL and SQL query optimisation
- Experience with Docker and containerised deployments
- Familiarity with Redis for caching

Nice to have:
- Kubernetes, FastAPI, AWS, CI/CD pipelines

Location: San Francisco, CA (hybrid)
"""

SAMPLE_CANDIDATES = [
    {
        "name": "Alice Chen",
        "email": "alice@example.com",
        "yoe": 6.0,
        "location": "San Francisco, CA",
        "resume_text": "6 years Python, PostgreSQL, Docker, Redis, FastAPI. Led 3 backend rewrites. AWS certified.",
    },
    {
        "name": "Bob Smith",
        "email": "bob@example.com",
        "yoe": 4.5,
        "location": "Remote",
        "resume_text": "4.5 years Python, PostgreSQL, Docker. Built data pipeline at FinTech startup.",
    },
    {
        "name": "Carol Wang",
        "email": "carol@example.com",
        "yoe": 2.0,
        "location": "New York",
        "resume_text": "2 years Python and Django. MySQL. No Docker experience yet.",
    },
    {
        "name": "Dan Lee",
        "email": "dan@example.com",
        "yoe": 8.0,
        "location": "San Francisco, CA",
        "resume_text": "8 years Java and some Python. PostgreSQL expert. Kubernetes and Docker.",
    },
    {
        "name": "Eva Müller",
        "email": "eva@example.com",
        "yoe": 5.0,
        "location": "Berlin",
        "resume_text": "5 years Python, FastAPI, PostgreSQL, Redis. Open-source contributor. Remote-only.",
    },
]


async def seed() -> None:
    engine = create_async_engine(settings.async_database_url, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    provider = get_provider()
    parsed = parse_jd(SAMPLE_JD, provider)

    async with factory() as session:
        user = (
            await session.execute(select(User).where(User.email == DEMO_EMAIL))
        ).scalar_one_or_none()
        if user:
            print(f"Reusing existing demo user {DEMO_EMAIL} — use the API key from its first run.")
        else:
            api_key = generate_api_key()
            user = User(email=DEMO_EMAIL, api_key_hash=hash_api_key(api_key))
            session.add(user)
            await session.flush()
            print(f"Created demo user {DEMO_EMAIL} — API key (save this, shown once): {api_key}")

        job = Job(
            user_id=user.id,
            title="Senior Python Engineer",
            jd_raw=SAMPLE_JD,
            jd_parsed=parsed.model_dump(),
            weights={"skill_overlap": 0.30, "cosine": 0.20, "judge": 0.50},
            thresholds={"fit": 0.70, "maybe": 0.40},
        )
        session.add(job)
        await session.flush()

        candidate_ids = []
        for c in SAMPLE_CANDIDATES:
            cid = str(uuid.uuid4())
            candidate = Candidate(
                id=cid,
                job_id=job.id,
                name=c["name"],
                email=c["email"],
                yoe=c["yoe"],
                location=c["location"],
                resume_text=c["resume_text"],
                status=CandidateStatus.pending,
            )
            session.add(candidate)
            candidate_ids.append(cid)

        await session.commit()
        print(f"Created job: {job.id}")
        print(f"Created {len(candidate_ids)} candidates")

    # Enqueue
    try:
        import redis as redis_lib
        from rq import Queue

        r = redis_lib.from_url(settings.effective_redis_url)
        q = Queue("ats", connection=r)
        for cid in candidate_ids:
            q.enqueue("app.workers.tasks.process_candidate", cid, job.id, job_timeout=600)
        print(f"Enqueued {len(candidate_ids)} candidates")
    except Exception as exc:
        print(f"Could not enqueue (is Redis running?): {exc}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
