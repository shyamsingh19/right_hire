from __future__ import annotations

import os

import reflex as rx

# Reflex runs its OWN backend (state/websocket server, default :8000) that is entirely
# separate from the FastAPI ATS API in app/main.py (:8001, configured via CORS_ORIGINS
# in .env). A websocket 403 in the browser almost always means one of these two Reflex
# settings, not the ATS API's CORS_ORIGINS:
#
#   api_url             — the browser connects its websocket here. The default
#                          (http://localhost:8000) only works when the UI is opened
#                          from the same machine it's served from. Accessing it via a
#                          LAN IP, a different host, or through a reverse proxy/tunnel
#                          needs this set to that publicly-reachable address.
#   cors_allowed_origins — origins the Reflex backend accepts websocket connections
#                          from. Defaults to allow-all; only needs setting if an
#                          operator has locked it down and the frontend's origin isn't
#                          on the list.
#
# Both are read from env vars so one deploy config can set them consistently instead of
# guessing which of the two apps a "CORS" env var was meant for.
_api_url = os.getenv("REFLEX_API_URL")
_cors_env = os.getenv("REFLEX_CORS_ORIGINS", "*")
_cors_allowed_origins = (
    ["*"] if _cors_env.strip() == "*" else [o.strip() for o in _cors_env.split(",") if o.strip()]
)

# Ports are pinned with env overrides rather than left to Reflex's defaults. Reflex
# silently increments past a busy port (:8000 -> :8002 ...), which makes the websocket
# URL differ between runs and between machines; a fresh clone should be deterministic.
# Kept env-driven, not hardcoded, because Render/Railway inject the port at runtime
# (see render.yaml's --backend-port $PORT).
_frontend_port = int(os.getenv("REFLEX_FRONTEND_PORT", "3000"))
_backend_port = int(os.getenv("REFLEX_BACKEND_PORT", "8000"))

config = rx.Config(
    app_name="right_hire_ui",
    **({"api_url": _api_url} if _api_url else {}),
    frontend_port=_frontend_port,
    backend_port=_backend_port,
    cors_allowed_origins=_cors_allowed_origins,
    show_built_with_reflex=False,
)
