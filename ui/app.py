"""Streamlit UI for Right Hire ATS Checker."""
from __future__ import annotations

import os

import requests
import streamlit as st

API_BASE = os.getenv("API_BASE", "http://localhost:8000")

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

    job_id = st.text_input("Job ID", placeholder="Paste the job ID from Create Job")
    uploaded = st.file_uploader("Candidate Excel (.xlsx)", type=["xlsx"])

    if st.button("Upload & Enqueue") and job_id and uploaded:
        with st.spinner("Uploading..."):
            try:
                resp = requests.post(
                    f"{API_BASE}/jobs/{job_id}/candidates",
                    files={"file": (uploaded.name, uploaded.getvalue(),
                                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
                    timeout=30,
                )
                resp.raise_for_status()
                data = resp.json()
                st.success(f"Enqueued {data['queued_count']} candidates for evaluation.")
            except requests.RequestException as e:
                st.error(f"Upload failed: {e}")

    st.markdown("---")
    st.markdown("""
**Expected Excel columns** (case-insensitive):

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

    job_id = st.text_input("Job ID")
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

                with st.expander(f"{badge} {c['name'] or 'Unknown'} — {verdict} (score: {e['score']:.2f if e and e['score'] else 'N/A'})"):
                    col1, col2 = st.columns(2)
                    with col1:
                        st.markdown(f"**Email:** {c.get('email', 'N/A')}")
                        st.markdown(f"**YOE:** {c.get('yoe', 'N/A')}")
                        st.markdown(f"**Location:** {c.get('location', 'N/A')}")
                    with col2:
                        if e:
                            st.markdown(f"**Score:** {e['score']:.3f}" if e.get("score") else "**Score:** N/A")
                            st.markdown(f"**Model:** {e.get('model_used', 'N/A')}")

                    if e and e.get("rubric"):
                        st.markdown("**Rubric scores:**")
                        for criterion, score in e["rubric"].items():
                            reason = (e.get("reasons") or {}).get(criterion, "")
                            st.markdown(f"- **{criterion}:** {score:.2f} — {reason}")
