"""API integration tests using TestClient + FakeLLMProvider + SQLite."""
from __future__ import annotations

import io

import openpyxl
import pytest


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


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_create_job(client):
    resp = client.post("/jobs", json={
        "title": "Senior Python Engineer",
        "jd_raw": "Looking for a Python expert with 5+ years. Required: Python, PostgreSQL.",
    })
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

    xlsx = _make_excel([
        {"name": "Alice", "email": "alice@test.com", "yoe": 5, "location": "SF", "resume_url": ""},
        {"name": "Bob", "email": "bob@test.com", "yoe": 2, "location": "NY", "resume_url": ""},
    ])
    resp = client.post(
        f"/jobs/{job_id}/candidates",
        files={"file": ("candidates.xlsx", xlsx, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert resp.status_code == 202
    data = resp.json()
    assert data["queued_count"] == 2
    assert len(data["candidate_ids"]) == 2


def test_ingest_candidates_csv(client):
    create = client.post("/jobs", json={"title": "Eng", "jd_raw": "Python required."})
    job_id = create.json()["id"]

    csv_bytes = (
        b"name,email,yoe,location,resume_url\n"
        b"Alice,alice@test.com,5,SF,\n"
        b"Bob,bob@test.com,2,NY,\n"
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
