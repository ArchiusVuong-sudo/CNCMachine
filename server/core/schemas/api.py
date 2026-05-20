"""Request / response models for the public /v1/* API."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .enums import JobStatus


class AnalyzeRequest(BaseModel):
    """POST /v1/analyze-stream request body.

    Either ``step_url`` + ``drawing_url`` (Supabase-hosted) or raw
    multipart uploads (handled outside the JSON body) — the client picks.
    """

    model_config = ConfigDict(extra="allow")

    analysis_id: str = Field(description="Caller-supplied UUID for correlation")
    step_url:    str | None = None
    drawing_url: str | None = None
    step_name:   str | None = None
    drawing_name: str | None = None
    user_id:     str | None = None
    batch_size:  int = 1
    forced_assembly_part_type: str | None = Field(
        None, description="UI override that pins every component to this part type",
    )


class HealthResponse(BaseModel):
    """GET /v1/health response."""

    status:    str = "ok"
    version:   str
    services:  dict[str, bool] = Field(
        default_factory=dict,
        description="Best-effort liveness of downstream dependencies",
    )


class JobStatusResponse(BaseModel):
    """Polling response for async analyses (future use)."""

    model_config = ConfigDict(extra="allow")

    job_id:   str
    status:   JobStatus
    progress: str | None = None
    error:    str | None = None
