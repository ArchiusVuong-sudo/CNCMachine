"""POST /v1/generate-gcode — on-demand FreeCAD CAM consumer.

The full pipeline already invokes the CAM engine inline as Phase 3, so
this route is primarily for:

  * Re-running CAM after the operator edits a plan (e.g. picks a
    different tool from the top-3, or overrides feeds/speeds).
  * Running CAM standalone when the upstream extraction was already
    completed in a previous request and only the STEP + plan need to be
    re-processed.

Accepts two body shapes (mirrors :mod:`analyze`):

  * **JSON** — ``{analysis_id, plan, step_url}`` or ``{analysis_id,
    plan, step_b64}``.
  * **multipart/form-data** — fields ``analysis_id`` + ``plan`` (JSON
    text) + ``step`` (file upload).

Response is JSON with the :class:`CAMOutput` shape from
:mod:`server.engines.cam.engine`. The endpoint never streams (G-code
generation is fast enough that SSE would be overkill).
"""
from __future__ import annotations

import base64
import json
import logging
import uuid

from fastapi import APIRouter, File, Form, HTTPException, Request
from starlette.datastructures import UploadFile

from ...core.http import download_bytes
from ...engines.cam import run as engine_generate_gcode

logger = logging.getLogger("cncserver.api.generate_gcode")

router = APIRouter(prefix="/v1", tags=["cam"])


# Same byte cap the analyze pipeline tolerates: STEP files up to ~64MB.
_MAX_STEP_BYTES = 64 * 1024 * 1024


def _decode_b64(blob: str) -> bytes:
    try:
        return base64.b64decode(blob, validate=True)
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail=f"step_b64 decode failed: {exc}",
        ) from exc


def _parse_plan_field(raw: object) -> dict:
    """The plan arrives as a JSON dict (already decoded by FastAPI) or as a
    JSON string in the multipart form. Coerce both to a dict.
    """
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, (str, bytes)):
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=400, detail=f"plan JSON parse error: {exc}",
            ) from exc
        if not isinstance(obj, dict):
            raise HTTPException(status_code=400, detail="plan must be a JSON object")
        return obj
    raise HTTPException(status_code=400, detail="plan must be a JSON object")


@router.post("/generate-gcode")
async def generate_gcode(request: Request) -> dict:
    """Run the CAM engine and return the list of generated ``.nc`` files."""
    content_type = (request.headers.get("content-type") or "").lower()

    analysis_id: str
    plan: dict
    step_bytes: bytes

    if "multipart/form-data" in content_type:
        form = await request.form()
        analysis_id = str(form.get("analysis_id") or uuid.uuid4())
        plan = _parse_plan_field(form.get("plan"))
        step_field = form.get("step")
        if not isinstance(step_field, UploadFile):
            raise HTTPException(status_code=400, detail="multipart 'step' file missing")
        step_bytes = await step_field.read()
    else:
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="body must be a JSON object")
        analysis_id = str(body.get("analysis_id") or uuid.uuid4())
        plan = _parse_plan_field(body.get("plan"))

        step_url = body.get("step_url")
        step_b64 = body.get("step_b64")
        if step_b64:
            step_bytes = _decode_b64(step_b64)
        elif step_url:
            step_bytes = await download_bytes(str(step_url))
        else:
            raise HTTPException(
                status_code=400,
                detail="provide one of: step_url, step_b64 (or multipart 'step')",
            )

    if not step_bytes:
        raise HTTPException(status_code=400, detail="step bytes resolved empty")
    if len(step_bytes) > _MAX_STEP_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"step too large ({len(step_bytes)}B > {_MAX_STEP_BYTES}B)",
        )

    logger.info(
        "POST /v1/generate-gcode — analysis_id=%s components=%d step=%dKB",
        analysis_id,
        len(plan.get("components") or []),
        len(step_bytes) // 1024,
    )

    cam_output = await engine_generate_gcode(
        step_bytes, plan, analysis_id=analysis_id,
    )
    return cam_output.as_dict()
