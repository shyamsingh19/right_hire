"""Thin async httpx wrappers around the Right Hire FastAPI backend.

Centralizes base URL, timeouts, and error propagation so state modules never
build request URLs inline. Every route requires the X-API-Key header (see
app/auth.py) — callers pass the caller's key through, sourced from
AppState.api_key.
"""

from __future__ import annotations

import httpx

from right_hire_ui.config import API_BASE


class ApiError(Exception):
    """Raised with the backend's own error message (from {"detail": ...}) instead of
    the raw httpx exception repr, so the UI can show users something actionable."""


def _headers(api_key: str) -> dict[str, str]:
    return {"X-API-Key": api_key}


async def _raise_for_status(resp: httpx.Response) -> None:
    if resp.is_success:
        return
    try:
        detail = resp.json().get("detail", resp.text)
    except Exception:
        detail = resp.text
    raise ApiError(str(detail))


async def signup(email: str) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{API_BASE}/auth/signup", json={"email": email}, timeout=10)
        await _raise_for_status(resp)
        return resp.json()


async def get_me(api_key: str) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{API_BASE}/auth/me", headers=_headers(api_key), timeout=10)
        await _raise_for_status(resp)
        return resp.json()


async def rotate_key(api_key: str) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{API_BASE}/auth/rotate-key", headers=_headers(api_key), timeout=10
        )
        await _raise_for_status(resp)
        return resp.json()


async def get_credits(api_key: str) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{API_BASE}/billing/credits", headers=_headers(api_key), timeout=10
        )
        await _raise_for_status(resp)
        return resp.json()


async def request_credits(api_key: str) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{API_BASE}/billing/request-credits", headers=_headers(api_key), timeout=10
        )
        await _raise_for_status(resp)
        return resp.json()


async def get_jobs(api_key: str) -> list[dict]:
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{API_BASE}/jobs", headers=_headers(api_key), timeout=10)
        await _raise_for_status(resp)
        return resp.json()


async def create_job(
    api_key: str, title: str, jd_raw: str, fit_threshold: float, maybe_threshold: float
) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{API_BASE}/jobs",
            headers=_headers(api_key),
            json={
                "title": title,
                "jd_raw": jd_raw,
                "thresholds": {"fit": fit_threshold, "maybe": maybe_threshold},
            },
            timeout=60,
        )
        await _raise_for_status(resp)
        return resp.json()


async def delete_job(api_key: str, job_id: str) -> None:
    async with httpx.AsyncClient() as client:
        resp = await client.delete(
            f"{API_BASE}/jobs/{job_id}", headers=_headers(api_key), timeout=30
        )
        await _raise_for_status(resp)


async def cancel_pending_candidates(api_key: str, job_id: str) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{API_BASE}/jobs/{job_id}/candidates/cancel-pending",
            headers=_headers(api_key),
            timeout=15,
        )
        await _raise_for_status(resp)
        return resp.json()


async def preview_candidates(
    api_key: str, job_id: str, filename: str, data: bytes, content_type: str
) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{API_BASE}/jobs/{job_id}/candidates/preview",
            headers=_headers(api_key),
            files={"file": (filename, data, content_type)},
            timeout=30,
        )
        await _raise_for_status(resp)
        return resp.json()


async def upload_candidates(
    api_key: str,
    job_id: str,
    filename: str,
    data: bytes,
    content_type: str,
    column_mapping: dict | None = None,
) -> dict:
    import json as _json

    async with httpx.AsyncClient() as client:
        data_fields: dict = {"file": (filename, data, content_type)}
        extra: dict = {}
        if column_mapping is not None:
            extra["column_mapping"] = (None, _json.dumps(column_mapping), "text/plain")
        resp = await client.post(
            f"{API_BASE}/jobs/{job_id}/candidates",
            headers=_headers(api_key),
            files={**data_fields, **extra},
            timeout=30,
        )
        await _raise_for_status(resp)
        return resp.json()


async def get_results(
    api_key: str, job_id: str, verdict_filter: str, offset: int = 0, limit: int = 50
) -> list[dict]:
    params: dict = {"offset": offset, "limit": limit}
    if verdict_filter != "All":
        params["verdict"] = verdict_filter
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{API_BASE}/jobs/{job_id}/results",
            headers=_headers(api_key),
            params=params,
            timeout=30,
        )
        await _raise_for_status(resp)
        return resp.json()


async def upload_resume(
    api_key: str, job_id: str, candidate_id: str, filename: str, data: bytes, content_type: str
) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{API_BASE}/jobs/{job_id}/candidates/{candidate_id}/resume",
            headers=_headers(api_key),
            files={"file": (filename, data, content_type)},
            timeout=60,
        )
        await _raise_for_status(resp)
        return resp.json()


async def delete_candidate(api_key: str, job_id: str, candidate_id: str) -> None:
    async with httpx.AsyncClient() as client:
        resp = await client.delete(
            f"{API_BASE}/jobs/{job_id}/candidates/{candidate_id}",
            headers=_headers(api_key),
            timeout=30,
        )
        await _raise_for_status(resp)


async def export_results_csv(api_key: str, job_id: str, verdict_filter: str) -> str:
    """Returns the CSV body as text. Fetched here rather than linked directly because the
    export route needs the X-API-Key header, which a plain browser <a href> can't send."""
    params = {} if verdict_filter == "All" else {"verdict": verdict_filter}
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{API_BASE}/jobs/{job_id}/results/export",
            headers=_headers(api_key),
            params=params,
            timeout=60,
        )
        await _raise_for_status(resp)
        return resp.text


def infer_content_type(filename: str) -> str:
    if filename.endswith(".csv"):
        return "text/csv"
    return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def infer_resume_content_type(filename: str) -> str:
    if filename.endswith(".pdf"):
        return "application/pdf"
    return "text/plain"
