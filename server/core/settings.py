"""Centralised settings, resolved from environment variables.

Each setting has a sensible default so the server still starts in a bare
dev environment (no Supabase, no FreeCAD, no remote VLM).  Engines call
`get_settings()` at runtime; we re-resolve at every call so tests can
mutate `os.environ` between cases.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


def _bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


_REPO_ROOT = Path(__file__).resolve().parent.parent   # .../server


@dataclass(frozen=True)
class ServerSettings:
    """Top-level server settings."""

    host: str = "0.0.0.0"
    port: int = 8001
    title: str = "CNC Analysis API"
    version: str = "1.0.0"
    cors_origins: tuple[str, ...] = ("*",)


@dataclass(frozen=True)
class LLMSettings:
    """Connection config for the vision/text LLM.

    The pipeline now talks to two distinct LLM backends:

      * **vLLM (Qwen3-VL)** — Engine 1 vision extraction. Always used.
      * **OpenRouter** — Engine 3 agentic planner (default). Selected per
        request through ``AnalyzeRequest.model`` or the server default
        ``openrouter_default_model``.

    The ``vllm:`` model prefix (or omitting ``model`` entirely) keeps a
    request on vLLM. Any other slug (e.g. ``anthropic/claude-sonnet-4.5``)
    routes to OpenRouter.
    """

    # ── vLLM (Qwen3-VL) ────────────────────────────────────────────────
    base_url: str = "http://localhost:11434"
    model: str = "Qwen/Qwen3-VL-32B-Instruct-FP8"
    vlm_inactivity_seconds: float = 30.0
    vlm_thinking_budget_tokens: int = 6000
    vlm_max_tokens: int = 12288
    text_max_tokens: int = 6144
    text_thinking_budget_tokens: int = 1024

    # ── OpenRouter ─────────────────────────────────────────────────────
    openrouter_api_key: str | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_default_model: str = "anthropic/claude-sonnet-4.5"
    openrouter_http_referer: str = "https://cncmachining.local"
    openrouter_app_title: str = "CNC Quote Engine"
    openrouter_inactivity_seconds: float = 90.0
    openrouter_request_timeout: float = 300.0
    openrouter_default_reasoning_effort: str = "medium"
    openrouter_max_tokens: int = 8192
    openrouter_allowed_models: tuple[str, ...] = (
        "anthropic/claude-sonnet-4.5",
        "anthropic/claude-opus-4.5",
        "openai/gpt-5",
        "openai/gpt-5-mini",
        "google/gemini-2.5-pro",
        "google/gemini-2.5-flash",
        "deepseek/deepseek-v3.2",
        "qwen/qwen3-max",
    )


@dataclass(frozen=True)
class ExtractionSettings:
    """2D drawing extraction tuning knobs."""

    pdf_long_side_px: int = 2000
    pdf_target_dpi: int = 150
    pdf_max_pages: int = 0           # 0 = process every page
    per_page_retries: int = 1
    vlm_phase_deadline_sec: float = 600.0


@dataclass(frozen=True)
class GeometrySettings:
    """3D extraction subprocess + OCC config."""

    occ_python: str = sys.executable
    stepanalyzer_timeout_sec: int = 240
    welding_subprocess_timeout_sec: int = 120

    # Feature classification thresholds (mm)
    max_fillet_radius_mm: float = 8.0
    min_hole_depth_mm: float = 1.0
    min_pocket_depth_mm: float = 0.5
    min_pocket_area_mm2: float = 5.0
    chamfer_angle_deg: float = 45.0
    chamfer_angle_tol_deg: float = 10.0
    coplanar_tol_mm: float = 0.05
    caxis_tol_mm: float = 0.2
    radius_group_tol_mm: float = 0.05


@dataclass(frozen=True)
class ProcessMappingSettings:
    """Process-planning engine tuning knobs."""

    default_post_processor: str = "linuxcnc"
    gcode_timeout_sec: int = 60
    blended_rate_usd_per_hr: float = 75.0
    default_batch_size: int = 1


@dataclass(frozen=True)
class AgenticSettings:
    """Agentic-engine tuning knobs.

    The single-loop agent replaces the old Phase A→B→C→D chain, so the
    iteration cap now governs the whole plan. Bump it via env
    ``AGENTIC_MAX_ITER_PER_PHASE`` if the agent needs more room to reach
    a clean ``final``.
    """

    max_iterations_per_phase: int = 40
    max_parse_retries: int = 3
    max_tool_result_chars: int = 16_000
    temp_note_ttl_days: int = 15


@dataclass(frozen=True)
class RagSettings:
    """RAG-engine config: embeddings + retrieval tuning.

    The RAG engine is a swap-in alternative to the agentic engine — one
    LLM call per component, grounded by analogue parts retrieved from
    pgvector. Set ``ENGINE_MODE=rag`` (see :class:`EngineSettings`) to
    make it the default, or pass ``?engine=rag`` per request.
    """

    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    openai_embedding_model: str = "text-embedding-3-small"
    rag_top_k: int = 5
    rag_top_k_patterns: int = 3


@dataclass(frozen=True)
class EngineSettings:
    """Engine-3 selection. Picks which planner backend runs per analysis.

    Per-request override: clients may set ``?engine=agentic|rag`` or pass
    ``engine`` in the JSON body. When absent, ``default`` applies.
    """

    default: str = "agentic"


@dataclass(frozen=True)
class Settings:
    server: ServerSettings
    llm: LLMSettings
    extraction: ExtractionSettings
    geometry: GeometrySettings
    process_mapping: ProcessMappingSettings
    agentic: AgenticSettings
    rag: RagSettings
    engine: EngineSettings
    repo_root: Path = _REPO_ROOT


_DEFAULT_OPENROUTER_ALLOWED = (
    "anthropic/claude-sonnet-4.5",
    "anthropic/claude-opus-4.5",
    "openai/gpt-5",
    "openai/gpt-5-mini",
    "google/gemini-2.5-pro",
    "google/gemini-2.5-flash",
    "deepseek/deepseek-v3.2",
    "qwen/qwen3-max",
)


def _csv_tuple(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    """Parse a comma-separated env var into a stripped, non-empty tuple."""
    raw = os.environ.get(name)
    if not raw:
        return default
    items = tuple(s.strip() for s in raw.split(",") if s.strip())
    return items or default


def _llm_settings() -> LLMSettings:
    return LLMSettings(
        base_url=(
            os.environ.get("VISION_MODEL_URL")
            or os.environ.get("LOCAL_OLLAMA_URL")
            or "http://localhost:11434"
        ).rstrip("/"),
        model=(
            os.environ.get("VISION_MODEL_NAME")
            or os.environ.get("VISION_MODEL")
            or "Qwen/Qwen3-VL-32B-Instruct-FP8"
        ),
        vlm_inactivity_seconds=float(os.environ.get("VLM_INACTIVITY_SECONDS", "30")),
        vlm_thinking_budget_tokens=_int("VLM_THINKING_BUDGET_TOKENS", 6000),
        vlm_max_tokens=_int("VLM_MAX_TOKENS", 12288),
        text_max_tokens=_int("TEXT_LLM_MAX_TOKENS", 6144),
        text_thinking_budget_tokens=_int("TEXT_LLM_THINKING_BUDGET", 1024),
        openrouter_api_key=os.environ.get("OPENROUTER_API_KEY") or None,
        openrouter_base_url=(
            os.environ.get("OPENROUTER_BASE_URL") or "https://openrouter.ai/api/v1"
        ).rstrip("/"),
        openrouter_default_model=(
            os.environ.get("OPENROUTER_DEFAULT_MODEL") or "anthropic/claude-sonnet-4.5"
        ),
        openrouter_http_referer=(
            os.environ.get("OPENROUTER_HTTP_REFERER") or "https://cncmachining.local"
        ),
        openrouter_app_title=(
            os.environ.get("OPENROUTER_APP_TITLE") or "CNC Quote Engine"
        ),
        openrouter_inactivity_seconds=float(
            os.environ.get("OPENROUTER_INACTIVITY_SECONDS", "90")
        ),
        openrouter_request_timeout=float(
            os.environ.get("OPENROUTER_REQUEST_TIMEOUT", "300")
        ),
        openrouter_default_reasoning_effort=(
            os.environ.get("OPENROUTER_DEFAULT_REASONING_EFFORT") or "medium"
        ),
        openrouter_max_tokens=_int("OPENROUTER_MAX_TOKENS", 8192),
        openrouter_allowed_models=_csv_tuple(
            "OPENROUTER_ALLOWED_MODELS", _DEFAULT_OPENROUTER_ALLOWED,
        ),
    )


def load_settings() -> Settings:
    """Build a Settings snapshot from the current environment."""
    return Settings(
        server=ServerSettings(
            host=os.environ.get("HOST", "0.0.0.0"),
            port=_int("PORT", 8001),
            title=os.environ.get("SERVER_TITLE", "CNC Analysis API"),
            version=os.environ.get("SERVER_VERSION", "1.0.0"),
            cors_origins=tuple(
                (os.environ.get("CORS_ORIGINS") or "*").split(",")
            ),
        ),
        llm=_llm_settings(),
        extraction=ExtractionSettings(
            pdf_long_side_px=_int("PDF_LONG_SIDE_PX", 2000),
            pdf_target_dpi=_int("PDF_TARGET_DPI", 150),
            pdf_max_pages=_int("PDF_MAX_PAGES_FOR_VISION", 0),
            per_page_retries=_int("VLM_PAGE_RETRIES", 1),
            vlm_phase_deadline_sec=float(os.environ.get("VLM_PHASE_DEADLINE_SEC", "600")),
        ),
        geometry=GeometrySettings(
            occ_python=os.environ.get("OCC_PYTHON") or sys.executable,
            stepanalyzer_timeout_sec=_int("STEPANALYZER_TIMEOUT_SEC", 240),
            welding_subprocess_timeout_sec=_int("WELDING_TIMEOUT_SEC", 120),
        ),
        process_mapping=ProcessMappingSettings(
            default_post_processor=os.environ.get("DEFAULT_POST_PROCESSOR", "linuxcnc"),
            gcode_timeout_sec=_int("GCODE_TIMEOUT_SEC", 60),
            blended_rate_usd_per_hr=float(os.environ.get("BLENDED_RATE_USD_PER_HR", "75")),
            default_batch_size=_int("DEFAULT_BATCH_SIZE", 1),
        ),
        agentic=AgenticSettings(
            max_iterations_per_phase=_int("AGENTIC_MAX_ITER_PER_PHASE", 40),
            max_parse_retries=_int("AGENTIC_MAX_PARSE_RETRIES", 3),
            max_tool_result_chars=_int("AGENTIC_MAX_TOOL_RESULT_CHARS", 16_000),
            temp_note_ttl_days=_int("AGENTIC_TEMP_TTL_DAYS", 15),
        ),
        rag=RagSettings(
            openai_api_key=os.environ.get("OPENAI_API_KEY") or None,
            openai_base_url=(
                os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1"
            ).rstrip("/"),
            openai_embedding_model=(
                os.environ.get("OPENAI_EMBEDDING_MODEL") or "text-embedding-3-small"
            ),
            rag_top_k=_int("RAG_TOP_K", 5),
            rag_top_k_patterns=_int("RAG_TOP_K_PATTERNS", 3),
        ),
        engine=EngineSettings(
            default=(os.environ.get("ENGINE_MODE") or "agentic").strip().lower(),
        ),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()


def reload_settings() -> Settings:
    """Reset the lru_cache and re-read env. Useful in tests."""
    get_settings.cache_clear()
    return get_settings()
