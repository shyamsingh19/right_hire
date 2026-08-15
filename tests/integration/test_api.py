"""API integration tests using TestClient + FakeLLMProvider + SQLite."""

from __future__ import annotations

import io

import openpyxl

from app.config import settings


def _make_excel(rows: list[dict]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    if not rows:
        return b""
    headers = list(rows[0].keys())
    ws.append(headers)
    for row in rows:
        ws.append([row.get(h) for h in headers])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_health_reports_every_dependency(client):
    """Asserts structure, not liveness — CI has no Ollama, so 'degraded' is a valid
    answer here. What must always hold is that every dependency gets reported."""
    import app.main as main_module

    main_module._llm_health_cache = None

    resp = client.get("/health")
    assert resp.status_code in (200, 503)
    body = resp.json()
    assert body["status"] in ("ok", "degraded")
    assert set(body["checks"]) == {"db", "redis", "llm", "storage"}
    assert set(body["targets"]) == {"db", "redis", "llm", "storage_dir"}


def test_health_degraded_when_llm_unreachable(client, monkeypatch):
    import app.main as main_module

    main_module._llm_health_cache = None
    monkeypatch.setattr(main_module, "_check_llm", lambda: "error: connection refused")

    resp = client.get("/health")
    assert resp.status_code == 503
    assert resp.json()["status"] == "degraded"
    assert "connection refused" in resp.json()["checks"]["llm"]


def test_health_ok_when_everything_reachable(client, monkeypatch):
    import app.main as main_module

    main_module._llm_health_cache = None
    monkeypatch.setattr(main_module, "_check_llm", lambda: "ok")

    resp = client.get("/health")
    if resp.json()["checks"]["redis"] == "ok":  # skip if no Redis in this environment
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


def test_create_job(client):
    resp = client.post(
        "/jobs",
        json={
            "title": "Senior Python Engineer",
            "jd_raw": "Looking for a Python expert with 5+ years. Required: Python, PostgreSQL.",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["id"]
    assert data["title"] == "Senior Python Engineer"
    assert data["jd_parsed"] is not None


def test_list_jobs(client):
    resp = client.get("/jobs")
    assert resp.status_code == 200
    assert resp.json() == []

    created = client.post("/jobs", json={"title": "Data Engineer", "jd_raw": "Need SQL, Airflow."})
    job_id = created.json()["id"]

    resp = client.get("/jobs")
    assert resp.status_code == 200
    ids = [j["id"] for j in resp.json()]
    assert job_id in ids


def test_get_job_not_found(client):
    resp = client.get("/jobs/nonexistent-id")
    assert resp.status_code == 404


def test_get_job_after_create(client):
    create = client.post("/jobs", json={"title": "ML Engineer", "jd_raw": "Need ML experience."})
    job_id = create.json()["id"]

    resp = client.get(f"/jobs/{job_id}")
    assert resp.status_code == 200
    assert resp.json()["candidate_count"] == 0


def test_ingest_candidates(client):
    create = client.post("/jobs", json={"title": "Eng", "jd_raw": "Python required."})
    job_id = create.json()["id"]

    xlsx = _make_excel(
        [
            {
                "name": "Alice",
                "email": "alice@test.com",
                "yoe": 5,
                "location": "SF",
                "resume_url": "",
            },
            {"name": "Bob", "email": "bob@test.com", "yoe": 2, "location": "NY", "resume_url": ""},
        ]
    )
    resp = client.post(
        f"/jobs/{job_id}/candidates",
        files={
            "file": (
                "candidates.xlsx",
                xlsx,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert resp.status_code == 202
    data = resp.json()
    assert data["queued_count"] == 2
    assert len(data["candidate_ids"]) == 2


def test_ingest_candidates_csv(client):
    create = client.post("/jobs", json={"title": "Eng", "jd_raw": "Python required."})
    job_id = create.json()["id"]

    csv_bytes = (
        b"name,email,yoe,location,resume_url\nAlice,alice@test.com,5,SF,\nBob,bob@test.com,2,NY,\n"
    )
    resp = client.post(
        f"/jobs/{job_id}/candidates",
        files={"file": ("candidates.csv", csv_bytes, "text/csv")},
    )
    assert resp.status_code == 202
    data = resp.json()
    assert data["queued_count"] == 2
    assert len(data["candidate_ids"]) == 2


def test_ingest_wrong_file_type(client):
    create = client.post("/jobs", json={"title": "Eng", "jd_raw": "Python required."})
    job_id = create.json()["id"]

    resp = client.post(
        f"/jobs/{job_id}/candidates",
        files={"file": ("data.txt", b"name,email\nAlice,a@b.com", "text/plain")},
    )
    assert resp.status_code == 400


def test_results_empty(client):
    create = client.post("/jobs", json={"title": "Eng", "jd_raw": "Python."})
    job_id = create.json()["id"]
    resp = client.get(f"/jobs/{job_id}/results")
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_evaluation_not_found(client):
    resp = client.get("/evaluations/nonexistent-id")
    assert resp.status_code == 404


# ── Auth ─────────────────────────────────────────────────────────────────────


def test_signup_returns_api_key(client):
    resp = client.post("/auth/signup", json={"email": "new@example.com"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["email"] == "new@example.com"
    assert data["api_key"].startswith("rh_")


def test_signup_duplicate_email_rejected(client):
    client.post("/auth/signup", json={"email": "dupe@example.com"})
    resp = client.post("/auth/signup", json={"email": "dupe@example.com"})
    assert resp.status_code == 409


def test_missing_api_key_rejected(client):
    resp = client.post(
        "/jobs", json={"title": "Eng", "jd_raw": "Python."}, headers={"X-API-Key": ""}
    )
    assert resp.status_code == 401


def test_invalid_api_key_rejected(client):
    resp = client.get("/jobs", headers={"X-API-Key": "rh_not-a-real-key"})
    assert resp.status_code == 401


def test_jobs_are_scoped_per_user(client, other_user_headers):
    mine = client.post("/jobs", json={"title": "Mine", "jd_raw": "Python."})
    job_id = mine.json()["id"]

    # The other user can't see it in their list...
    resp = client.get("/jobs", headers=other_user_headers)
    assert job_id not in [j["id"] for j in resp.json()]

    # ...and gets a 404 (not 403) fetching it directly, so existence isn't leaked.
    resp = client.get(f"/jobs/{job_id}", headers=other_user_headers)
    assert resp.status_code == 404

    # The owner can still see it.
    resp = client.get(f"/jobs/{job_id}")
    assert resp.status_code == 200


def test_upload_rejected_for_other_users_job(client, other_user_headers):
    mine = client.post("/jobs", json={"title": "Mine", "jd_raw": "Python."})
    job_id = mine.json()["id"]

    resp = client.post(
        f"/jobs/{job_id}/candidates",
        files={"file": ("c.csv", b"name,email\nAlice,a@b.com", "text/csv")},
        headers=other_user_headers,
    )
    assert resp.status_code == 404


def test_rotate_key_invalidates_old_key(client):
    old_key = client.headers["X-API-Key"]
    resp = client.post("/auth/rotate-key")
    assert resp.status_code == 200
    new_key = resp.json()["api_key"]
    assert new_key != old_key

    assert client.get("/jobs", headers={"X-API-Key": old_key}).status_code == 401
    assert client.get("/jobs", headers={"X-API-Key": new_key}).status_code == 200


def test_signup_grants_free_credits(client):
    resp = client.post("/auth/signup", json={"email": "credits@example.com"})
    assert resp.json()["credits"] == 3  # settings.signup_free_credits default


# ── Billing ──────────────────────────────────────────────────────────────────


def test_get_credits(client):
    resp = client.get("/billing/credits")
    assert resp.status_code == 200
    assert resp.json()["credits"] == 3


def test_request_credits_without_payment_link(client):
    resp = client.post("/billing/request-credits")
    assert resp.status_code == 200
    assert resp.json()["payment_link"] is None


def test_admin_grant_credits_disabled_when_unset(client, monkeypatch):
    # Pinned explicitly rather than relying on ambient config — a developer with
    # ADMIN_API_KEY set in their local .env would otherwise see a different result here.
    monkeypatch.setattr(settings, "admin_api_key", "")
    resp = client.post(
        "/billing/admin/grant-credits", json={"email": "test@example.com", "credits": 10}
    )
    assert resp.status_code == 501


def test_admin_grant_credits_rejects_wrong_key(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_api_key", "operator-secret")
    resp = client.post(
        "/billing/admin/grant-credits",
        json={"email": "test@example.com", "credits": 10},
        headers={"X-Admin-Key": "wrong"},
    )
    assert resp.status_code == 401


def test_admin_grant_credits_adds_credits(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_api_key", "operator-secret")
    resp = client.post(
        "/billing/admin/grant-credits",
        json={"email": "test@example.com", "credits": 10},
        headers={"X-Admin-Key": "operator-secret"},
    )
    assert resp.status_code == 200
    assert resp.json()["credits"] == 13  # 3 free signup credits + 10
    assert client.get("/billing/credits").json()["credits"] == 13


def test_admin_grant_credits_unknown_email(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_api_key", "operator-secret")
    resp = client.post(
        "/billing/admin/grant-credits",
        json={"email": "nobody@example.com", "credits": 10},
        headers={"X-Admin-Key": "operator-secret"},
    )
    assert resp.status_code == 404


def test_ingest_rejected_when_out_of_credits(client):
    create = client.post("/jobs", json={"title": "Eng", "jd_raw": "Python required."})
    job_id = create.json()["id"]

    # Default test user has 3 free credits; a 4-row batch exceeds that.
    csv_bytes = b"name,email\n" + b"\n".join(f"P{i},p{i}@test.com".encode() for i in range(4))
    resp = client.post(
        f"/jobs/{job_id}/candidates",
        files={"file": ("c.csv", csv_bytes, "text/csv")},
    )
    assert resp.status_code == 402


def test_ingest_deducts_credits(client):
    create = client.post("/jobs", json={"title": "Eng", "jd_raw": "Python required."})
    job_id = create.json()["id"]

    csv_bytes = b"name,email\nAlice,alice@test.com\nBob,bob@test.com\n"
    resp = client.post(
        f"/jobs/{job_id}/candidates", files={"file": ("c.csv", csv_bytes, "text/csv")}
    )
    assert resp.status_code == 202

    assert client.get("/billing/credits").json()["credits"] == 1  # 3 - 2


# ── Candidate lifecycle ────────────────────────────────────────────────────────


def test_delete_candidate(client):
    create = client.post("/jobs", json={"title": "Eng", "jd_raw": "Python required."})
    job_id = create.json()["id"]

    ingest = client.post(
        f"/jobs/{job_id}/candidates",
        files={"file": ("c.csv", b"name,email\nAlice,alice@test.com\n", "text/csv")},
    )
    candidate_id = ingest.json()["candidate_ids"][0]

    resp = client.delete(f"/jobs/{job_id}/candidates/{candidate_id}")
    assert resp.status_code == 204

    results = client.get(f"/jobs/{job_id}/results").json()
    assert candidate_id not in [r["candidate"]["id"] for r in results]


def test_delete_candidate_not_found(client):
    create = client.post("/jobs", json={"title": "Eng", "jd_raw": "Python required."})
    job_id = create.json()["id"]
    resp = client.delete(f"/jobs/{job_id}/candidates/nonexistent-id")
    assert resp.status_code == 404


def test_delete_all_candidates(client):
    create = client.post("/jobs", json={"title": "Eng", "jd_raw": "Python required."})
    job_id = create.json()["id"]

    csv_bytes = b"name,email\nAlice,alice@test.com\nBob,bob@test.com\n"
    client.post(f"/jobs/{job_id}/candidates", files={"file": ("c.csv", csv_bytes, "text/csv")})

    resp = client.delete(f"/jobs/{job_id}/candidates")
    assert resp.status_code == 200
    assert resp.json()["deleted_count"] == 2

    results = client.get(f"/jobs/{job_id}/results").json()
    assert results == []

    # Job itself must survive so a fresh batch can be uploaded to it.
    assert client.get(f"/jobs/{job_id}").status_code == 200


def test_delete_all_candidates_empty(client):
    create = client.post("/jobs", json={"title": "Eng", "jd_raw": "Python required."})
    job_id = create.json()["id"]

    resp = client.delete(f"/jobs/{job_id}/candidates")
    assert resp.status_code == 200
    assert resp.json()["deleted_count"] == 0


def test_delete_all_candidates_job_not_found(client):
    resp = client.delete("/jobs/nonexistent-id/candidates")
    assert resp.status_code == 404


def test_upload_candidate_resume_file(client):
    create = client.post("/jobs", json={"title": "Eng", "jd_raw": "Python required."})
    job_id = create.json()["id"]

    ingest = client.post(
        f"/jobs/{job_id}/candidates",
        files={"file": ("c.csv", b"name,email\nAlice,alice@test.com\n", "text/csv")},
    )
    candidate_id = ingest.json()["candidate_ids"][0]

    resp = client.post(
        f"/jobs/{job_id}/candidates/{candidate_id}/resume",
        files={"file": ("resume.txt", b"5 years Python experience.", "text/plain")},
    )
    assert resp.status_code == 200
    assert resp.json()["queued_count"] == 1


def test_upload_candidate_resume_rejects_bad_extension(client):
    create = client.post("/jobs", json={"title": "Eng", "jd_raw": "Python required."})
    job_id = create.json()["id"]
    ingest = client.post(
        f"/jobs/{job_id}/candidates",
        files={"file": ("c.csv", b"name,email\nAlice,alice@test.com\n", "text/csv")},
    )
    candidate_id = ingest.json()["candidate_ids"][0]

    resp = client.post(
        f"/jobs/{job_id}/candidates/{candidate_id}/resume",
        files={"file": ("resume.docx", b"not a real docx", "application/msword")},
    )
    assert resp.status_code == 400


def test_ingest_rejects_corrupt_xlsx_signature(client):
    create = client.post("/jobs", json={"title": "Eng", "jd_raw": "Python required."})
    job_id = create.json()["id"]
    resp = client.post(
        f"/jobs/{job_id}/candidates",
        files={
            "file": (
                "candidates.xlsx",
                b"not actually a zip",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert resp.status_code == 422


def test_export_results_csv(client):
    create = client.post("/jobs", json={"title": "Eng", "jd_raw": "Python required."})
    job_id = create.json()["id"]
    client.post(
        f"/jobs/{job_id}/candidates",
        files={"file": ("c.csv", b"name,email\nAlice,alice@test.com\n", "text/csv")},
    )

    resp = client.get(f"/jobs/{job_id}/results/export")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "Alice" in resp.text


def test_update_job(client):
    create = client.post("/jobs", json={"title": "Eng", "jd_raw": "Python required."})
    job_id = create.json()["id"]

    resp = client.patch(f"/jobs/{job_id}", json={"title": "Senior Eng", "weights": {"judge": 0.6}})
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "Senior Eng"
    assert data["weights"] == {"judge": 0.6}
    assert data["jd_raw"] == "Python required."  # untouched


def test_update_job_not_found(client):
    resp = client.patch("/jobs/nonexistent-id", json={"title": "X"})
    assert resp.status_code == 404


def test_parse_jd_preview_does_not_create_job(client):
    resp = client.post("/jobs/parse-jd", json={"jd_raw": "Need Python and SQL, 3+ years."})
    assert resp.status_code == 200
    body = resp.json()
    assert "required_skills" in body
    assert client.get("/jobs").json() == []  # no job row was created


def test_create_job_with_jd_parsed_override(client):
    override = {
        "title": "Custom Title",
        "required_skills": ["rust"],
        "preferred_skills": [],
        "min_yoe": 5.0,
        "location": "Remote",
        "must_haves": [],
    }
    resp = client.post(
        "/jobs",
        json={"title": "Eng", "jd_raw": "irrelevant", "jd_parsed_override": override},
    )
    assert resp.status_code == 201
    assert resp.json()["jd_parsed"]["required_skills"] == ["rust"]


def test_update_job_cross_user_404(client, other_user_headers):
    create = client.post("/jobs", json={"title": "Eng", "jd_raw": "Python required."})
    job_id = create.json()["id"]

    resp = client.patch(f"/jobs/{job_id}", json={"title": "Hijacked"}, headers=other_user_headers)
    assert resp.status_code == 404


def test_list_get_update_candidates(client):
    create = client.post("/jobs", json={"title": "Eng", "jd_raw": "Python required."})
    job_id = create.json()["id"]
    client.post(
        f"/jobs/{job_id}/candidates",
        files={"file": ("c.csv", b"name,email\nAlice,alice@test.com\n", "text/csv")},
    )

    listed = client.get(f"/jobs/{job_id}/candidates")
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    candidate_id = listed.json()[0]["id"]

    got = client.get(f"/jobs/{job_id}/candidates/{candidate_id}")
    assert got.status_code == 200
    assert got.json()["name"] == "Alice"

    updated = client.patch(
        f"/jobs/{job_id}/candidates/{candidate_id}",
        json={"location": "Remote", "yoe": 7},
    )
    assert updated.status_code == 200
    assert updated.json()["location"] == "Remote"
    assert updated.json()["yoe"] == 7


def test_get_candidate_not_found(client):
    create = client.post("/jobs", json={"title": "Eng", "jd_raw": "Python required."})
    job_id = create.json()["id"]
    resp = client.get(f"/jobs/{job_id}/candidates/nonexistent-id")
    assert resp.status_code == 404


def test_update_and_delete_evaluation(client):
    create = client.post("/jobs", json={"title": "Eng", "jd_raw": "Python required."})
    job_id = create.json()["id"]
    client.post(
        f"/jobs/{job_id}/candidates",
        files={"file": ("c.csv", b"name,email\nAlice,alice@test.com\n", "text/csv")},
    )
    candidate_id = client.get(f"/jobs/{job_id}/candidates").json()[0]["id"]

    # No worker running in this test process, so manually create the evaluation this
    # endpoint is meant to override — mirrors how workers/tasks.py writes one.
    from app.models import Evaluation

    import asyncio

    from app import db as db_module

    async def _seed():
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

        factory = async_sessionmaker(db_module.engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as session:
            ev = Evaluation(candidate_id=candidate_id, job_id=job_id, score=0.5, verdict="Maybe")
            session.add(ev)
            await session.commit()
            await session.refresh(ev)
            return ev.id

    eval_id = asyncio.run(_seed())

    resp = client.patch(f"/evaluations/{eval_id}", json={"verdict": "Fit", "score": 0.9})
    assert resp.status_code == 200
    assert resp.json()["verdict"] == "Fit"
    assert resp.json()["score"] == 0.9

    resp = client.delete(f"/evaluations/{eval_id}")
    assert resp.status_code == 204
    assert client.get(f"/evaluations/{eval_id}").status_code == 404


def test_admin_users_crud_requires_admin_key(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_api_key", "")
    assert client.get("/admin/users").status_code == 501

    monkeypatch.setattr(settings, "admin_api_key", "operator-secret")
    assert client.get("/admin/users").status_code == 401
    assert client.get("/admin/users", headers={"X-Admin-Key": "wrong"}).status_code == 401


def test_admin_users_list_get_update_delete(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_api_key", "operator-secret")
    headers = {"X-Admin-Key": "operator-secret"}

    listed = client.get("/admin/users", headers=headers)
    assert listed.status_code == 200
    user_id = next(u["id"] for u in listed.json() if u["email"] == "test@example.com")

    got = client.get(f"/admin/users/{user_id}", headers=headers)
    assert got.status_code == 200
    assert got.json()["email"] == "test@example.com"

    updated = client.patch(f"/admin/users/{user_id}", json={"credits": 42}, headers=headers)
    assert updated.status_code == 200
    assert updated.json()["credits"] == 42

    deleted = client.delete(f"/admin/users/{user_id}", headers=headers)
    assert deleted.status_code == 204
    assert client.get(f"/admin/users/{user_id}", headers=headers).status_code == 404


def test_admin_reset_api_key(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_api_key", "operator-secret")
    headers = {"X-Admin-Key": "operator-secret"}

    listed = client.get("/admin/users", headers=headers)
    user_id = next(u["id"] for u in listed.json() if u["email"] == "test@example.com")

    resp = client.post(f"/admin/users/{user_id}/reset-api-key", headers=headers)
    assert resp.status_code == 200
    new_key = resp.json()["api_key"]
    assert new_key.startswith("rh_")

    # Old key (used throughout this test via the `client` fixture's default header) no
    # longer authenticates.
    stale = client.get("/auth/me")
    assert stale.status_code == 401

    fresh = client.get("/auth/me", headers={"X-API-Key": new_key})
    assert fresh.status_code == 200
