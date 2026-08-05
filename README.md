# Right Hire — ATS Checker

AI-powered resume screening pipeline. Upload an Excel or CSV sheet of candidates against a job description, get back Fit / Maybe / Reject verdicts with rubric breakdowns.

## Quick start

Everything on the host (recommended for local dev — lets `local` backend reach an Ollama
instance on `localhost` or a GPU box on your LAN):

```bash
cp .env.example .env               # edit DB creds and LLM settings
ollama pull qwen2.5:7b             # judge model
ollama pull bge-m3                 # embeddings (or any embed model)
docker compose up -d mysql redis   # DB + queue only — ports remapped to :3307 / :6380
pip install -e ".[dev]"
make migrate                       # alembic upgrade head — creates the schema
make seed                          # loads demo job + 5 candidates (creates a demo user too)
make run                           # FastAPI on :8001
make worker                        # RQ worker — separate terminal
make ui                            # optional UI on :3000 (Reflex dev server)
```

Or fully containerized (`app`/`worker` now have a `Dockerfile`):

```bash
cp .env.example .env
# set DATABASE_URL to the in-network hostname docker-compose.yml expects:
#   mysql+pymysql://ats:ats@mysql:3306/ats
# (REDIS_URL is overridden automatically to the compose-managed redis service)
docker compose up -d
docker compose exec app alembic upgrade head
```

Every route requires an API key — multi-user, no passwords, just a bearer-style header:

```bash
curl -X POST localhost:8001/auth/signup -d '{"email":"you@example.com"}' -H 'content-type: application/json'
# → {"user_id": "...", "email": "...", "api_key": "rh_..."}  — shown once, save it

curl localhost:8001/jobs -H 'X-API-Key: rh_...'
```

The UI has a "Sign up" box in the sidebar that does this for you and remembers the key in
the browser's localStorage.

Signup grants a few free trial credits (`SIGNUP_FREE_CREDITS`, default 3 — 1 credit = 1
candidate evaluated). Running out returns `402` from `POST /jobs/{id}/candidates`; billing is
deliberately manual for this MVP (no card data touches the app) — see `POST
/billing/request-credits` and the [Billing section of CLAUDE.md](CLAUDE.md#billing).

Switch to cloud LLM at any time — no code change needed:

```bash
LLM_BACKEND=groq GROQ_API_KEY=gsk_... make run
```

Tables are also auto-created on startup (`Base.metadata.create_all` in `app/main.py`'s
lifespan) as a zero-friction dev convenience — `make migrate` is what a real deployment
should rely on instead. Set `AUTO_CREATE_TABLES=false` once Alembic owns your schema.

To point `local` backend at a GPU machine on your network instead of `localhost`, set in `.env`:
```
OLLAMA_URL=http://<gpu-host-ip>:11434
JUDGE_MODEL=<model pulled on that host>
```
Embeddings always run locally via `sentence-transformers` (`app/pipeline/embed.py`), regardless of `OLLAMA_URL` — the GPU host is only used for parse/judge calls.

## Architecture

```
Excel/CSV + Drive links + JD  →  FastAPI (ingest)  →  Redis queue (RQ)
                                                        ↓
                              ┌─────────── Worker pipeline ───────────┐
                              │ parse → filter → embed → match → judge │
                              └────────────────────────────────────────┘
                                                        ↓
                          MySQL (results, cache)  →  FastAPI (read)  →  UI
```

## Pipeline stages

| Stage | What it does |
|---|---|
| **Parse** | Extract text (PyMuPDF → pdfplumber → Tesseract OCR), LLM → structured JSON |
| **Filter** | Hard rules: YOE, location, must-have skills → instant Reject if failed |
| **Embed** | bge-m3 on experience bullets → float32 vector |
| **Match** | Skill overlap + cosine similarity + matched bullet extraction |
| **Judge** | LLM rubric prompt on pre-extracted signals → scored JSON (≤200 tokens) |
| **Score** | Weighted aggregate → Fit / Maybe / Reject |

## LLM backends

Set `LLM_BACKEND` in `.env`:

| Value | Provider | Needs |
|---|---|---|
| `local` | Ollama | `OLLAMA_URL`, `JUDGE_MODEL` |
| `groq` | Groq API | `GROQ_API_KEY` |
| `openai` | OpenAI | `OPENAI_API_KEY` |

## API

All endpoints below except `/auth/signup` and `/health` require an `X-API-Key` header.
Jobs are scoped per user — you'll only ever see your own.

| Endpoint | Description |
|---|---|
| `POST /auth/signup` | Create a user, get back an API key (shown once), rate-limited |
| `POST /auth/rotate-key` | Rotate your API key (requires the current one) |
| `GET /billing/credits` | Your current credit balance |
| `POST /billing/request-credits` | Request more credits (manual, human-approved — see CLAUDE.md) |
| `POST /jobs` | Create job, parse JD |
| `GET /jobs` | List your jobs |
| `GET /jobs/{id}` | Job details + stats |
| `POST /jobs/{id}/candidates` | Upload Excel or CSV, enqueue pipeline (costs 1 credit/row) |
| `POST /jobs/{id}/candidates/{cid}/resume` | Attach a resume file directly to a candidate (pdf/txt/md), re-queue it |
| `DELETE /jobs/{id}/candidates/{cid}` | Delete a candidate + their evaluation (GDPR-style removal) |
| `GET /jobs/{id}/results` | Paginated results (filter by verdict, `offset`/`limit`) |
| `GET /jobs/{id}/results/export` | Same results as CSV, for sharing with a hiring manager |
| `GET /jobs/{id}/stats` | Score distribution, verdict counts, suggested thresholds |
| `GET /evaluations/{id}` | Single evaluation detail |
| `GET /health` | DB + Redis reachability check |

## Testing

```bash
make test       # unit + integration tests, FakeLLMProvider — no GPU needed
make test-int   # integration only
make eval       # precision@k against labeled CSV
```

## Excel / CSV format

Same column layout for both — `.xlsx` and `.csv` are parsed with the same header-alias table (`app/pipeline/ingest.py`), so either format can be uploaded via `POST /jobs/{id}/candidates` or the Reflex UI's "Upload Candidates" page.

| Column | Required |
|---|---|
| `name` | Yes |
| `email` | Yes |
| `resume_url` | Yes (Google Drive share link or direct URL — the worker downloads and extracts text from this automatically) |
| `yoe` | No |
| `location` | No |

No `resume_url`, or the link is unreachable? Attach the file directly instead via
`POST /jobs/{id}/candidates/{candidate_id}/resume` (pdf/txt/md).
