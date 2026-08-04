# Right Hire — ATS Checker

AI-powered resume screening pipeline. Upload an Excel sheet of candidates against a job description, get back Fit / Maybe / Reject verdicts with rubric breakdowns.

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

## Architecture

```
Excel + Drive links + JD  →  FastAPI (ingest)  →  Redis queue (RQ)
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
| `POST /jobs/{id}/candidates` | Upload Excel, enqueue pipeline |
| `GET /jobs/{id}/results` | Paginated results (filter by verdict) |
| `GET /evaluations/{id}` | Single evaluation detail |

## Testing

```bash
make test       # unit + integration tests, FakeLLMProvider — no GPU needed
make test-int   # integration only
make eval       # precision@k against labeled CSV
```

## Excel format

| Column | Required |
|---|---|
| `name` | Yes |
| `email` | Yes |
| `resume_url` | Yes (Google Drive share link or direct URL) |
| `yoe` | No |
| `location` | No |
