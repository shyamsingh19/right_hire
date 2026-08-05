# Right Hire — ATS Checker

AI-powered resume screening pipeline. Upload an Excel or CSV sheet of candidates against a job description, get back Fit / Maybe / Reject verdicts with rubric breakdowns.

## Quick start

```bash
cp .env.example .env          # edit DB creds and LLM settings
ollama pull qwen3:8b          # judge model
ollama pull bge-m3            # embeddings (or any embed model)
docker compose up -d          # starts MySQL + Redis
make migrate                  # runs alembic upgrade head
make seed                     # loads demo job + 5 candidates
make run                      # FastAPI on :8000
make worker                   # RQ worker (separate terminal)
streamlit run ui/app.py       # optional UI on :8501
```

Switch to cloud LLM at any time — no code change needed:

```bash
LLM_BACKEND=groq GROQ_API_KEY=gsk_... make run
```

### Current setup (no Dockerfile / Alembic migration yet)

`app` and `worker` don't have a `Dockerfile` yet, so `docker compose up -d` on its own fails trying to build them. Until that's added, run only the DB/queue containers and everything else on the host:

```bash
docker compose up -d mysql redis   # skip app/worker — no Dockerfile yet
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
make run                           # FastAPI on :8001 (Makefile port, not :8000)
make worker                        # separate terminal
make seed                          # separate terminal — demo job + 5 candidates
curl http://localhost:8001/jobs/<job_id>/results
```

Skip `make migrate` too — `alembic.ini` and `alembic/versions/` migrations don't exist yet. Tables are created automatically on startup instead, via `Base.metadata.create_all` in `app/main.py`'s lifespan (dev-only convenience, not used in production).

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

| Endpoint | Description |
|---|---|
| `POST /jobs` | Create job, parse JD |
| `GET /jobs/{id}` | Job details + stats |
| `POST /jobs/{id}/candidates` | Upload Excel or CSV, enqueue pipeline |
| `GET /jobs/{id}/results` | Paginated results (filter by verdict) |
| `GET /evaluations/{id}` | Single evaluation detail |

## Testing

```bash
make test       # unit + integration tests, FakeLLMProvider — no GPU needed
make test-int   # integration only
make eval       # precision@k against labeled CSV
```

## Excel / CSV format

Same column layout for both — `.xlsx` and `.csv` are parsed with the same header-alias table (`app/pipeline/ingest.py`), so either format can be uploaded via `POST /jobs/{id}/candidates` or the Streamlit "Upload Candidates" page.

| Column | Required |
|---|---|
| `name` | Yes |
| `email` | Yes |
| `resume_url` | Yes (Google Drive share link or direct URL) |
| `yoe` | No |
| `location` | No |
