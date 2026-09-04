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

    # Persisted so sidebar shows correct values instantly on page load without a flash.
    # LocalStorage always deserializes as str, so credits is kept as str here.
    user_email: str = rx.LocalStorage(name="right_hire_user_email")
    credits: str = rx.LocalStorage(name="right_hire_credits")
    is_loading_account: bool = False
    credits_message: str = ""
    payment_link: str = ""
    support_contact: str = ""
    credit_requests: list[dict] = []  # noqa: RUF012
    is_loading_jobs: bool = False
    is_rotating_key: bool = False
    is_requesting_credits: bool = False

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
        self.credits = "0"
        self.user_email = ""
        self.credits_message = ""
        self.payment_link = ""
        self.support_contact = ""
        self.credit_requests = []

    async def rotate_key(self):
        """Swap in a fresh key. The old one stops working the moment this returns, so the
        new one is saved to localStorage immediately rather than shown for copying."""
        if not self.api_key:
            return
        self.is_rotating_key = True
        yield
        try:
            result = await api_client.rotate_key(self.api_key)
            self.api_key = result["api_key"]
            yield rx.toast.success("API key rotated — the previous key no longer works.")
        except (httpx.HTTPError, api_client.ApiError) as e:
            yield rx.toast.error(f"Could not rotate key: {e}")
        finally:
            self.is_rotating_key = False

    async def load_credits(self) -> None:
        if not self.api_key:
            self.credits = "0"
            return
        try:
            data = await api_client.get_me(self.api_key)
            self.credits = str(data["credits"])
            self.user_email = data["email"]
        except (httpx.HTTPError, api_client.ApiError):
            pass  # keep cached value on network error

    async def request_credits(self):
        if not self.api_key:
            return
        self.is_requesting_credits = True
        yield
        try:
            result = await api_client.request_credits(self.api_key)
            self.credits_message = result.get("message", "")
            self.payment_link = result.get("payment_link") or ""
            self.support_contact = result.get("support_contact") or ""
            yield rx.toast.info(self.credits_message)
            await self.load_credit_requests()
        except (httpx.HTTPError, api_client.ApiError) as e:
            yield rx.toast.error(str(e))
        finally:
            self.is_requesting_credits = False

    async def load_credit_requests(self) -> None:
        if not self.api_key:
            self.credit_requests = []
            return
        try:
            self.credit_requests = await api_client.get_credit_requests(self.api_key)
        except (httpx.HTTPError, api_client.ApiError):
            pass  # keep whatever was already shown on a transient network error

    @rx.var
    def has_pending_credit_request(self) -> bool:
        return any(r.get("status") == "pending" for r in self.credit_requests)

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
            self.credits = str(result.get("credits", 0))
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

    async def load_page_data(self):
        """on_load for every page — jobs list is always fetched fresh; credits come from
        LocalStorage immediately (no flash) and are refreshed in the background."""
        self.is_loading_jobs = True
        yield
        await self.load_jobs()
        self.is_loading_jobs = False
        # Refresh account data in background — cached values already visible from LocalStorage
        if self.api_key:
            self.is_loading_account = True
            yield
            await self.load_credits()
            await self.load_credit_requests()
            self.is_loading_account = False

    @rx.var
    def job_options(self) -> list[tuple[str, str]]:
        """Label is the title only — the id stays the option's value, never shown."""
        return [(j["id"], j["title"]) for j in self.jobs]

    @rx.var
    def user_initials(self) -> str:
        return (self.user_email[:2] or "RH").upper()

    @rx.var
    def is_authenticated(self) -> bool:
        return bool(self.api_key)
