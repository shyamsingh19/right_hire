from __future__ import annotations

import logging
from functools import lru_cache

import numpy as np

from app.config import settings

logger = logging.getLogger(__name__)

_FALLBACK_MODEL = "all-MiniLM-L6-v2"


@lru_cache(maxsize=1)
def get_embedder():
    """Load and cache the SentenceTransformer model (once per process)."""
    from sentence_transformers import SentenceTransformer

    model_name = settings.embed_model
    try:
        model = SentenceTransformer(model_name)
        logger.info("Loaded embedding model: %s", model_name)
        return model
    except Exception as exc:
        logger.warning("Failed to load %s (%s), falling back to %s", model_name, exc, _FALLBACK_MODEL)
        return SentenceTransformer(_FALLBACK_MODEL)


def embed_texts(texts: list[str]) -> np.ndarray:
    """Embed a list of strings. Returns (N, D) float32 array."""
    if not texts:
        return np.empty((0,), dtype=np.float32)
    model = get_embedder()
    vecs = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return np.array(vecs, dtype=np.float32)


def build_faiss_index(vectors: np.ndarray):
    """Build an inner-product FAISS index from an (N, D) array."""
    import faiss

    if vectors.ndim == 1:
        vectors = vectors.reshape(1, -1)
    dim = vectors.shape[1]
    index = faiss.IndexFlatIP(dim)
    index.add(vectors.astype(np.float32))
    return index


def search_index(index, query_vec: np.ndarray, k: int = 10) -> tuple[np.ndarray, np.ndarray]:
    """Search the index; returns (scores, indices) arrays of shape (k,)."""
    if query_vec.ndim == 1:
        query_vec = query_vec.reshape(1, -1)
    k = min(k, index.ntotal)
    if k == 0:
        return np.array([]), np.array([])
    scores, indices = index.search(query_vec.astype(np.float32), k)
    return scores[0], indices[0]


def vec_to_bytes(vec: np.ndarray) -> bytes:
    return vec.astype(np.float32).tobytes()


def bytes_to_vec(data: bytes) -> np.ndarray:
    return np.frombuffer(data, dtype=np.float32)
