#!/usr/bin/env python
"""Seed one job + 15 varied candidates for practical end-to-end testing.

Unlike seed_demo.py's 5 candidates, this set is deliberately spread across
hard-filter rejects, weak/strong judge outcomes, and clean fits so a real
LLM backend (local Ollama or cloud) has something meaningful to discriminate
between. See TESTING_GUIDE.md for how to run this against local vs cloud LLMs.
"""
from __future__ import annotations

import asyncio
import uuid

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.db import Base
from app.llm.factory import get_provider
from app.models import Candidate, CandidateStatus, Job
from app.pipeline.parse import parse_jd

JOB_TITLE = "Senior Backend Engineer (Python)"

JOB_JD = """
We are hiring a Senior Backend Engineer to own core services on our platform.

Requirements:
- 4+ years of professional Python experience
- Strong knowledge of PostgreSQL and query optimisation
- Experience with Docker and containerised deployments

Nice to have:
- Redis, Kubernetes, FastAPI, AWS, CI/CD pipelines

Location: San Francisco, CA (hybrid, remote considered for strong candidates)
"""

CANDIDATES = [
    {"name": "Alice Chen", "email": "alice@example.com", "yoe": 7.0, "location": "San Francisco, CA",
     "resume_text": "7 years Python backend engineering. Deep PostgreSQL query tuning experience. "
     "Docker + Kubernetes in production. Built FastAPI services handling 20k req/s. AWS certified."},

    {"name": "Bob Smith", "email": "bob@example.com", "yoe": 5.0, "location": "Remote",
     "resume_text": "5 years Python. PostgreSQL for OLTP workloads. Docker Compose for local dev. "
     "Some Redis caching experience. No Kubernetes yet."},

    {"name": "Carol Wang", "email": "carol@example.com", "yoe": 1.5, "location": "New York",
     "resume_text": "1.5 years Python and Django. MySQL, not PostgreSQL. Learning Docker."},

    {"name": "Dan Lee", "email": "dan@example.com", "yoe": 6.0, "location": "San Francisco, CA",
     "resume_text": "6 years primarily Java, with 2 years of Python on the side. PostgreSQL expert. "
     "Comfortable with Docker and Kubernetes from platform team work."},

    {"name": "Eva Muller", "email": "eva@example.com", "yoe": 4.5, "location": "Berlin",
     "resume_text": "4.5 years Python, strong FastAPI background. PostgreSQL for most projects. "
     "Never used Docker directly, deploys were handled by ops."},

    {"name": "Frank Ito", "email": "frank@example.com", "yoe": 5.0, "location": "Austin, TX",
     "resume_text": "5 years DevOps-leaning role. Heavy Docker and Kubernetes expertise, manages "
     "clusters for multiple teams. Python used mostly for scripting and tooling, not backend services."},

    {"name": "Grace Kim", "email": "grace@example.com", "yoe": 2.0, "location": "Seattle, WA",
     "resume_text": "2 years as a junior backend developer. Python and Flask. SQLite in dev, "
     "PostgreSQL in prod but limited hands-on tuning. No Docker experience."},

    {"name": "Henry Osei", "email": "henry@example.com", "yoe": 8.0, "location": "San Francisco, CA",
     "resume_text": "8 years Python backend, staff-level. Owns PostgreSQL infrastructure for a "
     "50-engineer org. Docker and Kubernetes daily. AWS certified, built internal CI/CD platform."},

    {"name": "Ivy Zhao", "email": "ivy@example.com", "yoe": 4.0, "location": "Remote",
     "resume_text": "4 years data engineering with Python. Strong SQL across MySQL and PostgreSQL. "
     "Airflow and dbt experience. Docker used for local pipeline testing only."},

    {"name": "Jake Wilson", "email": "jake@example.com", "yoe": 3.0, "location": "Chicago, IL",
     "resume_text": "3 years full-stack, mostly React frontend with a Node.js backend. Basic Python "
     "scripting. No PostgreSQL or Docker production experience."},

    {"name": "Kara Novak", "email": "kara@example.com", "yoe": 6.0, "location": "Remote",
     "resume_text": "6 years Python backend, FastAPI and Redis specialist. PostgreSQL with read "
     "replicas at scale. Docker Compose and basic Kubernetes. Open-source maintainer."},

    {"name": "Liam Brooks", "email": "liam@example.com", "yoe": 1.0, "location": "Denver, CO"
     , "resume_text": "1 year as a software engineer after a career switch from marketing. "
     "Currently learning Python and SQL through an online bootcamp."},

    {"name": "Maya Patel", "email": "maya@example.com", "yoe": 5.0, "location": "San Francisco, CA",
     "resume_text": "5 years as a contractor across multiple stacks: Python, Ruby, some Go. "
     "Generalist Docker knowledge. PostgreSQL used on about half of past projects."},

    {"name": "Noah Fischer", "email": "noah@example.com", "yoe": 12.0, "location": "San Francisco, CA",
     "resume_text": "12 years Python, ex-principal engineer. Designed PostgreSQL sharding strategy "
     "at previous company. Docker and Kubernetes since 2018. AWS and GCP experience."},

    {"name": "Olivia Turner", "email": "olivia@example.com", "yoe": 4.0, "location": "Portland, OR",
     "resume_text": "4 years Python backend. PostgreSQL expert, wrote internal query optimisation "
     "guide. New to Docker, containerised first project 6 months ago."},
]


async def seed() -> None:
    engine = create_async_engine(settings.async_database_url, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    provider = get_provider()
    parsed = parse_jd(JOB_JD, provider)

    async with factory() as session:
        job = Job(
            title=JOB_TITLE,
            jd_raw=JOB_JD,
            jd_parsed=parsed.model_dump(),
            weights={"skill_overlap": 0.30, "cosine": 0.20, "judge": 0.50},
            thresholds={"fit": 0.70, "maybe": 0.40},
        )
        session.add(job)
        await session.flush()

        candidate_ids = []
        for c in CANDIDATES:
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

    try:
        import redis as redis_lib
        from rq import Queue

        r = redis_lib.from_url(settings.redis_url)
        q = Queue("ats", connection=r)
        for cid in candidate_ids:
            q.enqueue("app.workers.tasks.process_candidate", cid, job.id, job_timeout=600)
        print(f"Enqueued {len(candidate_ids)} candidates on queue 'ats'")
    except Exception as exc:
        print(f"Could not enqueue (is Redis running?): {exc}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
