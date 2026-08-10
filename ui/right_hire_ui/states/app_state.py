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

    user_email: str = ""
    is_loading_account: bool = False

    # Billing — 1 credit = 1 candidate evaluated (see app/api/billing.py)
    credits: int = 0
    credits_message: str = ""
    payment_link: str = ""

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
        self.credits = 0
        self.user_email = ""
        self.credits_message = ""
        self.payment_link = ""

    async def rotate_key(self):
        """Swap in a fresh key. The old one stops working the moment this returns, so the
        new one is saved to localStorage immediately rather than shown for copying."""
        if not self.api_key:
            return
        try:
            result = await api_client.rotate_key(self.api_key)
            self.api_key = result["api_key"]
            yield rx.toast.success("API key rotated — the previous key no longer works.")
        except (httpx.HTTPError, api_client.ApiError) as e:
            yield rx.toast.error(f"Could not rotate key: {e}")

    async def load_credits(self) -> None:
        if not self.api_key:
            self.credits = 0
            return
        try:
            data = await api_client.get_me(self.api_key)
            self.credits = data["credits"]
            self.user_email = data["email"]
        except (httpx.HTTPError, api_client.ApiError):
            self.credits = 0

    async def request_credits(self):
        if not self.api_key:
            return
        try:
            result = await api_client.request_credits(self.api_key)
            self.credits_message = result.get("message", "")
            self.payment_link = result.get("payment_link") or ""
            yield rx.toast.info(self.credits_message)
        except (httpx.HTTPError, api_client.ApiError) as e:
            yield rx.toast.error(str(e))

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
            self.user_email = result.get("email", "")
            self.credits = result.get("credits", 0)
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

    async def load_page_data(self) -> None:
        """on_load for every page — loads jobs + account info before rendering the sidebar."""
        self.is_loading_account = True
        yield
        await self.load_jobs()
        await self.load_credits()
        self.is_loading_account = False

    @rx.var
    def job_options(self) -> list[tuple[str, str]]:
        return [(j["id"], f"{j['title']} — {j['id']}") for j in self.jobs]

    @rx.var
    def is_authenticated(self) -> bool:
        return bool(self.api_key)
