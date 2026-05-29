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

    The pipeline talks to two vLLM backends:

      * **vLLM (Qwen3-VL)** — Engine 1 vision extraction. Always used, and
        the fallback text backend for Engine 3.
      * **Agent vLLM (Kimi-Linear)** — Engine 3 agentic planner. Selected
        per request through ``AnalyzeRequest.model`` (the ``agent:`` prefix)
        or made the default automatically when ``AGENT_LLM_URL`` is set.

    The ``vllm:`` model prefix (or omitting ``model`` entirely) keeps a
    request on the Qwen vLLM backend; the ``agent:`` prefix routes to the
    Kimi pod.
    """

    # ── vLLM (Qwen3-VL) ────────────────────────────────────────────────
    # When ``base_url`` is a hosted OpenAI-compatible provider (Gemini's
    # ``v1beta/openai``, OpenAI proper, OpenRouter, etc.), ``vision_api_key``
    # holds the Bearer token. Set ``VISION_MODEL_API_KEY`` in the env to use
    # a hosted backend as a stand-in for the local Qwen3-VL vLLM — handy
    # while the GPU pod is unavailable.
    base_url: str = "http://localhost:11434"
    model: str = "Qwen/Qwen3-VL-32B-Instruct-FP8"
    vision_api_key: str | None = None
    vlm_inactivity_seconds: float = 30.0
    vlm_thinking_budget_tokens: int = 6000
    vlm_max_tokens: int = 12288
    text_max_tokens: int = 6144
    text_thinking_budget_tokens: int = 1024

    # ── Agent vLLM (Kimi-Linear — Engine 3 planner) ────────────────────
    # A second OpenAI-compatible vLLM endpoint dedicated to the agentic
    # planner. When ``agent_base_url`` is set, the ``agent:`` model prefix
    # routes here (and ``agent_default_model`` makes it the Engine-3
    # default). This backend gets PLAIN JSON-by-instruction: the provider
    # sends no ``response_format`` (Kimi's slow tokenizer has no vLLM
    # grammar backend — guided JSON crashes the engine) and no Qwen
    # ``chat_template_kwargs``.
    agent_base_url: str | None = None
    agent_model: str = "kimi-agent"
    agent_api_key: str | None = None
    agent_default_model: str | None = None
    agent_inactivity_seconds: float = 120.0
    # Kimi-VL-A3B-Thinking-2506 spends most of its budget on the inline
    # ◁think▷…◁/think▷ reasoning block BEFORE the answer JSON; 8192 routinely
    # truncates mid-thought (finish_reason=length, no answer). 16384 leaves
    # room for the reasoning + a clean trailing JSON within the 65536 ctx.
    agent_max_tokens: int = 16384
    agent_failover: str | None = None
    # Kimi sampling. Greedy decoding (temp 0) collapses Kimi models into a
    # degenerate repetition attractor, so we use Moonshot's recommended
    # non-greedy defaults (Kimi-VL generation_config: temp 0.6 / top_p 0.95)
    # instead of the deterministic 0.0 the Qwen vision path uses.
    # Env-overridable for tuning.
    agent_temperature: float = 0.6
    agent_top_p: float = 0.95


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
class EngineSettings:
    """Engine selection. Picks which 2D / 3D / planner backend runs.

    All three are pluggable seams. The defaults are the in-house engines
    (Qwen3-VL for 2D, OCC subprocess for 3D, agentic ReAct loop for the
    planner). External engines plug in by adding a branch to the matching
    ``_resolve_*_engine`` helper in ``pipeline/orchestrator.py`` and
    setting the env var below.
    """

    default:        str = "agentic"   # planner engine (Engine 3)
    extraction_2d:  str = "default"   # drawing-extraction engine (Engine 1)
    extraction_3d:  str = "default"   # 3D feature-recognition engine (Engine 2)


@dataclass(frozen=True)
class Settings:
    server: ServerSettings
    llm: LLMSettings
    extraction: ExtractionSettings
    geometry: GeometrySettings
    process_mapping: ProcessMappingSettings
    agentic: AgenticSettings
    engine: EngineSettings
    repo_root: Path = _REPO_ROOT


def _llm_settings() -> LLMSettings:
    # Agent backend (Kimi-Linear). When the URL is set but no explicit
    # default slug is given, make Kimi the Engine-3 default automatically.
    agent_base_url = (os.environ.get("AGENT_LLM_URL") or "").rstrip("/") or None
    agent_model = os.environ.get("AGENT_LLM_MODEL") or "kimi-agent"
    agent_default_model = os.environ.get("AGENT_DEFAULT_MODEL") or None
    if agent_default_model is None and agent_base_url:
        agent_default_model = f"agent:{agent_model}"

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
        vision_api_key=os.environ.get("VISION_MODEL_API_KEY") or None,
        vlm_inactivity_seconds=float(os.environ.get("VLM_INACTIVITY_SECONDS", "30")),
        vlm_thinking_budget_tokens=_int("VLM_THINKING_BUDGET_TOKENS", 6000),
        vlm_max_tokens=_int("VLM_MAX_TOKENS", 12288),
        text_max_tokens=_int("TEXT_LLM_MAX_TOKENS", 6144),
        text_thinking_budget_tokens=_int("TEXT_LLM_THINKING_BUDGET", 1024),
        agent_base_url=agent_base_url,
        agent_model=agent_model,
        agent_api_key=os.environ.get("AGENT_LLM_API_KEY") or None,
        agent_default_model=agent_default_model,
        agent_inactivity_seconds=float(
            os.environ.get("AGENT_LLM_INACTIVITY_SECONDS", "120")
        ),
        agent_max_tokens=_int("AGENT_LLM_MAX_TOKENS", 16384),
        agent_failover=os.environ.get("AGENT_LLM_FAILOVER") or None,
        agent_temperature=float(os.environ.get("AGENT_LLM_TEMPERATURE", "0.6")),
        agent_top_p=float(os.environ.get("AGENT_LLM_TOP_P", "0.95")),
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
        engine=EngineSettings(
            default=(os.environ.get("ENGINE_MODE") or "agentic").strip().lower(),
            extraction_2d=(os.environ.get("EXTRACTION_2D_ENGINE") or "default").strip().lower(),
            extraction_3d=(os.environ.get("EXTRACTION_3D_ENGINE") or "default").strip().lower(),
        ),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()


def reload_settings() -> Settings:
    """Reset the lru_cache and re-read env. Useful in tests."""
    get_settings.cache_clear()
    return get_settings()
