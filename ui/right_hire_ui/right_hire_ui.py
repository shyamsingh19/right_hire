"""Reflex app entry point — registers the three pages (Create Job, Upload
Candidates, Results), replacing the old Streamlit `st.sidebar.radio` switch."""

from __future__ import annotations

import reflex as rx

from right_hire_ui.components.theme import STYLESHEETS, get_theme
from right_hire_ui.pages.create_job import create_job_page
from right_hire_ui.pages.results import results_page
from right_hire_ui.pages.upload_candidates import upload_candidates_page
from right_hire_ui.states.create_job_state import CreateJobState
from right_hire_ui.states.results_state import ResultsState
from right_hire_ui.states.upload_state import UploadState

app = rx.App(
    theme=get_theme(),
    stylesheets=STYLESHEETS,
    toaster=rx.toast.provider(
        position="bottom-right",
        close_button=True,
        rich_colors=True,
        offset="1.5rem",
        toast_options=rx.toast.options(style={"maxWidth": "min(24rem, calc(100vw - 3rem))"}),
    ),
)

app.add_page(
    create_job_page,
    route="/",
    title="Right Hire — Create Job",
    on_load=CreateJobState.load_page_data,
)
app.add_page(
    upload_candidates_page,
    route="/upload",
    title="Right Hire — Upload Candidates",
    on_load=UploadState.load_page_data,
)
app.add_page(
    results_page,
    route="/results",
    title="Right Hire — Results",
    on_load=ResultsState.load_page_data,
)
