from __future__ import annotations

from app.schemas import ParsedJD, ParsedResume


def apply_filters(
    candidate: ParsedResume,
    jd: ParsedJD,
    thresholds: dict,
) -> tuple[bool, str | None]:
    """Apply hard elimination rules. Returns (passed, rejection_reason)."""
    # YOE check
    if jd.min_yoe and jd.min_yoe > 0:
        yoe_threshold = thresholds.get("min_yoe", jd.min_yoe)
        if candidate.yoe < yoe_threshold:
            return (
                False,
                f"Insufficient experience: {candidate.yoe:.1f} yrs < {yoe_threshold:.1f} yrs required",
            )

    # Location check (only when strict mode enabled)
    if thresholds.get("location_strict") and jd.location:
        jd_loc = jd.location.lower().strip()
        cand_loc = (candidate.location or "").lower().strip()
        if jd_loc and cand_loc and jd_loc not in cand_loc and cand_loc not in jd_loc:
            return (
                False,
                f"Location mismatch: candidate is in '{candidate.location}', JD requires '{jd.location}'",
            )

    # Must-have skills
    if jd.must_haves:
        candidate_skills_lower = {s.lower() for s in candidate.skills}
        missing = [
            skill
            for skill in jd.must_haves
            if not any(skill.lower() in cs or cs in skill.lower() for cs in candidate_skills_lower)
        ]
        if missing:
            return False, f"Missing required skill(s): {', '.join(missing)}"

    return True, None
