"""POST /v1/feedback — capture operator feedback for KB curation.

Per the locked decision **"Never auto-write; expose a /v1/feedback
endpoint"**, this is the ONLY ingress for KB-bound writes. The route
itself only persists the payload to ``KNOWLEDGE_BASE/_research/feedback/``
— a human reviewer later harvests useful feedback into real
``parts/*.md`` or ``patterns/*.md`` entries.

Why we don't auto-promote:
  * The agent's session notes are noisy; not every measured cycle time
    or analogue ranking deserves to live in the KB.
  * Promoting feedback automatically would let a single misclick poison
    every future analysis (the KB is a small, dense corpus — high
    signal-to-noise matters).

Payload shape is intentionally loose so the UI can evolve without server
changes. The handler validates ``analysis_id`` against a strict regex and
caps the body to 64 KB.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from ...engines.agentic.writeback import write_feedback

logger = logging.getLogger("cncserver.api.feedback")

router = APIRouter(prefix="/v1", tags=["feedback"])

# 64 KB cap — keeps a chatty UI from filling the disk.
_MAX_PAYLOAD_BYTES = 64 * 1024


class FeedbackRequest(BaseModel):
    """Incoming feedback payload.

    The ``payload`` field is intentionally loose (``dict``) so the UI can
    evolve without coupling to the server schema; the handler enforces
    a byte cap and writes the dict through verbatim.
    """

    model_config = ConfigDict(extra="allow")

    analysis_id: str = Field(
        ...,
        description="Analysis UUID this feedback applies to. Must match [A-Za-z0-9_.-]{1,128}.",
    )
    user_id: str | None = Field(None, description="Auth user id (for audit trail).")
    kind: str | None = Field(
        None,
        description=(
            "Feedback kind hint: 'machine_pick' | 'tool_pick' | 'cycle_time_correction' | "
            "'analogue_suggestion' | 'general'. Free-form."
        ),
    )
    payload: dict = Field(
        default_factory=dict,
        description="Operator-supplied feedback content. UI-defined shape.",
    )


class FeedbackResponse(BaseModel):
    ok: bool
    analysis_id: str
    persisted_to: str


@router.post("/feedback", response_model=FeedbackResponse)
async def submit_feedback(req: FeedbackRequest) -> FeedbackResponse:
    """Persist operator feedback for later human-curated KB promotion."""
    try:
        encoded_size = len(req.model_dump_json().encode("utf-8"))
    except Exception:  # noqa: BLE001 — pydantic should always serialize
        encoded_size = 0
    if encoded_size > _MAX_PAYLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"feedback payload too large ({encoded_size}B > {_MAX_PAYLOAD_BYTES}B)",
        )

    record = {
        "user_id": req.user_id,
        "kind": req.kind,
        "payload": req.payload,
    }
    ok = write_feedback(req.analysis_id, record)
    if not ok:
        raise HTTPException(
            status_code=400,
            detail="feedback rejected — invalid analysis_id or filesystem error",
        )

    logger.info(
        "feedback: analysis_id=%s kind=%s user=%s bytes=%d",
        req.analysis_id, req.kind or "-", req.user_id or "-", encoded_size,
    )
    return FeedbackResponse(
        ok=True,
        analysis_id=req.analysis_id,
        persisted_to=f"KNOWLEDGE_BASE/_research/feedback/{req.analysis_id}.json",
    )
