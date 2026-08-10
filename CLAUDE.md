# CLAUDE.md — Right Hire ATS Checker

## What this project is

AI-powered resume screening pipeline. Candidates are ingested from Excel or CSV, evaluated through a 7-stage pipeline (parse → filter → embed → match → judge → score), and stored with a Fit / Maybe / Reject verdict. The LLM backend is swappable via one env var with no code changes.

---

## Setup

**MySQL and Redis are managed services — `docker-compose.yml` builds only `app` and
`worker`.** There is no local infra to bring up first, and nothing in the repo listens on
3306/6379. `DATABASE_URL` points at hosted MySQL (the example uses filess.io); Redis is
either a plain local container or Upstash via `UPSTASH_REDIS_REST_*`.

```bash
cp .env.example .env          # set DATABASE_URL, Redis, LLM_BACKEND, OLLAMA_URL
docker run -d -p 6379:6379 redis:7-alpine   # local dev queue; or set Upstash creds instead
pip install -e ".[dev]"
make migrate                  # alembic upgrade head — creates the schema
make run                      # FastAPI on :8001 (Makefile hardcodes this port, not :8000)
make worker                   # RQ worker — separate terminal
make ui                       # optional UI on :3000 (Reflex dev server) — reads config.ini [ui] api_base
```

Containerized app/worker (same `.env`, same managed backing services):
`docker compose up -d`, then `docker compose exec app alembic upgrade head`.

`Settings.effective_redis_url` prefers Upstash when both `UPSTASH_REDIS_REST_*` vars hold
**real** values, else falls back to `REDIS_URL`. Values still containing `<` are treated as
unfilled placeholders and ignored (`Settings._is_real`) — a half-edited `.env` falls back
instead of silently pointing the queue at a nonexistent host.

Fully containerized: `docker compose up -d` (builds `app`/`worker` from the root `Dockerfile`),
then `docker compose exec app alembic upgrade head`.

Tables are also auto-created on startup (`Base.metadata.create_all` in `app/main.py`'s
lifespan, gated by `AUTO_CREATE_TABLES` — default `true`) as a zero-friction dev convenience.
Set `AUTO_CREATE_TABLES=false` once Alembic is the source of truth for a deployment's schema —
running both against the same DB will fight each other (`create_all` can't add columns to a
table Alembic already created differently).

Every route requires `X-API-Key` (see [Auth](#auth) below) — get one via `POST /auth/signup`
before calling anything else, or use the UI's sidebar sign-up box. Signup grants
`SIGNUP_FREE_CREDITS` (default 3) trial credits; see [Billing](#billing) below.

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
| `make migrate` | `alembic upgrade head` |
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
  auth.py          # API-key auth: hash/verify + get_current_user dependency
  models.py        # ORM: User, Job, Candidate, Evaluation
  schemas.py       # Pydantic: ParsedResume, ParsedJD, JudgeOutput, API I/O
  main.py          # FastAPI app + router registration, logging, request-ID middleware, /health
  api/             # Route handlers (auth, billing, jobs, ingest, results)
  llm/             # LLM abstraction layer (see below)
  pipeline/        # One file per stage: ingest, parse, filters, embed, match, judge, score
  skills/          # taxonomy.json + canonicalize.py (MiniLM similarity)
  workers/tasks.py # RQ task: full pipeline per candidate
prompts/           # parse_resume.txt, parse_jd.txt, judge.txt  ({{PLACEHOLDER}} substitution)
grammars/          # judge.gbnf  — forces valid JSON from local LLM
alembic/           # DB migrations — alembic.ini lives at repo root
Dockerfile         # shared image for `app` and `worker` (docker-compose sets the command)
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

## Auth

Every route (except `/auth/signup` and `/health`) requires an `X-API-Key` header, checked by
`get_current_user()` in `app/auth.py`. There's no login/session/JWT — just a random key per user:

```python
from app.auth import get_current_user
from app.models import User

@router.get("/jobs")
async def list_jobs(db=Depends(get_db), user: User = Depends(get_current_user)): ...
```

- `POST /auth/signup {email}` → creates a `User`, returns the raw key **once**. Only its
  SHA-256 hash (`User.api_key_hash`) is stored. Rate-limited to 5 signups/hour per client IP
  (in-memory, per-process — see `_check_signup_rate_limit` in `app/api/auth.py`).
- `POST /auth/rotate-key` (authenticated with the *current* key) issues a new key and
  invalidates the old one immediately. This is voluntary rotation, not lost-key recovery — a
  truly lost key still means signing up again, since there's no email-verification flow to
  prove ownership of an existing account. Fine for MVP.
- `Job.user_id` scopes ownership; `Candidate`/`Evaluation` inherit scoping transitively through
  their `job_id`. Every route that takes a `job_id` must call `app.api.jobs._get_owned_job()`
  (or otherwise filter by `Job.user_id == user.id`) — it 404s (not 403) on someone else's job,
  so existence isn't leaked to a caller who doesn't own it.
- The UI stores the key client-side in `localStorage` (`AppState.api_key` in
  `ui/right_hire_ui/states/app_state.py`) and sends it on every request from `api_client.py`.

---

## Billing

Deliberately manual for MVP — no card data or payment webhooks touch this app, so there's no
PCI surface and no payment-policy pages to have ready yet. See `app/api/billing.py`.

- Every user starts with `SIGNUP_FREE_CREDITS` (default 3). 1 credit = 1 candidate queued for
  evaluation (`app/api/ingest.py` checks `user.credits` before accepting a batch and returns
  `402` if there aren't enough; deducts only for rows actually enqueued).
- `POST /billing/request-credits` logs the request and returns `PAYMENT_LINK_URL` (an external
  page — Stripe Payment Link, PayPal.me, whatever the operator sets up) if configured.
- `POST /billing/admin/grant-credits {email, credits}` — the operator calls this **by hand**
  after manually confirming a payment came in, authenticated with a shared `ADMIN_API_KEY`
  header (`X-Admin-Key`), not a per-user key. Disabled (`501`) if `ADMIN_API_KEY` is unset.
- `GET /billing/credits` — current balance for the caller.

---

## Data models

| Table | Key columns |
|---|---|
| `users` | id (UUID str), email (unique), api_key_hash (sha256 hex, unique), credits (int, default 3) |
| `jobs` | id (UUID str), user_id (FK → users), title, jd_raw, jd_parsed (JSON), weights (JSON), thresholds (JSON) |
| `candidates` | id, job_id, name, email, yoe (float), location, resume_url, resume_text, parsed (JSON), embedding (LONGBLOB), status |
| `evaluations` | id, candidate_id, job_id, rubric (JSON), score (float), verdict (Fit/Maybe/Reject), reasons (JSON), model_used, cache_key |

- `Candidate.status` enum: `pending → processing → done | failed`. A `failed` candidate always
  gets an `Evaluation` row with `reasons.error` set (no score/verdict) — worker exceptions are
  never silent, see `workers/tasks.py`'s except block. Enqueue failures in `app/api/ingest.py`
  are recorded the same way, so nothing sits at `pending` forever with no visible cause.
- `Evaluation.cache_key` = `sha256(resume_text + json(jd_parsed) + json(weights) + json(thresholds))`
  — weights/thresholds are part of the key so recalibrating a job's thresholds doesn't serve a
  stale cached verdict from before the change.
- Embeddings stored as `float32` bytes: use `vec_to_bytes()` / `bytes_to_vec()` from `app/pipeline/embed.py`
- No DB-level `ON DELETE CASCADE` from `evaluations`/`candidates` to their parents — code that
  deletes a candidate (`DELETE /jobs/{id}/candidates/{id}`) must delete its `Evaluation` row
  explicitly first.

Schema changes require a new Alembic migration (`alembic revision --autogenerate -m "..."` then `make migrate`). Never edit existing migration files — the latest is `alembic/versions/0002_add_user_credits.py`.

---

## Pipeline stages

Each stage is a pure function in its own file. The RQ task in `workers/tasks.py` orchestrates them.

| Stage | File | Contract |
|---|---|---|
| Resolve resume | `workers/tasks.py:_resolve_resume_text` | Fetches `resume_url` (Drive/HTTP via `pipeline/ingest.py:fetch_drive_file`) if no local file/text yet; raises (→ candidate marked `failed`) if no text can be produced — never silently scores an empty resume |
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

> **⚖️ Score = Weighted Composite, Not Similarity**
> The final score must reflect four separate signals — skills match, experience level, tenure
> relevance, and role title trajectory — each with its own weight. Do **not** collapse these into
> a single semantic similarity between resume text and JD text. Cosine similarity is one input
> (`weight: 0.20`), not the answer; it is trivially gameable by keyword stuffing. The judge LLM
> rubric (`weight: 0.50`) exists precisely to catch what embedding distance misses.

> **📊 Normalize Per Batch, Not Globally**
> A score of `0.67` is meaningless in isolation. Scores only have interpretive value relative to
> the current candidate pool. The `fit` / `maybe` thresholds (`0.70` / `0.40`) are starting
> defaults, not universal constants — they should be calibrated against the score distribution
> histogram of each batch. When building eval tooling or UI, always show the distribution
> alongside individual scores; never surface a verdict without its peer context.

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
| `JUDGE_MODEL` | `qwen2.5:7b` | Any model available in Ollama |
| `JUDGE_MAX_TOKENS` | `200` | Keep ≤300 |
| `EMBED_MODEL` | `all-MiniLM-L6-v2` | `.env.example` sets `BAAI/bge-m3` — either works, MiniLM is smaller/faster |
| `DATABASE_URL` | `mysql+pymysql://ats:ats@localhost:3306/ats` | Sync URL (workers) |
| `REDIS_URL` | `redis://localhost:6379/0` | Queue + verdict cache |
| `STORAGE_DIR` | `./storage` | Resume file storage path |
| `GROQ_API_KEY` | _(empty)_ | Required when `LLM_BACKEND=groq` |
| `CASCADE_MODEL` | `llama-3.3-70b-versatile` | Chat model used by `GroqProvider` — Groq periodically decommissions older models (e.g. `llama3-8b-8192`), check https://console.groq.com/docs/deprecations if calls start 400ing |
| `OPENAI_API_KEY` | _(empty)_ | Required when `LLM_BACKEND=openai` |
| `OPENAI_MODEL` | `gpt-4o-mini` | Chat model used by `OpenAIProvider` |
| `OPENAI_EMBED_MODEL` | `text-embedding-3-small` | Embedding model used by `OpenAIProvider.embed()` |
| `CORS_ORIGINS` | `*` | Comma-separated allowlist, e.g. `https://app.example.com,http://localhost:3000` — a startup warning logs if left as `*` |
| `MAX_UPLOAD_MB` | `10` | Hard cap on candidate-sheet and resume-file upload size |
| `AUTO_CREATE_TABLES` | `true` | Dev convenience via `create_all`; auto-skipped (with a warning) if an `alembic_version` table already exists |
| `SIGNUP_FREE_CREDITS` | `3` | Trial credits granted on signup, no payment needed |
| `PAYMENT_LINK_URL` | _(empty)_ | External payment page shown by `POST /billing/request-credits` |
| `ADMIN_API_KEY` | _(empty)_ | Shared secret for `POST /billing/admin/grant-credits`; endpoint disabled if unset |

`config.py` auto-derives `async_database_url` by replacing `pymysql` → `aiomysql` (or `sqlite` → `aiosqlite` for tests).

The Reflex UI is not configured through these — it reads `API_BASE` env var, falling back to `[ui] api_base` in `config.ini` (default `http://localhost:8001`).

---

## TODOs / known gaps

- CI runs `make lint` + `make test` + `make test-int` on push/PR (`.github/workflows/ci.yml`). It provisions a Redis service container because the ingest route enqueues to a real Redis; MySQL is deliberately absent since tests use in-memory SQLite. `make lint` scopes ruff to `app tests scripts ui` — `alembic/` is excluded on purpose so frozen migration files don't fail formatting.
- `TODO`: `GroqProvider.embed()` always raises `NotImplementedError`; embeddings always fall back to the local SentenceTransformer. Document this if Groq is the primary backend.
- `TODO`: True lost-key recovery (email verification) isn't implemented — `POST /auth/rotate-key` only covers voluntary rotation while you still hold a valid key. A lost key means signing up again with a new email.
- `TODO`: The signup rate limiter (`app/api/auth.py`) is in-memory, per-process — fine for a single `make run` process, but resets on restart and doesn't share state across multiple app processes/replicas. Swap for a Redis-backed limiter before scaling out.
- `TODO`: Billing has no automated payment collection by design (see [Billing](#billing)) — `POST /billing/admin/grant-credits` is a manual, human-run step. There's no dashboard for pending requests yet; the operator watches logs for `Credit request from user_id=...`.
- `TODO`: `app/skills/taxonomy.json` is still tech/business-office skewed (SWE, data, and common cross-functional roles) — skill-overlap scoring will be weaker for roles outside that (trades, healthcare, legal, etc.). Scope the pitch accordingly or expand the taxonomy before selling into those verticals.
- `GET /health` probes DB, Redis, **and** the configured LLM backend, returning `503` + `{"status": "degraded"}` if any is down. The LLM probe calls `LLMProvider.health_check()` — a non-abstract method with a no-op default, overridden per provider to hit a list-models endpoint (never a completion, so it never bills). Its result is cached for 30s so load-balancer polling doesn't hammer the upstream API.
- `docker-compose.yml` builds only `app`/`worker`; MySQL and Redis are managed services configured entirely through `.env`. Don't re-add `environment:` overrides for `REDIS_URL`/`UPSTASH_*` there — they'd shadow the real credentials and point the queue at a service that doesn't exist.
- The RQ queue name was previously inconsistent (`ingest.py` enqueued to `"default"` while `make worker` and `seed_demo.py` used `"ats"`, so candidates silently never got processed). Now fixed — everything enqueues to and consumes `"ats"`. If you add a new enqueue call, use `"ats"`, not `"default"`.
- `[tool.ruff.lint] select` is pinned explicitly in `pyproject.toml` to pyflakes/pycodestyle only (`E4,E7,E9,F`) — newer ruff versions' unconfigured default pulls in a much larger rule set (bugbear, blind-except, etc.) that would flag idiomatic FastAPI patterns like `Depends(...)` as default-argument bugs. Don't remove that `select` line without checking `make lint` still passes cleanly.
