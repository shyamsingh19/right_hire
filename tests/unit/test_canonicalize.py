from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from app.skills.canonicalize import canonicalize_skill, canonicalize_skills


def _mock_canonicalizer(taxonomy: list[str], sims: list[float]):
    """Build a mock canonicalizer that returns pre-set similarity scores."""
    model = MagicMock()
    vec = np.array([[1.0] * 384], dtype=np.float32)
    model.encode.return_value = vec

    taxonomy_vecs = np.zeros((len(taxonomy), 384), dtype=np.float32)
    # Inject similarity via dot product: set each row so dot(taxonomy_vec, query) = sim[i]
    for i, sim in enumerate(sims):
        taxonomy_vecs[i, 0] = sim  # query has 1.0 in dim 0 so dot = sim

    return model, taxonomy, taxonomy_vecs


def test_exact_match():
    taxonomy = ["Python", "JavaScript", "Docker"]
    sims = [0.99, 0.3, 0.4]
    with patch("app.skills.canonicalize._get_canonicalizer", return_value=_mock_canonicalizer(taxonomy, sims)):
        result = canonicalize_skill("python")
    assert result == "Python"


def test_near_match():
    taxonomy = ["Machine Learning", "Docker", "Python"]
    sims = [0.82, 0.3, 0.5]
    with patch("app.skills.canonicalize._get_canonicalizer", return_value=_mock_canonicalizer(taxonomy, sims)):
        result = canonicalize_skill("ML", threshold=0.75)
    assert result == "Machine Learning"


def test_no_match_returns_original():
    taxonomy = ["Python", "Docker"]
    sims = [0.4, 0.3]  # both below threshold
    with patch("app.skills.canonicalize._get_canonicalizer", return_value=_mock_canonicalizer(taxonomy, sims)):
        result = canonicalize_skill("COBOL", threshold=0.75)
    assert result == "COBOL"


def test_canonicalize_skills_deduplicates():
    taxonomy = ["Python", "Docker"]
    sims = [0.95, 0.2]
    with patch("app.skills.canonicalize._get_canonicalizer", return_value=_mock_canonicalizer(taxonomy, sims)):
        result = canonicalize_skills(["python", "Python", "PYTHON"], threshold=0.75)
    assert result.count("Python") == 1


def test_no_model_returns_original():
    with patch("app.skills.canonicalize._get_canonicalizer", return_value=(None, ["Python"], None)):
        assert canonicalize_skill("python") == "python"
