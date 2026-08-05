# CLAUDE.md — Right Hire ATS Checker

## What this project is

AI-powered resume screening pipeline. Candidates are ingested from Excel or CSV, evaluated through a 7-stage pipeline (parse → filter → embed → match → judge → score), and stored with a Fit / Maybe / Reject verdict. The LLM backend is swappable via one env var with no code changes.

---

## Setup

There's no `Dockerfile` for `app`/`worker` yet and no `alembic.ini`, so `docker compose up -d` on its own and `make migrate` both fail. Run infra only in Docker, everything else on the host:

```bash
cp .env.example .env          # set DB creds, LLM_BACKEND, OLLAMA_URL
docker compose up -d mysql redis   # skip app/worker — no Dockerfile yet
                               # ports remapped to :3307 (MySQL) / :6380 (Redis)
                               # on boxes where native mysql/redis-server already own 3306/6379
pip install -e ".[dev]"
make run                      # FastAPI on :8001 (Makefile hardcodes this port, not :8000)
make worker                   # RQ worker — separate terminal
make ui                       # optional UI on :3000 (Reflex dev server) — reads config.ini [ui] api_base
```

Skip `make migrate` — tables are created automatically via `Base.metadata.create_all` in `app/main.py`'s lifespan (dev-only convenience) until Alembic is wired up.

Switch LLM backend (no code change):
```bash
LLM_BACKEND=groq GROQ_API_KEY=gsk_... make run
LLM_BACKEND=openai OPENAI_API_KEY=sk-... make run
```

See [TESTING_GUIDE.md](TESTING_GUIDE.md) for a full end-to-end run (1 job + 15 varied candidates) against either a local GPU Ollama box or a cloud backend, via `scripts/seed_batch_test.py`.

---

## Common commands

| Command | What it does |
|---|---|
| `make run` | `uvicorn app.main:app --reload` on :8001 |
| `make worker` | `rq worker` consuming queue `ats` |
| `make migrate` | `alembic upgrade head` (not yet wired — see TODOs) |
| `make seed` | Load demo job + 5 candidates, enqueue them |
| `make test` | Unit tests only (`tests/unit/`), no external deps |
| `make test-int` | Integration tests, skips `@pytest.mark.local` |
| `make lint` | `ruff check` + `ruff format --check` |
| `make eval` | `scripts/eval_harness.py` — precision@k vs labeled CSV |

---

## Architecture

```
POST /jobs/{id}/candidates (Excel or CSV)
        ↓
  FastAPI (async)  →  MySQL (candidates, jobs)
        ↓  enqueue
  Redis queue "ats"
        ↓
  RQ Worker (sync)
   parse → filter → embed → match → judge → score
        ↓
  MySQL (evaluations) + Redis verdict cache (7d TTL)
        ↓
  GET /jobs/{id}/results
```

**Key constraint:** FastAPI routes are `async`; RQ tasks are synchronous. Workers use a sync SQLAlchemy engine (`create_engine`), not the async one.

`GET /jobs` lists all jobs (used by the UI's job pickers); `GET /jobs/{id}` returns one. Both share `_job_response()` in `app/api/jobs.py` — add new response fields there, not in each route.

---

## Directory map

```
app/
  config.py        # pydantic-settings — all env vars live here
  db.py            # async SQLAlchemy engine + get_db dependency
  models.py        # ORM: Job, Candidate, Evaluation
  schemas.py       # Pydantic: ParsedResume, ParsedJD, JudgeOutput, API I/O
  main.py          # FastAPI app + router registration
  api/             # Route handlers (jobs, ingest, results)
  llm/             # LLM abstraction layer (see below)
  pipeline/        # One file per stage: ingest, parse, filters, embed, match, judge, score
  skills/          # taxonomy.json + canonicalize.py (MiniLM similarity)
  workers/tasks.py # RQ task: full pipeline per candidate
prompts/           # parse_resume.txt, parse_jd.txt, judge.txt  ({{PLACEHOLDER}} substitution)
grammars/          # judge.gbnf  — forces valid JSON from local LLM
alembic/           # DB migrations
tests/
  conftest.py      # FakeLLMProvider + test_db (SQLite) + client fixtures
  unit/            # filters, score, canonicalize — pure function tests
  integration/     # test_pipeline.py (no network), test_api.py (TestClient)
  fixtures/        # sample_jd.json, sample_resumes/
scripts/
  seed_demo.py       # creates demo job + 5 candidates in DB
  seed_batch_test.py # 1 job + 15 varied candidates for manual pipeline/LLM testing
  eval_harness.py    # precision@k evaluation
ui/                  # Reflex app (Python → React/Tailwind) — 3 pages: Create Job, Upload Candidates, Results
  rxconfig.py        # app_name="right_hire_ui"
  right_hire_ui/
    config.py        # API_BASE resolution (env var → config.ini [ui] api_base → localhost:8001)
    api_client.py    # async httpx wrappers around the FastAPI backend
    states/          # rx.State per page (AppState holds the shared GET /jobs cache)
    components/      # theme, layout shell, glass-panel cards, verdict/status badges, job picker
    pages/           # create_job.py, upload_candidates.py, results.py — job pickers backed by GET /jobs
config.ini           # [ui] api_base — UI falls back to this if API_BASE env var unset
TESTING_GUIDE.md      # manual end-to-end run against local GPU or cloud LLM backends
```

---

## LLM layer (the core abstraction)

**Never import a concrete provider directly.** Always use `get_provider()`.

```python
from app.llm.factory import get_provider
provider = get_provider()                        # reads LLM_BACKEND env var
result = provider.complete_json(prompt, Schema)  # → validated Pydantic instance
vecs   = provider.embed(["text1", "text2"])      # → list[list[float]]
```

| Backend | Class | Notes |
|---|---|---|
| `local` | `LocalProvider` | Calls Ollama `/api/chat` + `/api/embeddings`, 3 retries with exp backoff |
| `groq` | `GroqProvider` | OpenAI-compatible; `embed()` raises `NotImplementedError` |
| `openai` | `OpenAIProvider` | `gpt-4o-mini` + `text-embedding-3-small` |

Adding a new provider: subclass `LLMProvider` in `app/llm/`, implement `complete_json` and `embed`, register in `factory.py`.

---

## Data models

| Table | Key columns |
|---|---|
| `jobs` | id (UUID str), title, jd_raw, jd_parsed (JSON), weights (JSON), thresholds (JSON) |
| `candidates` | id, job_id, name, email, yoe (float), location, resume_url, resume_text, parsed (JSON), embedding (LONGBLOB), status |
| `evaluations` | id, candidate_id, job_id, rubric (JSON), score (float), verdict (Fit/Maybe/Reject), reasons (JSON), model_used, cache_key |

- `Candidate.status` enum: `pending → processing → done | failed`
- `Evaluation.cache_key` = `sha256(resume_text + json(jd_parsed))` — used for Redis verdict caching
- Embeddings stored as `float32` bytes: use `vec_to_bytes()` / `bytes_to_vec()` from `app/pipeline/embed.py`

Schema changes require a new Alembic migration (`alembic revision --autogenerate -m "..."` then `make migrate`). Never edit existing migration files.

---

## Pipeline stages

Each stage is a pure function in its own file. The RQ task in `workers/tasks.py` orchestrates them.

| Stage | File | Contract |
|---|---|---|
| Extract text | `pipeline/parse.py:extract_text` | pymupdf → pdfplumber → Tesseract cascade |
| Parse resume | `pipeline/parse.py:parse_resume` | LLM → `ParsedResume` |
| Parse JD | `pipeline/parse.py:parse_jd` | LLM → `ParsedJD` |
| Hard filter | `pipeline/filters.py:apply_filters` | Returns `(bool, reason_or_None)` |
| Embed | `pipeline/embed.py:embed_texts` | Returns `np.ndarray (N, D)` float32 |
| Match | `pipeline/match.py:match_candidate` | Returns dict with skill_overlap, cosine_sim, matched_skills, matched_bullets |
| Judge | `pipeline/judge.py:judge_candidate` | LLM rubric → `JudgeOutput` |
| Score | `pipeline/score.py:aggregate_score` | Weighted combine → `(float, verdict_str)` |

Default weights: `{skill_overlap: 0.30, cosine: 0.20, judge: 0.50}`. Configurable per-job via `jobs.weights`.
Default thresholds: `{fit: 0.70, maybe: 0.40}`. Configurable per-job via `jobs.thresholds`.

---

## Prompt system

Prompts live in `prompts/`. Use `{{PLACEHOLDER}}` substitution — no Jinja, no f-strings.

```python
template = Path("prompts/judge.txt").read_text()
prompt = template.replace("{{REQUIRED_SKILLS}}", required)
```

Prompt token budgets: resume parse ≤512, JD parse ≤512, judge ≤300 (keep judge low — it's called per candidate).

---

## Coding standards

- **Python ≥3.11.** Use `from __future__ import annotations` at the top of every file.
- **Ruff** enforces style: line length 100, target `py311`. Run `make lint` before committing.
- **Pydantic v2** throughout. Use `model_validate()`, `model_dump()`, `model_json_schema()`.
- **SQLAlchemy 2.0** style: `Mapped[T]`, `mapped_column()`, `select()`, `await session.execute()`.
- **No `import *`.** No circular imports — `db.py` and `models.py` must not import from `pipeline/` or `api/`.
- **Singletons via `@lru_cache(maxsize=1)`**: embedding model (`embed.py`) and canonicalizer (`canonicalize.py`) load once per worker process. Never load inside a loop.
- **No comments explaining what code does.** Only comment non-obvious invariants or workarounds.
- All new API endpoints must have a corresponding test in `tests/integration/test_api.py`.

---

## Testing rules

- **Unit tests** (`tests/unit/`): pure functions only, no DB, no network, no LLM. Fast.
- **Integration tests** (`tests/integration/`): use `FakeLLMProvider` + SQLite in-memory. No GPU, no Ollama, no real MySQL.
- **`@pytest.mark.local`**: tests that require a real Ollama instance. These are skipped in CI (`make test-int` uses `-m "not local"`).
- `FakeLLMProvider` is in `tests/conftest.py`. It returns canned `ParsedResume`, `ParsedJD`, `JudgeOutput`. Use it — do not mock individual pipeline functions.
- `asyncio_mode = "auto"` in `pyproject.toml` — async test functions work without `@pytest.mark.asyncio`.

```python
# Correct: use fake_provider fixture from conftest
def test_something(fake_provider):
    result = judge_candidate(match, jd, rubric, fake_provider)
```

---

## Do / Don't

**Do:**
- Call `get_provider()` at task/request time, not at module import.
- Use `ParsedResume`, `ParsedJD`, `JudgeOutput` as the shared data contract between pipeline stages.
- Store `jd_parsed` on the `Job` row immediately at creation time; workers read from it, never re-parse.
- Cap text inputs to prompts (resume ≤6000 chars, JD ≤4000 chars) to stay within context limits.
- Return early from the pipeline on filter failure — write the Evaluation and stop.

**Don't:**
- Import `LocalProvider`, `GroqProvider`, or `OpenAIProvider` outside their own file and `factory.py`.
- Add `await` to RQ task functions — they are sync. Use the sync engine in `workers/tasks.py`.
- Add async dependencies in `workers/tasks.py` — the sync `create_engine` path is intentional.
- Skip Alembic for schema changes. Don't use `Base.metadata.create_all` in production paths (it runs in `lifespan` only for development convenience).
- Add fields to `ParsedResume` / `ParsedJD` / `JudgeOutput` without updating the corresponding prompt in `prompts/`.
- Increase `JUDGE_MAX_TOKENS` above 300 — the judge prompt is designed to be terse.

---

## Environment variables

| Variable | Default | Notes |
|---|---|---|
| `LLM_BACKEND` | `local` | `local` \| `groq` \| `openai` |
| `OLLAMA_URL` | `http://localhost:11434` | Local Ollama instance |
| `JUDGE_MODEL` | `qwen3:8b` | Any model available in Ollama |
| `JUDGE_MAX_TOKENS` | `200` | Keep ≤300 |
| `EMBED_MODEL` | `bge-m3` | Falls back to `all-MiniLM-L6-v2` if unavailable |
| `DATABASE_URL` | `mysql+pymysql://ats:ats@localhost:3306/ats` | Sync URL (workers) |
| `REDIS_URL` | `redis://localhost:6379/0` | Queue + verdict cache |
| `STORAGE_DIR` | `./storage` | Resume file storage path |
| `GROQ_API_KEY` | _(empty)_ | Required when `LLM_BACKEND=groq` |
| `OPENAI_API_KEY` | _(empty)_ | Required when `LLM_BACKEND=openai` |

`config.py` auto-derives `async_database_url` by replacing `pymysql` → `aiomysql` (or `sqlite` → `aiosqlite` for tests).

The Reflex UI is not configured through these — it reads `API_BASE` env var, falling back to `[ui] api_base` in `config.ini` (default `http://localhost:8001`).

---

## TODOs / known gaps

- `TODO`: No Dockerfile yet — `docker compose up` will fail for the `app` and `worker` services until a `Dockerfile` is added.
- `TODO`: `make lint` / CI workflow not yet defined.
- `TODO`: `eval_harness.py` expects a labeled CSV (`candidate_id,expected_verdict`) — no sample provided.
- `TODO`: Alembic `alembic.ini` not yet present — needed for `make migrate` to work. Tables are created ad hoc via `Base.metadata.create_all` in `app/main.py` lifespan instead.
- `TODO`: `GroqProvider.embed()` always raises `NotImplementedError`; embeddings always fall back to the local SentenceTransformer. Document this if Groq is the primary backend.
- `docker-compose.yml` maps MySQL/Redis to host ports `3307`/`6380` (not the `3306`/`6379` defaults in `config.py`) to avoid clashing with native `mysql`/`redis-server` services on dev machines — set `DATABASE_URL`/`REDIS_URL` in `.env` accordingly when running against this compose file.
- The RQ queue name was previously inconsistent (`ingest.py` enqueued to `"default"` while `make worker` and `seed_demo.py` used `"ats"`, so candidates silently never got processed). Now fixed — everything enqueues to and consumes `"ats"`. If you add a new enqueue call, use `"ats"`, not `"default"`.
