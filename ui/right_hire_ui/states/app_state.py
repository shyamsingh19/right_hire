from __future__ import annotations

import httpx
import reflex as rx

from right_hire_ui import api_client


class AppState(rx.State):
    """Shared jobs cache used by every page's job picker."""

    jobs: list[dict] = []  # noqa: RUF012 — Reflex rx.State vars use plain mutable defaults

    async def load_jobs(self) -> None:
        try:
            self.jobs = await api_client.get_jobs()
        except httpx.HTTPError:
            self.jobs = []

    @rx.var
    def job_options(self) -> list[tuple[str, str]]:
        return [(j["id"], f"{j['title']} — {j['id']}") for j in self.jobs]
