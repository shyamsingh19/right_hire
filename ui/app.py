"""Streamlit UI for Right Hire ATS Checker."""
from __future__ import annotations

import configparser
import os
from pathlib import Path

import requests
import streamlit as st

_config = configparser.ConfigParser()
_config.read(Path(__file__).resolve().parent.parent / "config.ini")

API_BASE = os.getenv("API_BASE") or _config.get("ui", "api_base", fallback="http://localhost:8001")


def _fetch_jobs() -> list[dict]:
    try:
        resp = requests.get(f"{API_BASE}/jobs", timeout=10)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException:
        return []


def _job_selectbox(jobs: list[dict], key: str) -> str | None:
    return st.selectbox(
        "Job",
        options=[j["id"] for j in jobs],
        format_func=lambda jid: next((f"{j['title']} — {jid}" for j in jobs if j["id"] == jid), jid),
        key=key,
    )

st.set_page_config(page_title="Right Hire", page_icon="", layout="wide")
st.title("Right Hire — ATS Checker")

page = st.sidebar.radio("Navigate", ["Create Job", "Upload Candidates", "Results"])

# ── Page 1: Create Job ───────────────────────────────────────────────────────
if page == "Create Job":
    st.header("Create a New Job")

    with st.form("create_job_form"):
        title = st.text_input("Job Title", placeholder="Senior Python Engineer")
        jd_raw = st.text_area("Job Description", height=300, placeholder="Paste the full JD here...")
        fit_threshold = st.slider("Fit threshold", 0.0, 1.0, 0.70, 0.05)
        maybe_threshold = st.slider("Maybe threshold", 0.0, 1.0, 0.40, 0.05)
        submitted = st.form_submit_button("Create Job")

    if submitted:
        if not title or not jd_raw:
            st.error("Title and job description are required.")
        else:
            with st.spinner("Parsing JD with LLM..."):
                try:
                    resp = requests.post(f"{API_BASE}/jobs", json={
                        "title": title,
                        "jd_raw": jd_raw,
                        "thresholds": {"fit": fit_threshold, "maybe": maybe_threshold},
                    }, timeout=60)
                    resp.raise_for_status()
                    job = resp.json()
                    st.success(f"Job created! ID: `{job['id']}`")
                    st.json(job.get("jd_parsed", {}))
                except requests.RequestException as e:
                    st.error(f"API error: {e}")

# ── Page 2: Upload Candidates ────────────────────────────────────────────────
elif page == "Upload Candidates":
    st.header("Upload Candidates")

    jobs = _fetch_jobs()
    if not jobs:
        st.warning("No jobs found. Create one on the 'Create Job' page first.")
        job_id = None
    else:
        job_id = _job_selectbox(jobs, key="upload_job_id")
    uploaded = st.file_uploader("Candidate file (.xlsx or .csv)", type=["xlsx", "csv"])

    if st.button("Upload & Enqueue") and job_id and uploaded:
        content_type = (
            "text/csv"
            if uploaded.name.endswith(".csv")
            else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        with st.spinner("Uploading..."):
            try:
                resp = requests.post(
                    f"{API_BASE}/jobs/{job_id}/candidates",
                    files={"file": (uploaded.name, uploaded.getvalue(), content_type)},
                    timeout=30,
                )
                resp.raise_for_status()
                data = resp.json()
                st.success(f"Enqueued {data['queued_count']} candidates for evaluation.")
            except requests.RequestException as e:
                st.error(f"Upload failed: {e}")

    st.markdown("---")
    st.markdown("""
**Expected columns** (case-insensitive, .xlsx or .csv):

| Column | Required |
|---|---|
| `name` | Yes |
| `email` | Yes |
| `resume_url` | Yes (Google Drive or direct link) |
| `yoe` | No |
| `location` | No |
""")

# ── Page 3: Results ──────────────────────────────────────────────────────────
elif page == "Results":
    st.header("Evaluation Results")

    jobs = _fetch_jobs()
    if not jobs:
        st.warning("No jobs found. Create one on the 'Create Job' page first.")
        job_id = None
    else:
        job_id = _job_selectbox(jobs, key="results_job_id")
    verdict_filter = st.selectbox("Filter by verdict", ["All", "Fit", "Maybe", "Reject"])

    if st.button("Load Results") and job_id:
        params = {}
        if verdict_filter != "All":
            params["verdict"] = verdict_filter

        with st.spinner("Loading..."):
            try:
                resp = requests.get(
                    f"{API_BASE}/jobs/{job_id}/results",
                    params=params,
                    timeout=30,
                )
                resp.raise_for_status()
                results = resp.json()
            except requests.RequestException as e:
                st.error(f"API error: {e}")
                results = []

        if not results:
            st.info("No results found.")
        else:
            _BADGE = {"Fit": "🟢", "Maybe": "🟡", "Reject": "🔴"}

            for item in results:
                c = item["candidate"]
                e = item.get("evaluation")
                verdict = e["verdict"] if e else c["status"]
                badge = _BADGE.get(verdict, "⚪")
                score_display = f"{e['score']:.2f}" if e and e.get("score") is not None else "N/A"

                with st.expander(f"{badge} {c['name'] or 'Unknown'} — {verdict} (score: {score_display})"):
                    col1, col2 = st.columns(2)
                    with col1:
                        st.markdown(f"**Email:** {c.get('email', 'N/A')}")
                        st.markdown(f"**YOE:** {c.get('yoe', 'N/A')}")
                        st.markdown(f"**Location:** {c.get('location', 'N/A')}")
                    with col2:
                        if e:
                            st.markdown(
                                f"**Score:** {e['score']:.3f}"
                                if e.get("score") is not None
                                else "**Score:** N/A"
                            )
                            st.markdown(f"**Model:** {e.get('model_used', 'N/A')}")

                    if e and e.get("rubric"):
                        st.markdown("**Rubric scores:**")
                        for criterion, score in e["rubric"].items():
                            reason = (e.get("reasons") or {}).get(criterion, "")
                            st.markdown(f"- **{criterion}:** {score:.2f} — {reason}")
