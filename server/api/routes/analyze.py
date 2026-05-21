"""POST /v1/analyze-stream — SSE analysis pipeline.

Two body shapes are accepted:

  1. **JSON body** with ``step_url`` + ``drawing_url`` pointing at
     Supabase-hosted (or any HTTPS-reachable) files.
  2. **multipart/form-data** with raw ``step`` + ``drawing`` upload
     fields, useful for local dev and the desktop client.

In both cases the response is ``text/event-stream`` carrying the
orchestrator's events, terminated by a single ``done`` frame.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, File, Form, Request
from fastapi.responses import StreamingResponse
from starlette.datastructures import UploadFile

from ...core.schemas import AnalyzeRequest
from ...infra.supabase import get_supabase_client
from ...pipeline import run_pipeline
from ..sse import stream_to_sse

logger = logging.getLogger("cncserver.api.analyze")

router = APIRouter(prefix="/v1", tags=["analyze"])


@router.post("/analyze-stream")
async def analyze_stream(request: Request) -> StreamingResponse:
    """Run the 3-engine pipeline and stream events to the caller.

    Content negotiation is content-type driven:

      * ``application/json``        → :class:`AnalyzeRequest` body
      * ``multipart/form-data``     → form fields + uploaded files

    Engine selection precedence (first non-empty wins):

      1. ``?engine=agentic|rag``    — query parameter (works for both bodies)
      2. ``engine`` field in JSON body / form field of the same name
      3. Server default from ``ENGINE_MODE`` (see settings)

    Unknown engine names surface inside the SSE stream as an ``error``
    frame followed by ``done`` — the orchestrator owns that validation
    so the HTTP layer can stay dumb.

    Returns a ``text/event-stream`` response. The pipeline never raises
    out of the generator — fatal errors are emitted as ``error`` events
    followed by a ``done`` event.
    """
    content_type = (request.headers.get("content-type") or "").lower()

    analysis_id:  str
    step_url:     str | None = None
    drawing_url:  str | None = None
    step_bytes:   bytes | None = None
    drawing_bytes: bytes | None = None
    file_name:    str = ""
    user_id:      str | None = None
    batch_size:   int = 1
    forced_part_type: str | None = None
    engine: str | None = None
    model:  str | None = None

    if "multipart/form-data" in content_type:
        form = await request.form()
        analysis_id = str(form.get("analysis_id") or uuid.uuid4())
        user_id     = (form.get("user_id") or None) or None
        batch_size  = int(form.get("batch_size") or 1)
        forced_part_type = (form.get("forced_assembly_part_type") or None) or None
        file_name   = str(form.get("file_name") or "")
        engine      = (form.get("engine") or None) or None
        model       = (form.get("model") or None) or None
        step_field    = form.get("step")
        drawing_field = form.get("drawing")
        if isinstance(step_field, UploadFile):
            step_bytes = await step_field.read()
            file_name  = file_name or step_field.filename or ""
        if isinstance(drawing_field, UploadFile):
            drawing_bytes = await drawing_field.read()
    else:
        body = await request.json()
        req = AnalyzeRequest(**body)
        analysis_id      = req.analysis_id or str(uuid.uuid4())
        step_url         = req.step_url
        drawing_url      = req.drawing_url
        file_name        = req.step_name or ""
        user_id          = req.user_id
        batch_size       = req.batch_size or 1
        forced_part_type = req.forced_assembly_part_type
        engine           = req.engine
        model            = req.model

    # Query-string overrides beat both body and form. Lets the FE switch
    # engines / models without touching the existing JSON payload shape.
    engine_qs = request.query_params.get("engine")
    if engine_qs:
        engine = engine_qs
    model_qs = request.query_params.get("model")
    if model_qs:
        model = model_qs

    supabase_client: Any = get_supabase_client()

    logger.info(
        "POST /v1/analyze-stream — analysis_id=%s file=%s batch=%d user=%s "
        "engine=%s model=%s step=%s drawing=%s",
        analysis_id, file_name, batch_size, user_id or "-",
        engine or "default", model or "default",
        "bytes" if step_bytes else (step_url or "-"),
        "bytes" if drawing_bytes else (drawing_url or "-"),
    )

    events = run_pipeline(
        analysis_id=analysis_id,
        drawing_url=drawing_url,
        step_url=step_url,
        drawing_bytes=drawing_bytes,
        step_bytes=step_bytes,
        file_name=file_name,
        user_id=user_id,
        batch_size=batch_size,
        supabase_client=supabase_client,
        forced_assembly_part_type=forced_part_type,
        engine=engine,
        model=model,
    )

    return StreamingResponse(
        stream_to_sse(events),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering
            "Connection": "keep-alive",
        },
    )
