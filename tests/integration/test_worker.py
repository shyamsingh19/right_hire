"""Smoke tests for app.workers.tasks.process_candidate — the RQ pipeline orchestrator.

Uses a throwaway sync SQLite DB (tasks.py always uses a sync engine, per CLAUDE.md) and
FakeLLMProvider. embed_texts is monkeypatched to fixed vectors so this stays fast and
offline — no sentence-transformers model download, matching the fake-vector approach
already used in test_pipeline.py.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

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


# Long enough to clear _MIN_RESUME_CHARS — anything shorter is rejected as unparseable
# on purpose, so fixtures have to look like real resumes rather than one-liners.
_RESUME = (
    "Senior engineer with 5 years building APIs in Python, PostgreSQL, and Docker. "
    "Led the migration of a monolith to containerised services and owned the on-call "
    "rotation for the payments team."
)


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
    candidate_id, job_id = _seed_job_and_candidate(sync_factory, _RESUME)

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
        sync_factory, "Intern, no professional experience. " + _RESUME
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
    candidate_id, job_id = _seed_job_and_candidate(sync_factory, _RESUME)
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


def test_process_candidate_backfills_missing_yoe_and_location(sync_factory):
    """A sheet with only name+email must not leave the results table showing N/A —
    the parsed resume fills the gaps (FakeLLMProvider returns yoe=5.0, San Francisco)."""
    candidate_id, job_id = _seed_job_and_candidate(sync_factory, _RESUME)

    tasks_module.process_candidate(candidate_id, job_id)

    session = sync_factory()
    candidate = session.get(Candidate, candidate_id)
    assert candidate.yoe == 5.0
    assert candidate.location == "San Francisco, CA"


def test_process_candidate_does_not_overwrite_sheet_provided_values(sync_factory):
    candidate_id, job_id = _seed_job_and_candidate(sync_factory, _RESUME)
    session = sync_factory()
    candidate = session.get(Candidate, candidate_id)
    candidate.yoe = 9.0
    candidate.location = "Berlin"
    session.commit()

    tasks_module.process_candidate(candidate_id, job_id)

    session = sync_factory()
    candidate = session.get(Candidate, candidate_id)
    assert candidate.yoe == 9.0
    assert candidate.location == "Berlin"


def test_process_candidate_refuses_near_empty_resume(sync_factory):
    """Given near-empty input the LLM invents a plausible candidate rather than
    returning empty fields, so too-short resumes must fail instead of being parsed."""
    candidate_id, job_id = _seed_job_and_candidate(sync_factory, "Resume")

    tasks_module.process_candidate(candidate_id, job_id)

    session = sync_factory()
    assert session.get(Candidate, candidate_id).status == CandidateStatus.failed
    eval_obj = session.execute(
        select(Evaluation).where(Evaluation.candidate_id == candidate_id)
    ).scalar_one()
    assert "too short" in eval_obj.reasons["error"].lower()
    assert eval_obj.verdict is None  # never a merit-based rejection


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


class _FakeQueue:
    def __init__(self):
        self.enqueued: list[tuple] = []

    def enqueue(self, *args, **kwargs):
        self.enqueued.append(args)


def _make_stale(sync_factory, candidate_id, minutes_ago: float, stale_retries: int = 0):
    session = sync_factory()
    candidate = session.get(Candidate, candidate_id)
    candidate.updated_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
        minutes=minutes_ago
    )
    candidate.stale_retries = stale_retries
    session.commit()


def test_sweep_requeues_a_stuck_processing_candidate(sync_factory, monkeypatch):
    candidate_id, job_id = _seed_job_and_candidate(sync_factory, _RESUME)
    session = sync_factory()
    session.get(Candidate, candidate_id).status = CandidateStatus.processing
    session.commit()
    _make_stale(sync_factory, candidate_id, minutes_ago=120, stale_retries=1)

    fake_queue = _FakeQueue()
    monkeypatch.setattr(tasks_module, "get_ats_queue", lambda: fake_queue)

    result = tasks_module.sweep_stale_candidates()

    assert result == {"requeued": 1, "failed": 0}
    assert len(fake_queue.enqueued) == 1
    session = sync_factory()
    candidate = session.get(Candidate, candidate_id)
    assert candidate.status == CandidateStatus.pending
    assert candidate.stale_retries == 2


def test_sweep_fails_candidate_past_max_retries(sync_factory, monkeypatch):
    candidate_id, job_id = _seed_job_and_candidate(sync_factory, _RESUME)
    _make_stale(sync_factory, candidate_id, minutes_ago=120, stale_retries=3)

    fake_queue = _FakeQueue()
    monkeypatch.setattr(tasks_module, "get_ats_queue", lambda: fake_queue)

    result = tasks_module.sweep_stale_candidates()

    assert result == {"requeued": 0, "failed": 1}
    assert fake_queue.enqueued == []
    session = sync_factory()
    candidate = session.get(Candidate, candidate_id)
    assert candidate.status == CandidateStatus.failed
    eval_obj = session.execute(
        select(Evaluation).where(Evaluation.candidate_id == candidate_id)
    ).scalar_one()
    assert "timed out" in eval_obj.reasons["error"].lower()


def test_sweep_leaves_fresh_candidates_alone(sync_factory, monkeypatch):
    candidate_id, job_id = _seed_job_and_candidate(sync_factory, _RESUME)

    fake_queue = _FakeQueue()
    monkeypatch.setattr(tasks_module, "get_ats_queue", lambda: fake_queue)

    result = tasks_module.sweep_stale_candidates()

    assert result == {"requeued": 0, "failed": 0}
    session = sync_factory()
    assert session.get(Candidate, candidate_id).status == CandidateStatus.pending


class _FakeScheduledRegistry:
    def __init__(self, existing_ids=None):
        self.ids = set(existing_ids or [])

    def get_job_ids(self):
        return list(self.ids)


class _FakeSchedulingQueue(_FakeQueue):
    def __init__(self, existing_ids=None):
        super().__init__()
        self.scheduled_job_registry = _FakeScheduledRegistry(existing_ids)

    def enqueue_in(self, *args, **kwargs):
        self.enqueued.append((args, kwargs))


def test_ensure_stale_sweep_scheduled_is_idempotent(monkeypatch):
    fake_queue = _FakeSchedulingQueue()
    monkeypatch.setattr(tasks_module, "get_ats_queue", lambda: fake_queue)

    tasks_module.ensure_stale_sweep_scheduled()
    assert len(fake_queue.enqueued) == 1
    _, kwargs = fake_queue.enqueued[0]
    assert kwargs["job_id"] == tasks_module._SWEEP_JOB_ID

    # A second call (e.g. next worker restart) must not schedule a duplicate.
    fake_queue.scheduled_job_registry.ids.add(tasks_module._SWEEP_JOB_ID)
    tasks_module.ensure_stale_sweep_scheduled()
    assert len(fake_queue.enqueued) == 1


def test_process_candidate_self_starts_watchdog_exactly_once(sync_factory, monkeypatch):
    """Deployment-friendliness contract: no bootstrap script or cron to wire up — the first
    candidate any worker processes must schedule the recurring sweep for us."""
    monkeypatch.setattr(tasks_module, "_watchdog_started", False)
    calls = []
    monkeypatch.setattr(tasks_module, "ensure_stale_sweep_scheduled", lambda: calls.append(1))

    candidate_id, job_id = _seed_job_and_candidate(sync_factory, _RESUME)
    tasks_module.process_candidate(candidate_id, job_id)

    session = sync_factory()
    candidate_2 = Candidate(job_id=job_id, resume_text=_RESUME, status=CandidateStatus.pending)
    session.add(candidate_2)
    session.commit()
    tasks_module.process_candidate(candidate_2.id, job_id)

    assert len(calls) == 1


def test_process_candidate_survives_watchdog_scheduling_failure(sync_factory, monkeypatch):
    """A Redis hiccup while scheduling the watchdog must never fail the candidate's own job."""
    monkeypatch.setattr(tasks_module, "_watchdog_started", False)
    monkeypatch.setattr(
        tasks_module,
        "ensure_stale_sweep_scheduled",
        lambda: (_ for _ in ()).throw(RuntimeError("redis unreachable")),
    )

    candidate_id, job_id = _seed_job_and_candidate(sync_factory, _RESUME)
    tasks_module.process_candidate(candidate_id, job_id)

    session = sync_factory()
    assert session.get(Candidate, candidate_id).status == CandidateStatus.done
