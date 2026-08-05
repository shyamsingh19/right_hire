from __future__ import annotations

from typing import Callable

import numpy as np

from app.schemas import ParsedJD, ParsedResume


def compute_skill_overlap(
    candidate_skills: list[str],
    jd_skills: list[str],
    canonicalize_fn: Callable[[str], str] | None = None,
) -> float:
    """Jaccard-style overlap between canonical candidate skills and JD skills."""
    if not jd_skills:
        return 1.0

    def _canon(s: str) -> str:
        if canonicalize_fn:
            return canonicalize_fn(s).lower()
        return s.lower().strip()

    cand_set = {_canon(s) for s in candidate_skills}
    jd_set = {_canon(s) for s in jd_skills}

    if not jd_set:
        return 1.0

    matched = cand_set & jd_set
    # Precision against JD requirements (recall-biased)
    return len(matched) / len(jd_set)


def compute_cosine(vec_a: np.ndarray, vec_b: np.ndarray) -> float:
    """Cosine similarity between two vectors (assumes L2-normalised inputs)."""
    a = vec_a.flatten().astype(np.float64)
    b = vec_b.flatten().astype(np.float64)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def match_candidate(
    parsed_resume: ParsedResume,
    parsed_jd: ParsedJD,
    jd_embedding: np.ndarray,
    candidate_embedding: np.ndarray,
    canonicalize_fn: Callable[[str], str] | None = None,
) -> dict:
    """Compute all match signals between a candidate and a JD."""
    all_jd_skills = parsed_jd.required_skills + parsed_jd.preferred_skills

    skill_overlap = compute_skill_overlap(parsed_resume.skills, all_jd_skills, canonicalize_fn)
    cosine_sim = compute_cosine(candidate_embedding, jd_embedding)

    # Which JD skills did the candidate match?
    def _canon(s: str) -> str:
        if canonicalize_fn:
            return canonicalize_fn(s).lower()
        return s.lower().strip()

    cand_set = {_canon(s) for s in parsed_resume.skills}
    matched_skills = [skill for skill in all_jd_skills if _canon(skill) in cand_set]

    # Match bullets by simple keyword presence of matched skills
    matched_bullets: list[str] = []
    matched_lower = {s.lower() for s in matched_skills}
    for bullet in parsed_resume.bullets:
        bullet_lower = bullet.lower()
        if any(skill in bullet_lower for skill in matched_lower):
            matched_bullets.append(bullet)

    return {
        "skill_overlap": skill_overlap,
        "cosine_sim": cosine_sim,
        "matched_skills": matched_skills,
        "matched_bullets": matched_bullets[:10],  # cap for prompt budget
    }
