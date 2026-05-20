"""GET /v1/health — liveness + best-effort dependency probes."""
from __future__ import annotations

import logging
import os

from fastapi import APIRouter

from ...core.schemas import HealthResponse
from ...core.settings import get_settings
from ...infra.supabase import is_configured as supabase_configured

logger = logging.getLogger("cncserver.api.health")

router = APIRouter(prefix="/v1", tags=["health"])


def _freecad_available() -> bool:
    """True only when FREECAD_PYTHON points at a real executable file.

    The CAM engine + welding subprocess short-circuit on False — so this
    is the single source of truth for "can this server emit G-code?".
    """
    path = os.environ.get("FREECAD_PYTHON")
    return bool(path) and os.path.isfile(path)


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Always-200 liveness probe with dependency status fields."""
    settings = get_settings()
    return HealthResponse(
        status="ok",
        version=settings.server.version,
        services={
            "supabase":     supabase_configured(),
            "occ_python":   bool(settings.geometry.occ_python),
            "freecad":      _freecad_available(),
            "vlm_endpoint": bool(settings.llm.base_url),
        },
    )
