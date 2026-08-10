from __future__ import annotations

import httpx
import reflex as rx

from right_hire_ui import api_client
from right_hire_ui.states.app_state import AppState


class CreateJobState(AppState):
    step: int = 1  # 1 = input JD, 2 = review & calibrate

    title: str = ""
    jd_raw: str = ""

    # Populated from POST /jobs/parse-jd, then editable before job creation.
    parsed_title: str = ""
    required_skills: list[str] = []  # noqa: RUF012
    preferred_skills: list[str] = []  # noqa: RUF012
    new_skill_input: str = ""
    min_yoe: float = 0.0
    location: str = ""
    must_haves: list[str] = []  # noqa: RUF012

    skill_weight: float = 0.30
    cosine_weight: float = 0.20
    judge_weight: float = 0.50

    fit_threshold: float = 0.70
    maybe_threshold: float = 0.40

    is_parsing: bool = False
    is_submitting: bool = False
    error_message: str = ""
    created_job_id: str = ""
    created_job_jd_parsed: dict = {}  # noqa: RUF012

    def set_title(self, value: str) -> None:
        self.title = value

    def set_jd_raw(self, value: str) -> None:
        self.jd_raw = value

    def set_new_skill_input(self, value: str) -> None:
        self.new_skill_input = value

    def set_min_yoe(self, value: list[float]) -> None:
        self.min_yoe = value[0]

    def set_location(self, value: str) -> None:
        self.location = value

    def add_required_skill(self) -> None:
        skill = self.new_skill_input.strip()
        if skill and skill not in self.required_skills:
            self.required_skills = self.required_skills + [skill]
        self.new_skill_input = ""

    def remove_required_skill(self, skill: str) -> None:
        self.required_skills = [s for s in self.required_skills if s != skill]

    def remove_preferred_skill(self, skill: str) -> None:
        self.preferred_skills = [s for s in self.preferred_skills if s != skill]

    def set_skill_weight(self, value: list[float]) -> None:
        self.skill_weight = value[0]

    def set_cosine_weight(self, value: list[float]) -> None:
        self.cosine_weight = value[0]

    def set_judge_weight(self, value: list[float]) -> None:
        self.judge_weight = value[0]

    def set_fit_threshold(self, value: list[float]) -> None:
        self.fit_threshold = value[0]

    def set_maybe_threshold(self, value: list[float]) -> None:
        self.maybe_threshold = value[0]

    @rx.var
    def threshold_error(self) -> str:
        if self.maybe_threshold >= self.fit_threshold:
            return (
                f"Maybe threshold ({self.maybe_threshold:.2f}) must be lower than "
                f"Fit threshold ({self.fit_threshold:.2f}). "
                "Increase Fit or decrease Maybe."
            )
        return ""

    @rx.var
    def weight_total(self) -> float:
        return round(self.skill_weight + self.cosine_weight + self.judge_weight, 2)

    @rx.var
    def weight_error(self) -> str:
        if abs(self.weight_total - 1.0) > 0.01:
            return f"Weights must sum to 1.0 (currently {self.weight_total:.2f})."
        return ""

    def normalize_weights(self) -> None:
        """Rescales all three weights proportionally so they sum to exactly 1.0,
        preserving their relative balance instead of resetting to defaults."""
        total = self.skill_weight + self.cosine_weight + self.judge_weight
        if total <= 0:
            self.skill_weight, self.cosine_weight, self.judge_weight = 0.30, 0.20, 0.50
            return
        self.skill_weight = round(self.skill_weight / total, 2)
        self.cosine_weight = round(self.cosine_weight / total, 2)
        # Last one absorbs rounding error so the three still sum to exactly 1.0.
        self.judge_weight = round(1.0 - self.skill_weight - self.cosine_weight, 2)

    async def parse_criteria(self):
        """Step 1 -> Step 2: pre-flight parse via POST /jobs/parse-jd. Doesn't create a
        job or spend credits — lets the recruiter review/edit before committing."""
        self.error_message = ""
        if not self.api_key:
            self.error_message = "Sign up for an API key first (see the sidebar)."
            return
        if not self.title or not self.jd_raw:
            self.error_message = "Title and job description are required."
            return

        self.is_parsing = True
        yield
        try:
            parsed = await api_client.parse_jd_preview(self.api_key, self.jd_raw)
            self.parsed_title = parsed.get("title") or self.title
            self.required_skills = parsed.get("required_skills") or []
            self.preferred_skills = parsed.get("preferred_skills") or []
            self.min_yoe = parsed.get("min_yoe") or 0.0
            self.location = parsed.get("location") or ""
            self.must_haves = parsed.get("must_haves") or []
            self.step = 2
        except (httpx.HTTPError, api_client.ApiError) as e:
            self.error_message = str(e)
            yield rx.toast.error(self.error_message)
        finally:
            self.is_parsing = False

    def back_to_step_1(self) -> None:
        self.step = 1

    async def submit(self):
        self.error_message = ""
        if not self.api_key:
            self.error_message = "Sign up for an API key first (see the sidebar)."
            return
        if self.maybe_threshold >= self.fit_threshold:
            self.error_message = self.threshold_error
            return
        if abs(self.weight_total - 1.0) > 0.01:
            self.error_message = self.weight_error
            return

        self.is_submitting = True
        self.created_job_id = ""
        self.created_job_jd_parsed = {}
        yield

        try:
            jd_parsed_override = {
                "title": self.parsed_title or self.title,
                "required_skills": self.required_skills,
                "preferred_skills": self.preferred_skills,
                "min_yoe": self.min_yoe,
                "location": self.location,
                "must_haves": self.must_haves,
            }
            job = await api_client.create_job(
                self.api_key,
                self.title,
                self.jd_raw,
                self.fit_threshold,
                self.maybe_threshold,
                weights={
                    "skill_overlap": self.skill_weight,
                    "cosine": self.cosine_weight,
                    "judge": self.judge_weight,
                },
                jd_parsed_override=jd_parsed_override,
            )
            self.created_job_id = job["id"]
            self.created_job_jd_parsed = job.get("jd_parsed") or {}
            self.step = 1
            self.title = ""
            self.jd_raw = ""
            yield rx.toast.success(f"Job created! ID: {job['id']}")
        except (httpx.HTTPError, api_client.ApiError) as e:
            self.error_message = str(e)
            yield rx.toast.error(self.error_message)
        finally:
            self.is_submitting = False
