"""Entry point — ``python -m server.main`` or ``uvicorn server.main:app``.

Resolves the FastAPI app via :func:`server.api.create_app` and (when
invoked as a script) starts uvicorn against the host/port from the
resolved settings.
"""
from __future__ import annotations

import logging
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

from .api import create_app
from .core.settings import get_settings

logger = logging.getLogger("cncserver.main")

app = create_app()


def main() -> None:
    """Run the dev server. Production should run uvicorn directly."""
    import uvicorn

    settings = get_settings()
    logger.info("Starting uvicorn on %s:%d", settings.server.host, settings.server.port)
    uvicorn.run(
        "server.main:app",
        host=settings.server.host,
        port=settings.server.port,
        log_level="info",
        reload=False,
    )


if __name__ == "__main__":
    main()
