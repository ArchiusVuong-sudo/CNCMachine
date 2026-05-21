"""FastAPI application factory.

:func:`create_app` wires routers and CORS based on the resolved
settings. Routes themselves live in :mod:`server.api.routes`. Keeping
the factory out of ``main.py`` makes it trivial to spin up the app
inside tests without ever binding a TCP socket.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..core.logging import configure_logging
from ..core.settings import get_settings
from .routes import analyses, analyze, catalog, feedback, generate_gcode, health, models

logger = logging.getLogger("cncserver.api.app")


def create_app() -> FastAPI:
    """Build a configured FastAPI instance ready for uvicorn."""
    configure_logging()
    settings = get_settings()

    app = FastAPI(
        title=settings.server.title,
        version=settings.server.version,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.server.cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(analyze.router)
    app.include_router(analyses.router)
    app.include_router(catalog.router)
    app.include_router(feedback.router)
    app.include_router(generate_gcode.router)
    app.include_router(health.router)
    app.include_router(models.router)

    @app.on_event("startup")
    async def _log_startup() -> None:  # pragma: no cover
        logger.info(
            "FastAPI startup — %s v%s on %s:%d",
            settings.server.title, settings.server.version,
            settings.server.host, settings.server.port,
        )

    return app
