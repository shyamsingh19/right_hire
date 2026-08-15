# CLAUDE.md — Right Hire ATS Checker

AI-powered resume screening pipeline (parse → filter → embed → match → judge → score) with swappable LLM backends.

---

## Commands

| Command | Action |
|---|---|
| `make install` | Install CPU torch pin + dependencies (`requirements-torch-cpu.txt` + `.[dev]`) |
| `make run` | Run FastAPI on `:8001` (`uvicorn app.main:app --reload`) |
| `make worker` | Run RQ worker on queue `ats` |
| `make ui` | Run Reflex dev UI on `:3000` |
| `make migrate` | Run DB migrations (`alembic upgrade head`) |
| `make seed` | Load demo job + 5 candidates |
| `make test` | Run fast unit tests (`tests/unit/`, pure functions only) |
| `make test-int` | Run integration tests (skips `@pytest.mark.local`) |
| `make lint` | Run `ruff check` + `ruff format --check` |
| `make eval` | Run `scripts/eval_harness.py` (precision@k) |

---

## Architecture & Data Flow

```text
POST /jobs/{id}/candidates (Excel/CSV)
        ↓
FastAPI (Async / MySQL)
        ↓
Redis Queue ("ats")
        ↓
RQ Worker (Sync Pipeline)
        ↓
[parse → filter → embed → match → judge → score]
        ↓
MySQL (evaluations) + Redis Verdict Cache (7d TTL)
        ↓
GET /jobs/{id}/results
```

- **Async vs Sync Boundary:** FastAPI endpoints use `async` SQLAlchemy sessions (`get_db`). RQ tasks in `workers/tasks.py` use **synchronous** engines (`create_engine`).
- **Scoring Breakdown:** Score = Composite (`0.30` Skill Overlap + `0.20` Cosine Sim + `0.50` LLM Judge). Never collapse score to pure semantic cosine similarity.
- **Normalization:** Interpret scores relative to batch distribution, not absolute numbers.
- **Cache Key:** `Evaluation.cache_key = sha256(resume_text + json(jd_parsed) + json(weights) + json(thresholds))`.
- **Delete Constraint:** No DB cascade delete. Deleting a candidate requires deleting its `Evaluation` row first.

---

## Project Structure

```text
app/
├── api/              # Endpoints (auth, billing, jobs, ingest, results)
├── llm/              # LLM abstraction (factory.py, provider base, implementations)
├── pipeline/         # Pure stage functions: parse, filters, embed, match, judge, score
├── skills/           # taxonomy.json, canonicalize.py
├── workers/
│   └── tasks.py      # Sync RQ worker entry point
├── config.py         # pydantic-settings config
├── models.py         # SQLAlchemy 2.0 ORM models
├── schemas.py        # Pydantic v2 schemas (ParsedResume, ParsedJD, JudgeOutput)
├── prompts/          # Templates with {{PLACEHOLDER}} substitution (judge.txt <= 300 tokens)
└── ui/               # Reflex frontend (reads API_BASE or config.ini [ui] api_base)
```

---

## Core Conventions & Rules

### Coding Standards

- Python ≥3.11, `from __future__ import annotations` at the top of every file.
- Pydantic v2 (`model_validate`, `model_dump`) & SQLAlchemy 2.0 (`Mapped[T]`, `select`).
- Singletons via `@lru_cache(maxsize=1)` for embedding models and canonicalizers.
- No `import *`.
- No circular imports (`models.py`/`db.py` must not import from `pipeline/` or `api/`).

### LLM & Pipeline

- **Always** instantiate LLM via `get_provider()` (`app/llm/factory.py`). Never import concrete provider classes directly.
- Hard caps for prompt inputs:
  - Resume ≤6000 chars
  - JD ≤4000 chars
  - Judge tokens ≤300
- `GroqProvider.embed()` falls back to local `SentenceTransformer`.

### Auth & Multi-Tenancy

- All routes require `X-API-Key` (except `/auth/signup` and `/health`).
- Scoping rule: Filter jobs by `Job.user_id == user.id`. Non-owned jobs must return `404` (not `403`).
- 1 candidate evaluation = 1 credit (`SIGNUP_FREE_CREDITS=3`).
- Admin grants via `POST /billing/admin/grant-credits` + `X-Admin-Key`.

### Testing

- Unit: pure functions, no I/O (`tests/unit/`).
- Integration: `FakeLLMProvider` + SQLite in-memory (`tests/integration/`).
- Mark real Ollama tests with `@pytest.mark.local`.

---

## Environment Variables

| Variable | Default | Role |
|---|---|---|
| `LLM_BACKEND` | `local` | `local` \| `groq` \| `openai` |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama host |
| `JUDGE_MODEL` | `qwen2.5:7b` | Local evaluation model |
| `EMBED_MODEL` | `all-MiniLM-L6-v2` | SentenceTransformer embedding model |
| `DATABASE_URL` | `mysql+pymysql://ats:ats@localhost:3306/ats` | Sync DB string (derived to async automatically) |
| `REDIS_URL` | `redis://localhost:6379/0` | RQ queue & cache (auto-prefers Upstash if set) |
| `SIGNUP_FREE_CREDITS` | `3` | Default credits on registration |
| `ADMIN_API_KEY` | `""` | Key for manual billing adjustments |
| `AUTO_CREATE_TABLES` | `true` | Dev table auto-creation (set `false` in prod) |

---

## Self-Maintenance & Anti-Bloat Protocol

1. **Auto-Update on Change:** Whenever dependencies, architecture, endpoints, or environment variables are altered or added, update this file immediately.
2. **Hard Ceiling (150 Lines):** Keep this file under 150 lines. Never add narrative prose, conversational explanations, or post-mortem bug histories.
3. **Information Density:** Use compact markdown tables, ASCII diagrams, or concise bullet lists.
4. **Pruning Rule:** Delete temporary TODOs, fixed bugs, and verbose deployment logs upon task completion. Only store permanent contracts, invariants, and commands.
