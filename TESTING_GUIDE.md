# Practical End-to-End Test Guide

One job (Senior Backend Engineer) + 15 varied candidates, run through the real
pipeline (parse → filter → embed → match → judge → score) against either your
local GPU's Ollama or a cloud LLM API. Uses `scripts/seed_batch_test.py`,
which seeds candidates directly with `resume_text` set — no Excel upload or
file hosting needed to exercise the pipeline logic itself.

## 0. Do you need "real" Redis / MySQL?

**No.** The `docker compose up -d mysql redis` containers you already have
behave identically to a hosted Redis/MySQL for everything this pipeline does
— RQ doesn't care where its broker lives, and SQLAlchemy doesn't care where
the DB lives. Get a hosted instance only if you specifically want to test
network latency to a remote service or persistence across machines — neither
matters for validating pipeline correctness or LLM judging quality. If you
want one anyway for extra realism, free tiers exist (Upstash Redis, Railway
or Aiven MySQL), but it's not required for anything in this guide.

## 1. Start infra

```bash
docker compose up -d mysql redis
```

(Already remapped to host ports `3307`/`6380` on this machine since native
`mysql`/`redis-server` system services own `3306`/`6379`.)

## 2. Pick an LLM backend

Edit `.env` — only these lines change between backends, nothing else.

**Local GPU (Ollama on your 12GB box):**
```
LLM_BACKEND=local
OLLAMA_URL=http://192.168.75.107:11434
JUDGE_MODEL=qwen2.5:7b
```

**Groq (cloud):**
```
LLM_BACKEND=groq
GROQ_API_KEY=gsk_...
CASCADE_MODEL=llama3-8b-8192
```
Note: Groq reads the model from `CASCADE_MODEL`, not `JUDGE_MODEL` —
`app/llm/groq.py:22` (`settings.cascade_model or "llama3-8b-8192"`).

**OpenAI (cloud):**
```
LLM_BACKEND=openai
OPENAI_API_KEY=sk-...
```
Uses `gpt-4o-mini` — not currently configurable via `.env`
(`app/llm/openai.py:21`).

Embeddings always run locally via `sentence-transformers` regardless of
backend (`app/pipeline/embed.py`) — this switch only affects parse/judge
calls.

## 3. Run the app + worker

```bash
source .venv/bin/activate

# terminal A
make run

# terminal B
make worker
```

## 4. Seed the test batch

```bash
# terminal C
source .venv/bin/activate
python scripts/seed_batch_test.py
```
Prints the job ID and enqueues 15 candidates on the `ats` queue. Watch
terminal B — that's where parse/judge calls to your chosen backend actually
happen, one per candidate.

The 15 are deliberately mixed:
- 4 fail the hard YOE filter outright (Carol, Grace, Jake, Liam — all under
  the JD's 4-year minimum) and never reach the LLM judge
- The rest span weak-to-strong skill overlap so judge output should vary
  meaningfully, not cluster on one verdict

## 5. Check results

```bash
curl -s http://localhost:8001/jobs/<job_id>/results | python -m json.tool
```
or the Reflex UI:
```bash
make ui   # cd ui && reflex run — dev server on :3000
```
→ "Results" page now has a job dropdown (no more pasting IDs) — pick the
job you just seeded.

## 6. Comparing backends on the same candidates

Verdicts are cached in Redis for 7 days, keyed only on
`sha256(resume_text + jd_parsed)` — **not** on which LLM backend produced
them (`app/workers/tasks.py:33`). If you switch backends and rerun the exact
same job, you'll get the cached verdict back, not a fresh one from the new
backend. To force a clean comparison, flush the cache between runs:
```bash
docker exec right_hire-redis-1 redis-cli FLUSHDB
```
then re-run `python scripts/seed_batch_test.py` (creates a fresh job + new
candidate rows either way, but the cache flush guarantees no stale verdict
reuse from the resume/JD text match).
