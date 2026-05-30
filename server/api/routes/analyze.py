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

import asyncio
import json
import logging
import time
import uuid
from typing import Any, AsyncIterator

from fastapi import APIRouter, File, Form, Request
from fastapi.responses import StreamingResponse
from starlette.datastructures import UploadFile

from ...core.schemas import AnalyzeRequest
from ...core.writeback import _NOTES_DIR, _safe_id
from ...infra.supabase import get_supabase_client
from ...pipeline import run_pipeline
from ..sse import stream_to_sse

logger = logging.getLogger("cncserver.api.analyze")

router = APIRouter(prefix="/v1", tags=["analyze"])

# Strong references to in-flight background pipeline tasks. asyncio only keeps
# a WEAK reference to tasks created via create_task(), so a fire-and-forget
# task can be garbage-collected mid-run — silently killing the pipeline and
# losing persistence. Holding the task here until it finishes prevents that.
_BACKGROUND_TASKS: set[asyncio.Task] = set()


@router.post("/analyze-stream")
async def analyze_stream(request: Request) -> StreamingResponse:
    """Run the 3-engine pipeline and stream events to the caller.

    Content negotiation is content-type driven:

      * ``application/json``        → :class:`AnalyzeRequest` body
      * ``multipart/form-data``     → form fields + uploaded files

    Engine selection precedence (first non-empty wins):

      1. ``?engine=agentic``        — query parameter (works for both bodies)
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

    # ── Decouple pipeline from SSE stream ───────────────────────────────────
    # Cloudflare Tunnel (the trycloudflare.com free proxy) silently kills
    # long-running HTTP/2 streams. When the SSE response is cancelled mid-
    # pipeline, the underlying async generator gets a CancelledError on its
    # next `yield`, which aborts the pipeline entirely — losing all the
    # work Engine 1 has already done. To survive that, we tee events into a
    # queue and run the pipeline as an *independent* background Task. The
    # SSE response consumes the queue; if the client disconnects, the queue
    # consumer stops but the background task drains the pipeline to
    # completion. Results still land in Supabase + `_research/notes` so a
    # browser refresh shows the finished run.
    queue: asyncio.Queue[tuple[str, dict] | None] = asyncio.Queue(maxsize=2048)

    async def _drain_to_queue() -> None:
        try:
            async for ev in _capture_and_persist_messages(events, analysis_id):
                try:
                    queue.put_nowait(ev)
                except asyncio.QueueFull:
                    # Slow consumer (or client disconnected). Drop the SSE
                    # tee — but the pipeline continues; persistence still
                    # happens at the tail of `_capture_and_persist_messages`.
                    pass
        except Exception as exc:
            logger.exception(
                "analyze-stream: background pipeline raised for %s: %s",
                analysis_id, exc,
            )
        finally:
            # Guarantee the terminal sentinel reaches the consumer even when
            # the queue is full (slow but live consumer): evict one buffered
            # event to free a slot, then enqueue None. We never block here —
            # blocking would leak this task forever if the consumer is gone.
            while True:
                try:
                    queue.put_nowait(None)
                    break
                except asyncio.QueueFull:
                    try:
                        queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break

    # Keep a strong reference so the task isn't GC'd mid-run, and drop it on
    # completion. Without this, asyncio's weak task reference lets the pipeline
    # vanish at any await point.
    _bg_task = asyncio.create_task(_drain_to_queue())
    _BACKGROUND_TASKS.add(_bg_task)
    _bg_task.add_done_callback(_BACKGROUND_TASKS.discard)

    async def _pump_to_sse() -> AsyncIterator[tuple[str, dict]]:
        """Yield queued events. On client disconnect, the consumer is
        cancelled by FastAPI — we just stop yielding; the background task
        keeps running independently."""
        while True:
            try:
                ev = await queue.get()
            except asyncio.CancelledError:
                logger.info(
                    "analyze-stream: SSE consumer cancelled for %s "
                    "(client likely disconnected) — background pipeline "
                    "continues",
                    analysis_id,
                )
                return
            if ev is None:
                return
            yield ev

    return StreamingResponse(
        stream_to_sse(_pump_to_sse()),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering
            "Connection": "keep-alive",
        },
    )


async def _capture_and_persist_messages(
    gen: AsyncIterator[tuple[str, dict]],
    analysis_id: str,
) -> AsyncIterator[tuple[str, dict]]:
    """Pass orchestrator events through unchanged while collecting them, then
    write the message log into the saved ``<id>_full.json`` so the history
    view's pipeline activity card can replay them.

    Filters out ``heartbeat`` (keep-alive only, not interesting to a saved
    timeline). Best-effort: file errors are logged and swallowed.
    """
    messages: list[dict[str, Any]] = []
    async for ev in gen:
        ev_type = ev[0]
        ev_data = ev[1] if len(ev) > 1 else {}
        if ev_type != "heartbeat":
            messages.append({
                "id":        str(uuid.uuid4()),
                "type":      ev_type,
                "data":      ev_data,
                "timestamp": int(time.time() * 1000),
            })
        yield ev

    safe = _safe_id(analysis_id)
    if not safe or not messages:
        return
    target = _NOTES_DIR / f"{safe}_full.json"
    try:
        existing = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("messages persist: could not read %s — %s", target, exc)
        return
    existing["messages"] = messages
    try:
        target.write_text(
            json.dumps(existing, indent=2, default=str, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError as exc:
        logger.warning("messages persist: write failed for %s — %s", target, exc)
        return
    logger.info("messages persist: %d events saved → %s", len(messages), target)
