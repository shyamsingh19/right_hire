from __future__ import annotations

import csv
import io
import logging
import os
import re
from pathlib import Path

import httpx
import openpyxl

from app.config import settings

logger = logging.getLogger(__name__)

# Canonical column name mapping — covers common spreadsheet headers
_COL_MAP: dict[str, str] = {
    "name": "name",
    "full name": "name",
    "candidate name": "name",
    "email": "email",
    "email address": "email",
    "e-mail": "email",
    "resume_url": "resume_url",
    "resume url": "resume_url",
    "cv url": "resume_url",
    "resume link": "resume_url",
    "resume_drive_link": "resume_url",
    "drive link": "resume_url",
    "google drive link": "resume_url",
    "yoe": "yoe",
    "years of experience": "yoe",
    "experience": "yoe",
    "years": "yoe",
    "location": "location",
    "city": "location",
    "city/country": "location",
}


def _normalize_header(raw: str) -> str:
    return _COL_MAP.get(raw.strip().lower(), raw.strip().lower().replace(" ", "_"))


def parse_excel(file_bytes: bytes) -> list[dict]:
    """Parse an .xlsx file and return a list of normalised row dicts."""
    wb = openpyxl.load_workbook(filename=io.BytesIO(file_bytes), read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []

    raw_headers = [str(h) if h is not None else "" for h in rows[0]]
    headers = [_normalize_header(h) for h in raw_headers]

    result: list[dict] = []
    for row in rows[1:]:
        if all(v is None for v in row):
            continue  # skip blank rows
        record: dict = {}
        for header, value in zip(headers, row):
            if not header:
                continue
            if value is not None:
                record[header] = value
        if record:
            result.append(record)

    wb.close()
    return result


def parse_csv(file_bytes: bytes) -> list[dict]:
    """Parse a .csv file and return a list of normalised row dicts.

    Shares `_COL_MAP` / `_normalize_header` with `parse_excel` so both formats
    accept the same header aliases and produce identical row shapes.
    """
    text = file_bytes.decode("utf-8-sig")
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        return []

    headers = [_normalize_header(h) for h in rows[0]]

    result: list[dict] = []
    for row in rows[1:]:
        if all(not v.strip() for v in row):
            continue  # skip blank rows
        record: dict = {}
        for header, value in zip(headers, row):
            if not header:
                continue
            value = value.strip()
            if value:
                record[header] = value
        if record:
            result.append(record)

    return result


def _is_drive_url(url: str) -> bool:
    return "drive.google.com" in url or "docs.google.com" in url


def _drive_to_direct(url: str) -> str:
    """Convert a Google Drive share URL to a direct download URL."""
    # e.g. https://drive.google.com/file/d/<ID>/view?...
    match = re.search(r"/file/d/([^/]+)", url)
    if match:
        file_id = match.group(1)
        return f"https://drive.google.com/uc?export=download&id={file_id}"
    # e.g. https://drive.google.com/open?id=<ID>
    match = re.search(r"id=([^&]+)", url)
    if match:
        file_id = match.group(1)
        return f"https://drive.google.com/uc?export=download&id={file_id}"
    return url


def fetch_drive_file(url: str, dest_path: str) -> str:
    """Download a file from Google Drive or a direct URL to *dest_path*.

    Returns the local path.
    """
    Path(dest_path).parent.mkdir(parents=True, exist_ok=True)

    if _is_drive_url(url):
        try:
            import gdown

            gdown.download(url, dest_path, quiet=True, fuzzy=True)
            return dest_path
        except Exception as exc:
            logger.warning("gdown failed (%s), falling back to direct download", exc)
            direct_url = _drive_to_direct(url)
            _http_download(direct_url, dest_path)
            return dest_path
    else:
        _http_download(url, dest_path)
        return dest_path


def _http_download(url: str, dest_path: str) -> None:
    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        with client.stream("GET", url) as resp:
            resp.raise_for_status()
            with open(dest_path, "wb") as fh:
                for chunk in resp.iter_bytes(chunk_size=8192):
                    fh.write(chunk)


def save_resume(candidate_id: str, content: bytes, ext: str) -> str:
    """Persist resume bytes under STORAGE_DIR and return the file path."""
    storage = Path(settings.storage_dir)
    storage.mkdir(parents=True, exist_ok=True)
    safe_ext = ext.lstrip(".").lower() or "pdf"
    file_path = storage / f"{candidate_id}.{safe_ext}"
    file_path.write_bytes(content)
    return str(file_path)
