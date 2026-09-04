from __future__ import annotations

import httpx
import reflex as rx

from right_hire_ui import api_client
from right_hire_ui.states.app_state import AppState

# A criterion's importance maps onto the three lists ParsedJD already has, chosen to
# match what each one actually does in the pipeline:
#   nice      -> preferred_skills : counted in skill overlap only
#   important -> required_skills  : counted in overlap AND shown to the LLM judge
#   required  -> required_skills + must_haves : the above, plus a hard elimination
#                filter (app/pipeline/filters.py) — a must-have alone would drop the
#                skill out of scoring entirely, which is not what "required" means.
CRITERION_LEVELS = [
    ("nice", "Nice to have"),
    ("important", "Important"),
    ("required", "Required"),
]
_LEVEL_VALUES = [v for v, _ in CRITERION_LEVELS]

PARSE_FAILED_MESSAGE = (
    "Couldn't parse this description. Try adding more detail, or enter criteria manually."
)


def _criteria_from_parse(required: list[str], preferred: list[str], must: list[str]) -> list[dict]:
    """Parsed JD lists -> editable criteria rows, preserving importance."""
    must_lower = {m.lower() for m in must}
    rows = [
        {"text": s, "level": "required" if s.lower() in must_lower else "important"}
        for s in required
    ]
    seen = {r["text"].lower() for r in rows}
    # A must-have the parser didn't also list as a required skill still belongs here.
    rows += [{"text": m, "level": "required"} for m in must if m.lower() not in seen]
    seen |= must_lower
    rows += [{"text": s, "level": "nice"} for s in preferred if s.lower() not in seen]
    return rows


class CreateJobState(AppState):
    step: int = 1  # 1 = input JD, 2 = review & calibrate

    title: str = ""
    jd_raw: str = ""

    # Populated from POST /jobs/parse-jd, then editable before job creation.
    parsed_title: str = ""
    # Single editable source of truth for step 2: [{"text": str, "level": str}].
    # Split back into ParsedJD's three lists on submit (see _split_criteria).
    criteria: list[dict] = []  # noqa: RUF012
    required_skills: list[str] = []  # noqa: RUF012
    preferred_skills: list[str] = []  # noqa: RUF012
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
    created_job_title: str = ""
    created_job_jd_parsed: dict = {}  # noqa: RUF012

    def set_title(self, value: str) -> None:
        self.title = value

    def set_jd_raw(self, value: str) -> None:
        self.jd_raw = value

    def set_min_yoe(self, value: list[float]) -> None:
        self.min_yoe = value[0]

    def set_location(self, value: str) -> None:
        self.location = value

    def set_criterion_text(self, index: int, value: str) -> None:
        if 0 <= index < len(self.criteria):
            row = dict(self.criteria[index])
            row["text"] = value
            self.criteria = [*self.criteria[:index], row, *self.criteria[index + 1 :]]

    def set_criterion_level(self, index: int, level: str) -> None:
        if 0 <= index < len(self.criteria) and level in _LEVEL_VALUES:
            row = dict(self.criteria[index])
            row["level"] = level
            self.criteria = [*self.criteria[:index], row, *self.criteria[index + 1 :]]

    def remove_criterion(self, index: int) -> None:
        self.criteria = [c for i, c in enumerate(self.criteria) if i != index]

    def add_criterion(self) -> None:
        self.criteria = [*self.criteria, {"text": "", "level": "important"}]

    @rx.var
    def jd_char_count(self) -> str:
        """Empty string when the field is empty — "0 characters" is noise."""
        n = len(self.jd_raw)
        return f"{n:,} characters" if n else ""

    @rx.var
    def has_criteria(self) -> bool:
        return any((c.get("text") or "").strip() for c in self.criteria)

    def _split_criteria(self) -> tuple[list[str], list[str], list[str]]:
        required: list[str] = []
        preferred: list[str] = []
        must: list[str] = []
        for c in self.criteria:
            text = (c.get("text") or "").strip()
            if not text:
                continue
            level = c.get("level") or "important"
            if level == "nice":
                if text not in preferred:
                    preferred.append(text)
                continue
            if text not in required:
                required.append(text)
            if level == "required" and text not in must:
                must.append(text)
        return required, preferred, must

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
            required = parsed.get("required_skills") or []
            preferred = parsed.get("preferred_skills") or []
            must = parsed.get("must_haves") or []
            if not (required or preferred or must):
                # A 200 with nothing extracted is still a failure from the user's point
                # of view — don't drop them into an empty step 2 with no explanation.
                self.error_message = PARSE_FAILED_MESSAGE
                return
            self.parsed_title = parsed.get("title") or self.title
            self.min_yoe = parsed.get("min_yoe") or 0.0
            self.location = parsed.get("location") or ""
            self.criteria = _criteria_from_parse(required, preferred, must)
            self.step = 2
        except (httpx.HTTPError, api_client.ApiError):
            # Inline, beside the field that caused it — a toast puts the message far
            # from the textarea the user has to fix.
            self.error_message = PARSE_FAILED_MESSAGE
        finally:
            self.is_parsing = False

    def start_manual(self) -> None:
        """Skip the LLM and build criteria by hand — for a role with no JD to paste."""
        self.error_message = ""
        self.parsed_title = self.title
        self.criteria = [{"text": "", "level": "important"}]
        self.min_yoe = 0.0
        self.location = ""
        self.step = 2

    def back_to_step_1(self) -> None:
        self.step = 1

    def create_another(self) -> None:
        """Dismisses the success panel and returns to an empty step 1."""
        self.criteria = []
        self.created_job_id = ""
        self.created_job_title = ""
        self.created_job_jd_parsed = {}
        self.step = 1
        self.error_message = ""

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
        self.created_job_title = ""
        self.created_job_jd_parsed = {}
        yield

        try:
            job_title = self.parsed_title or self.title
            # Kept on state so the post-create summary panel can render them.
            self.required_skills, self.preferred_skills, self.must_haves = self._split_criteria()
            jd_parsed_override = {
                "title": job_title,
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
            self.created_job_title = job_title
            self.created_job_jd_parsed = job.get("jd_parsed") or {}
            self.step = 1
            self.title = ""
            self.jd_raw = ""
            self.criteria = []
            yield rx.toast.success(f"'{job_title}' is live and ready for candidates.")
        except (httpx.HTTPError, api_client.ApiError) as e:
            self.error_message = str(e)
            yield rx.toast.error(self.error_message)
        finally:
            self.is_submitting = False
