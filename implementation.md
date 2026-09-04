# Right Hire: ATS Checker — Zero-to-One MVP Implementation Plan

A pluggable LLM provider layer is the spine here: write one `LLMProvider` interface, implement `LocalProvider` (Ollama/llama.cpp) now, leave `GroqProvider`/`OpenAIProvider` as drop-in classes for later. Everything else stays on your stack — FastAPI, Redis, MySQL.

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

MySQL for everything relational. Vectors go in a `VARBINARY` column + in-process FAISS index (no pgvector needed — your corpus is small). Redis = queue + verdict cache. LLM behind an interface, local now.

## Repository structure

```
ats-checker/
├── README.md
├── docker-compose.yml          # mysql, redis, app, worker
├── .env.example
├── pyproject.toml
├── Makefile                    # run, test, lint, seed
├── alembic/                    # MySQL migrations
│
├── app/
│   ├── main.py                 # FastAPI app, routers
│   ├── config.py               # pydantic-settings, reads .env
│   ├── db.py                   # SQLAlchemy session
│   ├── models.py               # ORM: Candidate, Job, Evaluation
│   ├── schemas.py              # Pydantic request/response
│   │
│   ├── api/
│   │   ├── jobs.py             # POST /jobs (create JD), GET /jobs/{id}
│   │   ├── ingest.py           # POST /jobs/{id}/candidates (Excel upload)
│   │   └── results.py          # GET /jobs/{id}/results, /evaluations/{id}
│   │
│   ├── llm/
│   │   ├── base.py             # LLMProvider ABC: .complete_json(prompt, schema)
│   │   ├── local.py            # LocalProvider (Ollama HTTP / llama.cpp)
│   │   ├── groq.py             # GroqProvider (stub, OpenAI-compatible)
│   │   ├── openai.py           # OpenAIProvider (stub)
│   │   └── factory.py          # get_provider() reads LLM_BACKEND env
│   │
│   ├── pipeline/
│   │   ├── ingest.py           # Excel→rows, Drive→bytes→storage
│   │   ├── parse.py            # text extract + LLM structured parse
│   │   ├── filters.py          # hard rules (YOE, location, must-haves)
│   │   ├── embed.py            # bge-m3 → vectors
│   │   ├── match.py            # skill overlap + cosine + rerank
│   │   ├── judge.py            # rubric prompt → scored JSON
│   │   └── score.py            # weighted aggregate → Fit/Maybe/Reject
│   │
│   ├── skills/
│   │   ├── taxonomy.json       # ESCO skill list
│   │   └── canonicalize.py     # MiniLM similarity → canonical skill
│   │
│   └── workers/
│       └── tasks.py            # RQ job: run full pipeline per candidate
│
├── prompts/
│   ├── parse_resume.txt
│   ├── parse_jd.txt
│   └── judge.txt               # few-shot, terse-JSON instructions
│
├── grammars/
│   └── judge.gbnf              # forces valid JSON output (local)
│
├── tests/
│   ├── conftest.py             # fixtures: test db, fake provider
│   ├── unit/
│   │   ├── test_filters.py
│   │   ├── test_score.py
│   │   └── test_canonicalize.py
│   ├── integration/
│   │   ├── test_pipeline.py    # FakeLLMProvider, no network
│   │   └── test_api.py         # TestClient
│   └── fixtures/
│       ├── sample_resumes/
│       └── sample_jd.json
│
├── scripts/
│   ├── seed_demo.py            # load sample Excel + JD
│   └── eval_harness.py         # precision@k vs labeled set
│
└── ui/                         # optional: Streamlit single-file
    └── app.py
```

## The LLM interface (this is the key abstraction)

```python
# app/llm/base.py
class LLMProvider(ABC):
    @abstractmethod
    def complete_json(self, prompt: str, schema: type[BaseModel],
                      max_tokens: int = 256) -> BaseModel: ...

# app/llm/factory.py
def get_provider() -> LLMProvider:
    backend = settings.LLM_BACKEND  # "local" | "groq" | "openai"
    return {"local": LocalProvider, "groq": GroqProvider,
            "openai": OpenAIProvider}[backend]()
```

`LocalProvider` calls Ollama's `/api/chat` with the GBNF grammar + Instructor for retry. Switching to cloud later = change one env var. The pipeline never imports a concrete provider — only `get_provider()`.

## Data model (MySQL)

| Table | Key columns |
|---|---|
| `jobs` | id, title, jd_raw, jd_parsed (JSON), weights (JSON), thresholds (JSON) |
| `candidates` | id, job_id, name, email, yoe, location, resume_url, resume_text, parsed (JSON), embedding (VARBINARY) |
| `evaluations` | id, candidate_id, job_id, rubric (JSON), score, verdict, reasons (JSON), model_used, cache_key, created_at |

Verdict cache key = `sha256(resume_text + jd_parsed)`. Hit → skip pipeline.

## Pipeline flow per candidate (the RQ task)

1. **Parse** — extract text (pymupdf→pdfplumber→Tesseract), LLM → structured JSON
2. **Filter** — hard rules; fail → write `Reject` with rule cited, stop
3. **Embed** — bge-m3 on experience bullets; store vector
4. **Match** — canonical skill overlap + cosine per JD requirement; cross-encoder rerank
5. **Judge** — pass *pre-extracted matched bullets* + JD + rubric → terse JSON scores (≤200 tokens)
6. **Score** — weighted aggregate → threshold → verdict + reasons from rubric

## Build order (do it in this sequence)

| Phase | Deliverable | Validates |
|---|---|---|
| 1 | docker-compose (MySQL+Redis), config, models, alembic | Infra runs |
| 2 | `LLMProvider` + `LocalProvider` + `FakeLLMProvider` | Provider swap works |
| 3 | Ingest: Excel parse + Drive fetch + storage | Data lands in MySQL |
| 4 | Parse + filters (test with Fake provider) | Pipeline shape |
| 5 | Embed + match + canonicalize | Retrieval works |
| 6 | Judge + score + GBNF grammar | End-to-end verdict |
| 7 | RQ wiring + API endpoints | Async batch runs |
| 8 | Streamlit UI + seed script + eval harness | Demo-able |

## How to run (README essentials)

```bash
cp .env.example .env          # set LLM_BACKEND=local, OLLAMA_URL, DB creds
ollama pull qwen3:8b          # judge model
ollama pull bge-m3            # embeddings
docker compose up -d          # mysql + redis
make migrate                  # alembic upgrade head
make seed                     # load demo Excel + JD
make run                      # FastAPI on :8001
make worker                   # RQ worker (separate terminal)
streamlit run ui/app.py       # optional UI on :8501
```

Switch to cloud later: `LLM_BACKEND=groq GROQ_API_KEY=...` — no code change.

## How to test

```bash
make test          # pytest, uses FakeLLMProvider — no GPU, no network
make test-int      # integration: real pipeline, fake LLM, test MySQL
make eval          # precision@k against tests/fixtures labeled set
```

Testing strategy: `FakeLLMProvider` returns canned JSON so CI runs without a GPU or API key. Unit-test `filters`/`score`/`canonicalize` as pure functions. Integration-test the full pipeline with the fake provider. One smoke test hits real Ollama, marked `@pytest.mark.local`, skipped in CI.

## Config that keeps LLM flexible

```bash
# .env.example
LLM_BACKEND=local              # local | groq | openai
OLLAMA_URL=http://localhost:11434
JUDGE_MODEL=qwen3:8b
JUDGE_MAX_TOKENS=200           # the latency lever
EMBED_MODEL=bge-m3
# GROQ_API_KEY=                # uncomment for cloud
# CASCADE_MODEL=               # borderline escalation
DATABASE_URL=mysql+pymysql://user:pass@localhost/ats
REDIS_URL=redis://localhost:6379/0
```

