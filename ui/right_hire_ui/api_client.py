"""Thin async httpx wrappers around the Right Hire FastAPI backend.

Centralizes base URL, timeouts, and error propagation so state modules never
build request URLs inline. Mirrors the exact requests made by the old
Streamlit app (same endpoints, params, and timeouts).
"""

from __future__ import annotations

import httpx

from right_hire_ui.config import API_BASE


async def get_jobs() -> list[dict]:
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{API_BASE}/jobs", timeout=10)
        resp.raise_for_status()
        return resp.json()


async def create_job(title: str, jd_raw: str, fit_threshold: float, maybe_threshold: float) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{API_BASE}/jobs",
            json={
                "title": title,
                "jd_raw": jd_raw,
                "thresholds": {"fit": fit_threshold, "maybe": maybe_threshold},
            },
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()


async def upload_candidates(job_id: str, filename: str, data: bytes, content_type: str) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{API_BASE}/jobs/{job_id}/candidates",
            files={"file": (filename, data, content_type)},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()


async def get_results(job_id: str, verdict_filter: str) -> list[dict]:
    params = {} if verdict_filter == "All" else {"verdict": verdict_filter}
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{API_BASE}/jobs/{job_id}/results", params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()


def infer_content_type(filename: str) -> str:
    if filename.endswith(".csv"):
        return "text/csv"
    return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
