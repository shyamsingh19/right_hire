from __future__ import annotations

import logging
from pathlib import Path

from app.llm.base import LLMProvider, LLMUnavailableError
from app.schemas import ParsedJD, ParsedResume

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"


def _load_prompt(name: str) -> str:
    path = _PROMPTS_DIR / name
    return path.read_text(encoding="utf-8")


# ── Text extraction ──────────────────────────────────────────────────────────


def extract_text(file_path: str) -> str:
    """Extract plain text from a PDF (or image PDF) using a cascade of strategies.

    Strategy order:
    1. pymupdf  — fastest, works for text-layer PDFs
    2. pdfplumber — handles some edge-cases pymupdf misses
    3. Tesseract OCR — last resort for scanned documents
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Resume file not found: {file_path}")

    suffix = path.suffix.lower()

    # Non-PDF formats: try reading as plain text
    if suffix in {".txt", ".md"}:
        return path.read_text(encoding="utf-8", errors="replace")

    # ── Strategy 1: pymupdf ──────────────────────────────────────────────────
    try:
        import fitz  # pymupdf

        doc = fitz.open(str(path))
        pages_text = [page.get_text() for page in doc]
        doc.close()
        text = "\n".join(pages_text).strip()
        if len(text) > 100:
            return text
        logger.debug("pymupdf returned thin text (%d chars), trying pdfplumber", len(text))
    except Exception as exc:
        logger.warning("pymupdf failed: %s", exc)

    # ── Strategy 2: pdfplumber ───────────────────────────────────────────────
    try:
        import pdfplumber

        with pdfplumber.open(str(path)) as pdf:
            pages_text = [p.extract_text() or "" for p in pdf.pages]
        text = "\n".join(pages_text).strip()
        if len(text) > 100:
            return text
        logger.debug("pdfplumber returned thin text (%d chars), trying OCR", len(text))
    except Exception as exc:
        logger.warning("pdfplumber failed: %s", exc)

    # ── Strategy 3: Tesseract OCR ────────────────────────────────────────────
    try:
        import pytesseract
        from PIL import Image

        # Use fitz to render pages as images, then OCR each
        import fitz  # noqa: F401 already imported above but guard with try

        doc = fitz.open(str(path))
        ocr_pages: list[str] = []
        for page in doc:
            pix = page.get_pixmap(dpi=200)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            ocr_pages.append(pytesseract.image_to_string(img))
        doc.close()
        text = "\n".join(ocr_pages).strip()
        if text:
            return text
    except Exception as exc:
        logger.warning("Tesseract OCR failed: %s", exc)

    logger.error("All text-extraction strategies failed for %s", file_path)
    return ""


# ── LLM-based parsing ────────────────────────────────────────────────────────


def parse_resume(text: str, provider: LLMProvider) -> ParsedResume:
    """Parse raw resume text into a structured ParsedResume using the LLM."""
    template = _load_prompt("parse_resume.txt")
    prompt = template.replace("{{RESUME_TEXT}}", text[:6000])  # cap context
    try:
        return provider.complete_json(prompt, ParsedResume, max_tokens=512)
    except Exception as exc:  # normalize any provider error
        logger.warning(
            "LLM provider failed while parsing resume [backend=%s model=%s]: %s",
            type(provider).__name__,
            getattr(provider, "model", "?"),
            exc,
            exc_info=True,
        )
        raise LLMUnavailableError("LLM provider unavailable for resume parsing") from exc


def parse_jd(jd_raw: str, provider: LLMProvider) -> ParsedJD:
    """Parse a raw job description into a structured ParsedJD using the LLM."""
    template = _load_prompt("parse_jd.txt")
    prompt = template.replace("{{JD_TEXT}}", jd_raw[:4000])
    try:
        return provider.complete_json(prompt, ParsedJD, max_tokens=512)
    except Exception as exc:  # normalize any provider error
        logger.warning(
            "LLM provider failed while parsing JD [backend=%s model=%s]: %s",
            type(provider).__name__,
            getattr(provider, "model", "?"),
            exc,
            exc_info=True,
        )
        raise LLMUnavailableError("LLM provider unavailable for JD parsing") from exc
