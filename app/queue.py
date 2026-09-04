from __future__ import annotations

from rq import Queue

from app.config import settings


def get_ats_queue() -> Queue:
    import redis as redis_lib

    r = redis_lib.from_url(settings.effective_redis_url)
    return Queue("ats", connection=r)
