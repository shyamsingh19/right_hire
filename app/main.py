from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import inspect, text
from starlette.concurrency import run_in_threadpool

from app import db
from app.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)


def _has_alembic_version_table(sync_conn) -> bool:
    return inspect(sync_conn).has_table("alembic_version")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.auto_create_tables:
        async with db.engine.begin() as conn:
            # If Alembic already manages this schema, create_all must not run alongside
            # it — the two can drift (create_all never alters existing tables). See
            # CLAUDE.md's AUTO_CREATE_TABLES footgun note.
            if await conn.run_sync(_has_alembic_version_table):
                logger.warning(
                    "alembic_version table found — skipping auto_create_tables. "
                    "Set AUTO_CREATE_TABLES=false to silence this."
                )
            else:
                await conn.run_sync(db.Base.metadata.create_all)
    if settings.cors_origins_list == ["*"]:
        logger.warning(
            "CORS_ORIGINS is '*' — fine for local dev, lock this down before a public deploy."
        )
    yield


app = FastAPI(
    title="Right Hire — ATS Checker",
    version="0.1.0",
    description="Automated resume screening pipeline powered by local or cloud LLMs.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_id_and_timing(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    start = time.monotonic()
    response = await call_next(request)
    duration_ms = (time.monotonic() - start) * 1000
    response.headers["X-Request-ID"] = request_id
    logger.info(
        "%s %s %s %.1fms request_id=%s",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
        request_id,
    )
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    request_id = request.headers.get("X-Request-ID", "unknown")
    logger.exception(
        "Unhandled error on %s %s (request_id=%s)", request.method, request.url.path, request_id
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "request_id": request_id},
    )


from app.api import auth, billing, ingest, jobs, results  # noqa: E402

app.include_router(auth.router)
app.include_router(billing.router)
app.include_router(jobs.router)
app.include_router(ingest.router)
app.include_router(results.router)


# The LLM probe hits a third-party API, so its result is cached briefly — /health is
# polled by load balancers and this must not turn into a per-request upstream call.
_LLM_HEALTH_TTL_SECONDS = 30
_llm_health_cache: tuple[float, str] | None = None


def _check_llm() -> str:
    """Returns 'ok' or an 'error: ...' string. Never raises."""
    global _llm_health_cache
    now = time.monotonic()
    if _llm_health_cache and now - _llm_health_cache[0] < _LLM_HEALTH_TTL_SECONDS:
        return _llm_health_cache[1]

    try:
        from app.llm.factory import get_provider

        get_provider().health_check()
        result = "ok"
    except Exception as exc:
        result = f"error: {exc}"[:200]

    _llm_health_cache = (now, result)
    return result


@app.get("/health")
async def health():
    checks: dict[str, str] = {}

    try:
        async with db.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["db"] = "ok"
    except Exception as exc:
        checks["db"] = f"error: {exc}"[:200]

    try:
        import redis as redis_lib

        r = redis_lib.from_url(settings.effective_redis_url, socket_connect_timeout=2)
        r.ping()
        checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = f"error: {exc}"[:200]

    checks["llm"] = await run_in_threadpool(_check_llm)

    healthy = all(v == "ok" for v in checks.values())
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={"status": "ok" if healthy else "degraded", "checks": checks},
    )
