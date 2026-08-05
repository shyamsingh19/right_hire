"""Smoke tests for app.workers.tasks.process_candidate — the RQ pipeline orchestrator.

Uses a throwaway sync SQLite DB (tasks.py always uses a sync engine, per CLAUDE.md) and
FakeLLMProvider. embed_texts is monkeypatched to fixed vectors so this stays fast and
offline — no sentence-transformers model download, matching the fake-vector approach
already used in test_pipeline.py.
"""

from __future__ import annotations

import numpy as np
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import Candidate, CandidateStatus, Evaluation, Job, User
from app.workers import tasks as tasks_module


@pytest.fixture
def sync_factory(monkeypatch, tmp_path, fake_provider):
    engine = create_engine(f"sqlite:///{tmp_path / 'worker.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    monkeypatch.setattr(tasks_module, "_sync_session", lambda: factory())
    monkeypatch.setattr(tasks_module, "get_provider", lambda: fake_provider)
    monkeypatch.setattr(
        tasks_module,
        "embed_texts",
        lambda texts: np.array([[0.1] * 384 for _ in texts], dtype=np.float32),
    )
    # No live Redis in tests — verdict cache is best-effort and already handles this.
    monkeypatch.setattr(
        tasks_module,
        "_get_redis",
        lambda: (_ for _ in ()).throw(RuntimeError("no redis in tests")),
    )
    return factory


def _seed_job_and_candidate(factory, resume_text: str) -> tuple[str, str]:
    session = factory()
    user = User(email="worker@test.com", api_key_hash="0" * 64)
    session.add(user)
    session.flush()  # assign user.id before it's referenced by the job FK below

    job = Job(user_id=user.id, title="Eng", jd_raw="Need Python, PostgreSQL, Docker. 4+ years.")
    session.add(job)
    session.flush()

    candidate = Candidate(job_id=job.id, resume_text=resume_text, status=CandidateStatus.pending)
    session.add(candidate)
    session.commit()
    return candidate.id, job.id


def test_process_candidate_happy_path(sync_factory):
    candidate_id, job_id = _seed_job_and_candidate(
        sync_factory,
        "Senior engineer with 5 years building APIs in Python, PostgreSQL, and Docker.",
    )

    tasks_module.process_candidate(candidate_id, job_id)

    session = sync_factory()
    candidate = session.get(Candidate, candidate_id)
    assert candidate.status == CandidateStatus.done

    eval_obj = session.execute(
        select(Evaluation).where(Evaluation.candidate_id == candidate_id)
    ).scalar_one()
    assert eval_obj.verdict in ("Fit", "Maybe", "Reject")
    assert eval_obj.score is not None


def test_process_candidate_filter_rejection(sync_factory):
    # FakeLLMProvider's canned JD requires 4+ years; this resume has 0 — hard filter should reject
    # before any embed/judge call.
    candidate_id, job_id = _seed_job_and_candidate(
        sync_factory, "Intern, no professional experience."
    )
    session = sync_factory()
    candidate = session.get(Candidate, candidate_id)
    candidate.parsed = {
        "name": "New Grad",
        "email": "grad@test.com",
        "yoe": 0.0,
        "location": "",
        "skills": ["Python"],
        "bullets": [],
    }
    session.commit()

    tasks_module.process_candidate(candidate_id, job_id)

    session = sync_factory()
    eval_obj = session.execute(
        select(Evaluation).where(Evaluation.candidate_id == candidate_id)
    ).scalar_one()
    assert eval_obj.verdict == "Reject"
    assert "filter" in (eval_obj.reasons or {})


def test_process_candidate_records_failure_without_crashing(sync_factory, monkeypatch):
    """A mid-pipeline exception must mark the candidate failed with a reason, not raise —
    and must not hit the UnboundLocalError this test guards against."""
    candidate_id, job_id = _seed_job_and_candidate(sync_factory, "Some resume text.")
    monkeypatch.setattr(
        tasks_module, "embed_texts", lambda texts: (_ for _ in ()).throw(RuntimeError("boom"))
    )

    tasks_module.process_candidate(candidate_id, job_id)  # must not raise

    session = sync_factory()
    candidate = session.get(Candidate, candidate_id)
    assert candidate.status == CandidateStatus.failed

    eval_obj = session.execute(
        select(Evaluation).where(Evaluation.candidate_id == candidate_id)
    ).scalar_one()
    assert "boom" in eval_obj.reasons["error"]


def test_process_candidate_missing_row_is_a_noop(sync_factory):
    tasks_module.process_candidate("nonexistent", "also-nonexistent")  # must not raise


def test_process_candidate_fails_loudly_with_no_resume_text_or_url(sync_factory):
    """Guards the Critical Blocker #1 fix: a candidate with neither resume_text nor a
    resolvable resume_url must never silently get scored against empty text — it should
    end up 'failed' with a clear reason instead."""
    candidate_id, job_id = _seed_job_and_candidate(sync_factory, resume_text="")

    tasks_module.process_candidate(candidate_id, job_id)

    session = sync_factory()
    candidate = session.get(Candidate, candidate_id)
    assert candidate.status == CandidateStatus.failed

    eval_obj = session.execute(
        select(Evaluation).where(Evaluation.candidate_id == candidate_id)
    ).scalar_one()
    assert "resume" in eval_obj.reasons["error"].lower()
