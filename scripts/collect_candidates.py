"""
collect_candidates.py  —  Simple public candidate collector
──────────────────────────────────────────────────────────
Sources:
  1. GitHub REST API  — public user profiles (name, email, location, website)
  2. Serper.dev       — Google search for public resume PDFs / portfolios

Output:
  output/candidates.csv   — live, one row per candidate as found
  output/candidates.html  — auto-refreshing table (open in browser)
  output/candidates.xlsx  — ATS-ready Excel after enrichment

Quick start:
  pip install requests email-validator openpyxl
  python collect_candidates.py --query "python developer" --limit 20

Env vars (loaded from .env automatically):
  GITHUB_TOKEN    — raises GitHub rate limit from 10 → 30 req/min
  SERPER_API_KEY  — Google search via serper.dev (100 free queries/day)
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import logging
import os
import re
import sys
import time
import webbrowser
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

import requests
from email_validator import validate_email, EmailNotValidError

# Running ``python scripts/collect_candidates.py`` puts only ``scripts/`` on
# sys.path. Add the repository root so verification can reuse worker helpers.
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.pipeline.ingest import fetch_drive_file  # noqa: E402
from app.pipeline.parse import extract_text  # noqa: E402

# ── Load .env from repo root ──────────────────────────────────
_env_path = REPO_ROOT / ".env"
if _env_path.exists():
    for _line in _env_path.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

# ── Config ────────────────────────────────────────────────────
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
SERPER_API_KEY = os.getenv("SERPER_API_KEY", "")

OUTPUT_DIR = REPO_ROOT / "output"
OUTPUT_CSV = OUTPUT_DIR / "candidates.csv"
OUTPUT_HTML = OUTPUT_DIR / "candidates.html"
OUTPUT_XLSX = OUTPUT_DIR / "candidates.xlsx"
RESUME_DIR = OUTPUT_DIR / "resumes"
DOWNLOAD_REPORT = OUTPUT_DIR / "resume_downloads.csv"

OUTPUT_DIR.mkdir(exist_ok=True)

# Columns written to CSV / HTML
FIELDS = ["name", "email", "resume_url", "yoe", "location", "source", "collected_at"]
# ATS Excel columns (subset, required by ingest API)
ATS_FIELDS = ["name", "email", "resume_url", "yoe", "location"]
DOWNLOAD_FIELDS = [
    "name",
    "email",
    "resume_url",
    "status",
    "local_path",
    "size_bytes",
    "text_characters",
    "checked_at",
    "detail",
]
MIN_RESUME_TEXT_CHARS = 1000

EMAIL_RE = re.compile(r"[\w.+\-]+@[\w\-]+\.[a-z]{2,}")
_DRIVE_FILE_PATH_RE = re.compile(r"^/file/d/([^/]+)")

# ── Logging ───────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)


# ── Data model ────────────────────────────────────────────────
@dataclass
class Candidate:
    name: str
    email: str | None = None
    resume_url: str | None = None
    yoe: int | None = None
    location: str | None = None
    source: str = ""
    collected_at: str = ""


# ── Live local sheet ──────────────────────────────────────────
class LocalSheet:
    """Writes candidates to CSV + HTML as they arrive — open HTML in browser."""

    _HTML_HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="4">
<title>Candidates — live</title>
<style>
  body  { font-family: system-ui, sans-serif; margin: 2rem; background:#f8f9fa; color:#212529; }
  h1    { font-size:1.4rem; margin-bottom:.5rem; }
  .meta { font-size:.85rem; color:#6c757d; margin-bottom:1.2rem; }
  table { border-collapse:collapse; width:100%; background:#fff;
          box-shadow:0 1px 4px rgba(0,0,0,.1); border-radius:6px; overflow:hidden; }
  th    { background:#343a40; color:#fff; padding:10px 14px; text-align:left;
          font-size:.82rem; text-transform:uppercase; letter-spacing:.04em; }
  td    { padding:9px 14px; font-size:.88rem; border-bottom:1px solid #dee2e6; }
  tr:last-child td { border-bottom:none; }
  tr:hover td      { background:#f1f3f5; }
  a     { color:#0d6efd; text-decoration:none; }
  a:hover { text-decoration:underline; }
  .badge { display:inline-block; padding:2px 8px; border-radius:99px; font-size:.75rem;
           font-weight:600; background:#e9ecef; color:#495057; }
  .badge-gh     { background:#d1ecf1; color:#0c5460; }
  .badge-serper { background:#d4edda; color:#155724; }
  .ok   { color:#198754; font-weight:600; }
  .miss { color:#dc3545; }
</style>
</head>
<body>
<h1>&#128101; Candidate Collection — Live View</h1>
"""

    def __init__(self):
        is_new = not OUTPUT_CSV.exists() or OUTPUT_CSV.stat().st_size == 0
        self._csv_file = open(OUTPUT_CSV, "a", newline="", encoding="utf-8")  # noqa: SIM115
        self._writer = csv.DictWriter(self._csv_file, fieldnames=FIELDS)
        if is_new:
            self._writer.writeheader()
            self._csv_file.flush()

        self._rows: list[dict] = []
        if OUTPUT_CSV.exists() and not is_new:
            with open(OUTPUT_CSV, encoding="utf-8") as f:
                self._rows = list(csv.DictReader(f))

        self._render_html()
        log.info("Sheet › %s  (open in browser for live view)", OUTPUT_HTML)

    def append(self, c: Candidate) -> None:
        c.collected_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        row = {k: (getattr(c, k) or "") for k in FIELDS}
        self._writer.writerow(row)
        self._csv_file.flush()
        self._rows.append(row)
        self._render_html()

    def append_complete(self, c: Candidate) -> None:
        """Only write to sheet when all 3 mandatory fields are present."""
        if not (c.name and c.email and c.resume_url):
            return
        self.append(c)

    def close(self) -> None:
        self._csv_file.close()

    def _render_html(self) -> None:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        rows = self._rows
        has_email = sum(1 for r in rows if r.get("email"))

        header_cells = "<th>#</th>" + "".join(f"<th>{h}</th>" for h in FIELDS)
        body_rows = []
        for i, r in enumerate(reversed(rows), 1):
            cells = [f"<td>{i}</td>"]
            for f in FIELDS:
                val = r.get(f, "")
                if f == "resume_url" and val:
                    disp = val[:55] + "…" if len(val) > 55 else val
                    val = f'<a href="{val}" target="_blank">{disp}</a>'
                elif f == "source":
                    cls = "badge-gh" if val == "github" else "badge-serper"
                    val = f'<span class="badge {cls}">{val}</span>'
                elif f == "email":
                    if val:
                        val = f'<span class="ok">✓ {val}</span>'
                    else:
                        val = '<span class="miss">—</span>'
                cells.append(f"<td>{val}</td>")
            body_rows.append("<tr>" + "".join(cells) + "</tr>")

        html = (
            self._HTML_HEAD + f'<div class="meta">&#128260; Auto-refreshes every 4 s &nbsp;|&nbsp; '
            f"{len(rows)} candidates &nbsp;|&nbsp; "
            f"emails found: {has_email}/{len(rows)} &nbsp;|&nbsp; "
            f"last update: {ts}</div>\n"
            + "<table><thead><tr>"
            + header_cells
            + "</tr></thead><tbody>"
            + "\n".join(body_rows)
            + "</tbody></table></body></html>"
        )
        OUTPUT_HTML.write_text(html, encoding="utf-8")


# ── Email enrichment ─────────────────────────────────────────
def _extract_email_from_text(text: str) -> str | None:
    m = EMAIL_RE.search(text)
    if not m:
        return None
    return clean_email(m.group())


def enrich_email(c: Candidate) -> str | None:
    """Try to pull an email from the resume_url — PDF parse or HTML scrape."""
    if not c.resume_url:
        return None

    try:
        # A Drive share URL serves an HTML viewer.  Fetch the file endpoint instead
        # so PDFs can be searched for the candidate's contact details.
        download_url = google_drive_download_url(c.resume_url)
        resp = requests.get(
            download_url, timeout=10, stream=True, headers={"User-Agent": "Mozilla/5.0"}
        )
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "")

        if "pdf" in content_type or download_url.lower().endswith(".pdf"):
            raw = resp.content
            # Try pdfplumber first, fall back to pymupdf
            try:
                import pdfplumber

                with pdfplumber.open(io.BytesIO(raw)) as pdf:
                    text = "\n".join(p.extract_text() or "" for p in pdf.pages[:3])
            except Exception:
                try:
                    import fitz  # pymupdf

                    doc = fitz.open(stream=raw, filetype="pdf")
                    text = "\n".join(doc[i].get_text() for i in range(min(3, len(doc))))
                except Exception:
                    return None
            return _extract_email_from_text(text)

        else:
            # HTML page — scan visible text for email pattern
            return _extract_email_from_text(resp.text)

    except Exception as e:
        log.debug("enrich_email failed for %s: %s", c.resume_url, e)
        return None


def enrich_all(candidates: list[Candidate], sheet: LocalSheet) -> None:
    """Download each resume, extract email, then add complete candidate to sheet."""
    missing = [c for c in candidates if not c.email and c.resume_url]
    if not missing:
        return

    log.info("Enriching emails for %d candidates …", len(missing))
    found = 0
    for c in missing:
        email = enrich_email(c)
        if email:
            c.email = email
            sheet.append_complete(c)  # write to sheet only now that it's complete
            found += 1
            log.info("  ✉  %s  →  %s", c.name, email)
        else:
            log.info("  –  %s  (no email found — skipped)", c.name)
    log.info("Enrichment done: %d/%d added to sheet", found, len(missing))


# ── ATS Excel export ─────────────────────────────────────────
def export_xlsx(candidates: list[Candidate]) -> None:
    try:
        import openpyxl
    except ImportError:
        log.warning("pip install openpyxl  — skipping Excel export")
        return

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Candidates"

    # Bold header
    from openpyxl.styles import Font, PatternFill, Alignment

    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="343A40")

    ws.append(ATS_FIELDS)
    for cell in ws[1]:
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")

    for c in candidates:
        ws.append(
            [
                c.name or "",
                c.email or "",
                c.resume_url or "",
                c.yoe if c.yoe is not None else "",
                c.location or "",
            ]
        )

    # Auto column width
    for col in ws.columns:
        width = max(len(str(cell.value or "")) for cell in col) + 4
        ws.column_dimensions[col[0].column_letter].width = min(width, 60)

    wb.save(OUTPUT_XLSX)
    log.info("✅  Excel → %s  (%d rows)", OUTPUT_XLSX, len(candidates))


# ── Resume download verification ──────────────────────────────
def _safe_filename(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip(".-")
    return value[:60] or "resume"


def _resume_suffix(path: Path) -> str:
    """Infer an extension from the downloaded content, not the share URL."""
    try:
        head = path.read_bytes()[:512].lstrip().lower()
    except OSError:
        return ".bin"
    if head.startswith(b"%pdf-"):
        return ".pdf"
    if head.startswith((b"<!doctype html", b"<html")):
        return ".html"
    if head.startswith(b"pk\\x03\\x04"):
        return ".zip"
    return ".bin"


def _load_collected_candidates() -> list[Candidate]:
    """Load the existing candidate export for verification without searching again."""
    if not OUTPUT_CSV.exists():
        raise FileNotFoundError(f"No candidate export found at {OUTPUT_CSV}")
    with open(OUTPUT_CSV, encoding="utf-8", newline="") as f:
        return [
            Candidate(
                name=row.get("name", ""),
                email=row.get("email") or None,
                resume_url=row.get("resume_url") or None,
                yoe=int(row["yoe"]) if row.get("yoe", "").isdigit() else None,
                location=row.get("location") or None,
                source=row.get("source", ""),
                collected_at=row.get("collected_at", ""),
            )
            for row in csv.DictReader(f)
            if row.get("name") and row.get("resume_url")
        ]


def verify_resume_downloads(candidates: list[Candidate]) -> None:
    """Download resumes, save the response, and write a reproducible status report.

    This deliberately uses the same ``fetch_drive_file`` and ``extract_text`` helpers
    as the worker. A successful result therefore means the resume is publicly
    downloadable *and* has enough text for the screening pipeline.
    """
    RESUME_DIR.mkdir(parents=True, exist_ok=True)
    checked_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    usable = downloaded = 0

    log.info("Resume verification › checking %d links", len(candidates))
    log.info("Downloaded files → %s", RESUME_DIR)
    with open(DOWNLOAD_REPORT, "w", newline="", encoding="utf-8") as report_file:
        report = csv.DictWriter(report_file, fieldnames=DOWNLOAD_FIELDS)
        report.writeheader()

        for index, candidate in enumerate(candidates, 1):
            assert candidate.resume_url  # candidates are filtered by the caller
            url_hash = hashlib.sha256(candidate.resume_url.encode()).hexdigest()[:12]
            base_name = f"{index:03d}-{_safe_filename(candidate.name)}-{url_hash}"
            temporary_path = RESUME_DIR / f"{base_name}.download"
            row = {
                "name": candidate.name,
                "email": candidate.email or "",
                "resume_url": candidate.resume_url,
                "status": "failed",
                "local_path": "",
                "size_bytes": "",
                "text_characters": "",
                "checked_at": checked_at,
                "detail": "",
            }

            try:
                fetch_drive_file(candidate.resume_url, str(temporary_path))
                downloaded += 1
                saved_path = temporary_path.with_suffix(_resume_suffix(temporary_path))
                temporary_path.replace(saved_path)
                row.update(
                    local_path=str(saved_path),
                    size_bytes=saved_path.stat().st_size,
                )
                if saved_path.suffix == ".html":
                    row.update(status="not_a_resume", detail="Received HTML, not a resume file")
                    log.info("  – %s  → HTML page (saved for inspection)", candidate.name)
                    report.writerow(row)
                    report_file.flush()
                    continue

                text_characters = len(extract_text(str(saved_path)).strip())
                row["text_characters"] = text_characters
                if text_characters < MIN_RESUME_TEXT_CHARS:
                    row.update(
                        status="insufficient_text",
                        detail=f"Extracted fewer than {MIN_RESUME_TEXT_CHARS} characters",
                    )
                    log.info("  – %s  → %d chars (below minimum)", candidate.name, text_characters)
                else:
                    row.update(status="usable")
                    usable += 1
                    log.info(
                        "  ✓ %s  → %s (%d bytes, %d chars)",
                        candidate.name,
                        saved_path.name,
                        saved_path.stat().st_size,
                        text_characters,
                    )
            except Exception as exc:
                temporary_path.unlink(missing_ok=True)
                row["detail"] = str(exc)
                log.warning("  ✗ %s  → %s", candidate.name, exc)

            report.writerow(row)
            report_file.flush()

    log.info("Resume verification done: %d/%d downloaded", downloaded, len(candidates))
    log.info(
        "Usable by worker: %d/%d (at least %d extracted characters)",
        usable,
        len(candidates),
        MIN_RESUME_TEXT_CHARS,
    )
    log.info("Download report → %s", DOWNLOAD_REPORT)


# ── HTTP helpers ──────────────────────────────────────────────
session = requests.Session()
session.headers["User-Agent"] = "CandidateCollector/1.0 (research-only)"


def get(url, params=None, headers=None, pause=1.5):
    time.sleep(pause)
    try:
        r = session.get(url, params=params, headers=headers, timeout=10)
        if r.status_code == 429 or (r.status_code == 403 and "github" in url):
            log.warning("Rate limited on %s — waiting 15s", url)
            time.sleep(15)
            return None
        if not r.ok:
            try:
                detail = r.json()
                msg = (
                    detail.get("error", {}).get("message") or detail.get("message") or r.text[:200]
                )
            except Exception:
                msg = r.text[:200]
            log.warning("HTTP %s on %s: %s", r.status_code, url, msg)
            return None
        return r.json()
    except Exception as e:
        log.warning("Request failed (%s): %s", url, e)
        return None


def clean_email(raw: str) -> str | None:
    if not raw:
        return None
    try:
        return validate_email(raw, check_deliverability=False).normalized
    except EmailNotValidError:
        return None


def _google_drive_file_id(url: str) -> str | None:
    """Return a Google Drive file ID from a share/download URL, if present."""
    parsed = urlparse(url)
    if parsed.hostname not in {"drive.google.com", "www.drive.google.com"}:
        return None

    match = _DRIVE_FILE_PATH_RE.match(parsed.path)
    if match:
        return match.group(1)

    # Handles /open?id=<id> and /uc?export=download&id=<id> links.
    return parse_qs(parsed.query).get("id", [None])[0]


def canonical_google_drive_url(url: str) -> str | None:
    """Convert a Drive result into the stable share URL stored in exports."""
    file_id = _google_drive_file_id(url)
    if not file_id:
        return None
    return f"https://drive.google.com/file/d/{quote(file_id, safe='')}/view"


def google_drive_download_url(url: str) -> str:
    """Return Drive's download endpoint, or leave a non-Drive URL unchanged."""
    file_id = _google_drive_file_id(url)
    if not file_id:
        return url
    return f"https://drive.google.com/uc?export=download&id={quote(file_id, safe='')}"


def dedup(candidates: list[Candidate]) -> list[Candidate]:
    seen, out = set(), []
    for c in candidates:
        key = (c.name.lower().strip(), c.email or c.resume_url or "")
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out


# ── Source 1: GitHub REST API ─────────────────────────────────
def from_github(query: str, limit: int, sheet: LocalSheet) -> list[Candidate]:
    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"

    pause = 1.2 if GITHUB_TOKEN else 6.5
    results = []
    page = 1

    while len(results) < limit:
        log.info("GitHub › page %d  (%d collected)", page, len(results))
        data = get(
            "https://api.github.com/search/users",
            params={"q": f"{query} in:bio", "per_page": 30, "page": page},
            headers=headers,
            pause=pause,
        )
        if not data or not data.get("items"):
            break

        for user in data["items"]:
            if len(results) >= limit:
                break
            profile = get(
                f"https://api.github.com/users/{user['login']}",
                headers=headers,
                pause=pause,
            )
            if not profile:
                continue

            name = profile.get("name") or profile.get("login")
            email = clean_email(profile.get("email") or "")
            site = profile.get("blog") or ""
            if site and not site.startswith("http"):
                site = "https://" + site
            resume_url = site or profile.get("html_url")

            if not name or (not email and not resume_url):
                continue

            c = Candidate(
                name=name,
                email=email,
                resume_url=resume_url,
                location=profile.get("location"),
                source="github",
            )
            results.append(c)
            sheet.append_complete(c)
            log.info("  ✓ %s  email=%s", name, email or "(none)")

        page += 1
        if page > 10:
            break

    return results


# Sites that host fake/template resumes — skip them
_JUNK_DOMAINS = {
    "qwikresume.com",
    "resumeworded.com",
    "enhancv.com",
    "novoresume.com",
    "zety.com",
    "kickresume.com",
    "resumegenius.com",
    "resume.io",
    "cloudfront.net",
    "livecareer.com",
    "resumehelp.com",
    "visualcv.com",
    "resumelab.com",
    "myperfectresume.com",
    "resumebuilder.com",
    "assets.qwikresume.com",
}

_NAME_RE = re.compile(r"^([A-Z][a-z]+(?: [A-Z][a-z]+){1,3})")


def _is_junk(link: str, title: str) -> bool:
    from urllib.parse import urlparse

    domain = urlparse(link).netloc.lstrip("www.")
    if any(j in domain for j in _JUNK_DOMAINS):
        return True
    junk_titles = {
        "resume",
        "resume.pdf",
        "cv",
        "curriculum vitae",
        "python developer",
        "software developer resume",
    }
    if title.lower().strip() in junk_titles:
        return True
    return False


def _parse_name(title: str) -> str | None:
    """Extract a real person name from a search result title."""
    # "John Doe - Python Developer" or "John Doe Resume" etc.
    title = re.sub(r"\s*[-|–—]\s*.*$", "", title).strip()  # drop suffix after dash
    title = re.sub(r"\s*(resume|cv|portfolio|\.pdf).*", "", title, flags=re.I).strip()
    m = _NAME_RE.match(title)
    if m:
        name = m.group(1)
        # reject if it's a generic phrase
        if len(name.split()) >= 2 and not any(
            w.lower()
            in ("python", "developer", "engineer", "resume", "software", "backend", "frontend")
            for w in name.split()
        ):
            return name
    return None


# ── Source 2: Serper.dev (Google Search API) ─────────────────
_SERPER_QUERIES = [
    # Put this first: the collector's exported resume_url is suitable for the
    # ingest worker when Serper finds a public Drive-hosted resume.
    'intitle:"{query}" resume pdf site:drive.google.com',
    '"{query}" resume site:github.io',
    '"{query}" resume filetype:pdf',
    'intitle:"resume" "{query}" site:linkedin.com/in',
    '"{query}" portfolio contact site:*.io OR site:*.dev OR site:*.me',
    '"{query}" site:github.io cv',
    '"{query}" resume site:*.github.io -template -sample',
    'filetype:pdf "{query}" resume engineer',
    '"{query}" developer resume contact email',
    '"{query}" developer site:about.me OR site:career.io',
]


def from_serper(query: str, limit: int, sheet: LocalSheet) -> list[Candidate]:
    if not SERPER_API_KEY:
        log.info("Serper skipped — set SERPER_API_KEY in .env to enable")
        return []

    results: list[Candidate] = []
    seen_links: set[str] = set()

    for q_template in _SERPER_QUERIES:
        if len(results) >= limit:
            break

        q = q_template.replace("{query}", query)

        # Paginate: Serper supports page=1,2,3... each returning up to 10 results
        for page in range(1, 6):
            if len(results) >= limit:
                break
            log.info("Serper › '%s'  page=%d", q, page)
            try:
                resp = session.post(
                    "https://google.serper.dev/search",
                    headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
                    json={"q": q, "num": 10, "page": page},
                    timeout=10,
                )
                resp.raise_for_status()
                items = resp.json().get("organic", [])
            except Exception as e:
                log.warning("Serper request failed: %s", e)
                break

            if not items:
                break  # no more pages

            new_on_page = 0
            for item in items:
                if len(results) >= limit:
                    break
                title = item.get("title", "")
                link = item.get("link", "")
                snippet = item.get("snippet", "")

                # Preserve a public Google Drive *share* link in the export,
                # rather than Serper's variant (for example /open?id=...).
                # The app accepts this URL directly and converts it to a download
                # URL when it evaluates the candidate.
                drive_link = canonical_google_drive_url(link)
                if drive_link:
                    link = drive_link

                if not link or link in seen_links:
                    continue
                if _is_junk(link, title):
                    log.debug("  skip junk: %s", link)
                    continue

                name = _parse_name(title)
                if not name:
                    log.debug("  skip (no real name): %s", title)
                    continue

                seen_links.add(link)
                new_on_page += 1

                # Grab email from snippet if visible; enrichment will fetch the rest
                em = EMAIL_RE.search(snippet)
                email = clean_email(em.group()) if em else None

                c = Candidate(name=name, email=email, resume_url=link, source="serper")
                results.append(c)
                if email:
                    sheet.append(c)
                    log.info("  ✓ %s  %s  →  %s", name, email, link[:55])
                else:
                    log.info("  · %s  (no email yet)  →  %s", name, link[:55])

            if new_on_page == 0:
                break  # page had nothing new — stop paginating this query

            time.sleep(1.0)

    return results


# ── Main ──────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", default="python developer", help="Search keyword")
    ap.add_argument("--limit", type=int, default=20, help="Max candidates per source")
    ap.add_argument("--source", default="all", choices=["all", "github", "google"])
    ap.add_argument("--no-enrich", action="store_true", help="Skip email enrichment step")
    ap.add_argument("--no-browser", action="store_true", help="Don't auto-open browser")
    ap.add_argument(
        "--verify-output",
        action="store_true",
        help="Download and validate resume URLs already in output/candidates.csv, then exit",
    )
    ap.add_argument(
        "--verify-resumes",
        action="store_true",
        help="After collecting, download and validate every collected resume URL",
    )
    args = ap.parse_args()

    if args.verify_output:
        try:
            verify_resume_downloads(_load_collected_candidates())
        except FileNotFoundError as exc:
            ap.error(str(exc))
        return

    sheet = LocalSheet()

    if not args.no_browser:
        webbrowser.open(OUTPUT_HTML.as_uri())

    collected: list[Candidate] = []

    if args.source in ("all", "github"):
        gh = from_github(args.query, args.limit, sheet)
        log.info("GitHub: %d", len(gh))
        collected.extend(gh)

    if args.source in ("all", "google"):
        sr = from_serper(args.query, args.limit, sheet)
        log.info("Serper: %d", len(sr))
        collected.extend(sr)

    # ── Enrich: fetch emails from pages/PDFs that had none in snippet ──
    if not args.no_enrich:
        enrich_all(collected, sheet)

    final = dedup([c for c in collected if c.name and c.resume_url])

    sheet.close()

    log.info("─" * 42)
    log.info("Total collected : %d", len(collected))
    log.info("After dedup     : %d", len(final))
    log.info("With email      : %d", sum(1 for c in final if c.email))
    log.info("CSV  → %s", OUTPUT_CSV)
    log.info("HTML → %s", OUTPUT_HTML)

    export_xlsx(final)
    if args.verify_resumes:
        verify_resume_downloads(final)
    log.info("Open candidates.xlsx and upload via POST /jobs/<id>/candidates")


if __name__ == "__main__":
    main()
