from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

_TAXONOMY_PATH = Path(__file__).parent / "taxonomy.json"


@lru_cache(maxsize=1)
def _load_taxonomy() -> list[str]:
    return json.loads(_TAXONOMY_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _get_canonicalizer():
    """Load MiniLM and pre-embed the taxonomy once per process."""
    try:
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer("all-MiniLM-L6-v2")
        taxonomy = _load_taxonomy()
        taxonomy_vecs = model.encode(taxonomy, normalize_embeddings=True, show_progress_bar=False)
        return model, taxonomy, np.array(taxonomy_vecs, dtype=np.float32)
    except Exception as exc:
        logger.warning("Could not load canonicalizer model: %s", exc)
        return None, _load_taxonomy(), None


def canonicalize_skill(skill: str, threshold: float = 0.75) -> str:
    """Map a raw skill string to its closest ESCO taxonomy entry if similarity ≥ threshold."""
    model, taxonomy, taxonomy_vecs = _get_canonicalizer()

    if model is None or taxonomy_vecs is None:
        # No model available — return as-is
        return skill

    vec = model.encode([skill], normalize_embeddings=True, show_progress_bar=False)
    sims = (taxonomy_vecs @ vec.T).flatten()
    best_idx = int(np.argmax(sims))
    best_score = float(sims[best_idx])

    if best_score >= threshold:
        return taxonomy[best_idx]
    return skill
