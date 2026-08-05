from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import db
from app.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.auto_create_tables:
        async with db.engine.begin() as conn:
            await conn.run_sync(db.Base.metadata.create_all)
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

from app.api import auth, jobs, ingest, results  # noqa: E402

app.include_router(auth.router)
app.include_router(jobs.router)
app.include_router(ingest.router)
app.include_router(results.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
