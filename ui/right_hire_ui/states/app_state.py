from __future__ import annotations

import httpx
import reflex as rx

from right_hire_ui import api_client


class AppState(rx.State):
    """Shared jobs cache + API key used by every page."""

    jobs: list[dict] = []  # noqa: RUF012 — Reflex rx.State vars use plain mutable defaults

    # Persisted client-side (browser localStorage) so the key survives page reloads.
    api_key: str = rx.LocalStorage(name="right_hire_api_key")

    signup_email: str = ""
    key_input: str = ""
    auth_error: str = ""
    is_authenticating: bool = False

    def set_signup_email(self, value: str) -> None:
        self.signup_email = value

    def set_key_input(self, value: str) -> None:
        self.key_input = value

    def use_existing_key(self) -> None:
        """For a returning user pasting a key they already have (e.g. on a new browser)."""
        if self.key_input.strip():
            self.api_key = self.key_input.strip()
            self.key_input = ""
            self.auth_error = ""

    def log_out(self) -> None:
        self.api_key = ""
        self.jobs = []

    async def signup(self):
        self.auth_error = ""
        if not self.signup_email.strip():
            self.auth_error = "Enter an email to get an API key."
            return

        self.is_authenticating = True
        yield

        try:
            result = await api_client.signup(self.signup_email.strip())
            self.api_key = result["api_key"]
            self.signup_email = ""
            yield rx.toast.success("Signed up — API key saved in this browser.")
        except (httpx.HTTPError, api_client.ApiError) as e:
            self.auth_error = str(e)
            yield rx.toast.error(self.auth_error)
        finally:
            self.is_authenticating = False

    async def load_jobs(self) -> None:
        if not self.api_key:
            self.jobs = []
            return
        try:
            self.jobs = await api_client.get_jobs(self.api_key)
        except (httpx.HTTPError, api_client.ApiError):
            self.jobs = []

    @rx.var
    def job_options(self) -> list[tuple[str, str]]:
        return [(j["id"], f"{j['title']} — {j['id']}") for j in self.jobs]

    @rx.var
    def is_authenticated(self) -> bool:
        return bool(self.api_key)
