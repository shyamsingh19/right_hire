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
import io
import logging
import os
import re
import time
import webbrowser
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import requests
from email_validator import validate_email, EmailNotValidError

# ── Load .env from repo root ──────────────────────────────────
_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

# ── Config ────────────────────────────────────────────────────
GITHUB_TOKEN   = os.getenv("GITHUB_TOKEN", "")
SERPER_API_KEY = os.getenv("SERPER_API_KEY", "")

OUTPUT_DIR   = Path(__file__).resolve().parent.parent / "output"
OUTPUT_CSV   = OUTPUT_DIR / "candidates.csv"
OUTPUT_HTML  = OUTPUT_DIR / "candidates.html"
OUTPUT_XLSX  = OUTPUT_DIR / "candidates.xlsx"

OUTPUT_DIR.mkdir(exist_ok=True)

# Columns written to CSV / HTML
FIELDS = ["name", "email", "resume_url", "yoe", "location", "source", "collected_at"]
# ATS Excel columns (subset, required by ingest API)
ATS_FIELDS = ["name", "email", "resume_url", "yoe", "location"]

EMAIL_RE = re.compile(r"[\w.+\-]+@[\w\-]+\.[a-z]{2,}")

# ── Logging ───────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)


# ── Data model ────────────────────────────────────────────────
@dataclass
class Candidate:
    name:         str
    email:        str | None = None
    resume_url:   str | None = None
    yoe:          int | None = None
    location:     str | None = None
    source:       str        = ""
    collected_at: str        = ""


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
        self._writer   = csv.DictWriter(self._csv_file, fieldnames=FIELDS)
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
        ts   = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
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
                    val  = f'<a href="{val}" target="_blank">{disp}</a>'
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
            self._HTML_HEAD
            + f'<div class="meta">&#128260; Auto-refreshes every 4 s &nbsp;|&nbsp; '
            f'{len(rows)} candidates &nbsp;|&nbsp; '
            f'emails found: {has_email}/{len(rows)} &nbsp;|&nbsp; '
            f'last update: {ts}</div>\n'
            + "<table><thead><tr>" + header_cells + "</tr></thead><tbody>"
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
        resp = requests.get(c.resume_url, timeout=10, stream=True,
                            headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "")

        if "pdf" in content_type or c.resume_url.lower().endswith(".pdf"):
            raw = resp.content
            # Try pdfplumber first, fall back to pymupdf
            try:
                import pdfplumber
                with pdfplumber.open(io.BytesIO(raw)) as pdf:
                    text = "\n".join(p.extract_text() or "" for p in pdf.pages[:3])
            except Exception:
                try:
                    import fitz  # pymupdf
                    doc  = fitz.open(stream=raw, filetype="pdf")
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
            sheet.append_complete(c)   # write to sheet only now that it's complete
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
        cell.font  = header_font
        cell.fill  = header_fill
        cell.alignment = Alignment(horizontal="center")

    for c in candidates:
        ws.append([
            c.name or "",
            c.email or "",
            c.resume_url or "",
            c.yoe if c.yoe is not None else "",
            c.location or "",
        ])

    # Auto column width
    for col in ws.columns:
        width = max(len(str(cell.value or "")) for cell in col) + 4
        ws.column_dimensions[col[0].column_letter].width = min(width, 60)

    wb.save(OUTPUT_XLSX)
    log.info("✅  Excel → %s  (%d rows)", OUTPUT_XLSX, len(candidates))


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
                msg = detail.get("error", {}).get("message") or detail.get("message") or r.text[:200]
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

    pause   = 1.2 if GITHUB_TOKEN else 6.5
    results = []
    page    = 1

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

            name  = profile.get("name") or profile.get("login")
            email = clean_email(profile.get("email") or "")
            site  = profile.get("blog") or ""
            if site and not site.startswith("http"):
                site = "https://" + site
            resume_url = site or profile.get("html_url")

            if not name or (not email and not resume_url):
                continue

            c = Candidate(name=name, email=email, resume_url=resume_url,
                          location=profile.get("location"), source="github")
            results.append(c)
            sheet.append_complete(c)
            log.info("  ✓ %s  email=%s", name, email or "(none)")

        page += 1
        if page > 10:
            break

    return results


# Sites that host fake/template resumes — skip them
_JUNK_DOMAINS = {
    "qwikresume.com", "resumeworded.com", "enhancv.com", "novoresume.com",
    "zety.com", "kickresume.com", "resumegenius.com", "resume.io",
    "cloudfront.net", "livecareer.com", "resumehelp.com", "visualcv.com",
    "resumelab.com", "myperfectresume.com", "resumebuilder.com",
    "assets.qwikresume.com",
}

_NAME_RE = re.compile(r"^([A-Z][a-z]+(?: [A-Z][a-z]+){1,3})")


def _is_junk(link: str, title: str) -> bool:
    from urllib.parse import urlparse
    domain = urlparse(link).netloc.lstrip("www.")
    if any(j in domain for j in _JUNK_DOMAINS):
        return True
    junk_titles = {"resume", "resume.pdf", "cv", "curriculum vitae",
                   "python developer", "software developer resume"}
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
            w.lower() in ("python", "developer", "engineer", "resume", "software", "backend", "frontend")
            for w in name.split()
        ):
            return name
    return None


# ── Source 2: Serper.dev (Google Search API) ─────────────────
_SERPER_QUERIES = [
    '"{query}" resume site:github.io',
    '"{query}" resume filetype:pdf',
    'intitle:"resume" "{query}" site:linkedin.com/in',
    '"{query}" portfolio contact site:*.io OR site:*.dev OR site:*.me',
    '"{query}" site:github.io cv',
    '"{query}" resume site:*.github.io -template -sample',
    'filetype:pdf "{query}" resume engineer',
    '"{query}" developer resume contact email',
    'intitle:"{query}" resume pdf site:drive.google.com',
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
                title   = item.get("title", "")
                link    = item.get("link", "")
                snippet = item.get("snippet", "")

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
                em    = EMAIL_RE.search(snippet)
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
    ap.add_argument("--query",      default="python developer",
                    help="Search keyword")
    ap.add_argument("--limit",      type=int, default=20,
                    help="Max candidates per source")
    ap.add_argument("--source",     default="all",
                    choices=["all", "github", "google"])
    ap.add_argument("--no-enrich",  action="store_true",
                    help="Skip email enrichment step")
    ap.add_argument("--no-browser", action="store_true",
                    help="Don't auto-open browser")
    args = ap.parse_args()

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
    log.info("Open candidates.xlsx and upload via POST /jobs/<id>/candidates")


if __name__ == "__main__":
    main()
