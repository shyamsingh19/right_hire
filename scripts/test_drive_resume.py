#!/usr/bin/env python
"""Manually test fetching + extracting text from a resume URL (Google Drive or direct).

Exercises the exact code path a worker uses (app/pipeline/ingest.py:fetch_drive_file +
app/pipeline/parse.py:extract_text) without touching the DB or queue, so you can check
whether a given link is actually downloadable and yields real resume text before wiring
it into a candidate row.

Usage:
    python scripts/test_drive_resume.py "https://drive.google.com/file/d/<ID>/view"
    python scripts/test_drive_resume.py "https://example.com/resume.pdf"
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from app.pipeline.ingest import check_drive_link_access, fetch_drive_file
from app.pipeline.parse import extract_text

_MIN_RESUME_CHARS = 1000


def main() -> int:
    if len(sys.argv) != 2:
        print(f"Usage: python {sys.argv[0]} <resume_url>", file=sys.stderr)
        return 1

    url = sys.argv[1]
    ext = Path(url.split("?")[0]).suffix or ".pdf"

    # Access check runs first, on its own, before any download or parsing is attempted.
    print("Checking link accessibility ...")
    try:
        check_drive_link_access(url)
    except Exception as exc:
        print(f"PRIVATE: {exc}")
        print("Stopping here — this resume was not downloaded or parsed.")
        return 1
    print("PUBLIC: link is accessible without sign-in.")

    with tempfile.TemporaryDirectory() as tmpdir:
        dest = Path(tmpdir) / f"test_resume{ext}"
        print(f"Downloading {url!r} -> {dest} ...")
        try:
            fetch_drive_file(url, str(dest))
        except Exception as exc:
            print(f"FAILED to download: {exc}")
            return 1

        size = dest.stat().st_size
        print(f"Downloaded {size} bytes.")

        print("Extracting text ...")
        try:
            text = extract_text(str(dest))
        except Exception as exc:
            print(f"FAILED to extract text: {exc}")
            return 1

        stripped = text.strip()
        print(f"Extracted {len(stripped)} chars.")
        print("-" * 60)
        print(stripped)  # Prints the whole resume text without truncation
        print("-" * 60)

        if len(stripped) < _MIN_RESUME_CHARS:
            print(f"WOULD FAIL in pipeline: below {_MIN_RESUME_CHARS}-char minimum.")
            return 1

        print("OK: looks like usable resume text.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())