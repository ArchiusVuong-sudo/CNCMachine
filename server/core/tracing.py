"""In-process pipeline tracing — logs every step to stdout via the
standard logger so the operator can watch the pipeline live without
opening any external file.

The public surface (:func:`start_trace`, :func:`record_step`,
:func:`finalize_trace`) is preserved so the orchestrator and any engine
that calls into it does not need to change. The functions return a
plain in-memory dict that callers can keep poking at if they want, but
nothing is ever written to disk — every recorded step is emitted as a
single multi-line log record under ``cncserver.pipeline.trace`` at INFO
level. Tracing is diagnostic-only: nothing here ever raises.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

logger = logging.getLogger("cncserver.pipeline.trace")

# Cap the JSON dump per step so a 50-page drawing extraction doesn't
# swamp the console. Anything over the cap is replaced with a short
# placeholder; the size figure tells you what got dropped.
_MAX_STEP_CHARS = 8000


def _sanitize(obj: Any, _depth: int = 0) -> Any:
    if _depth > 12:
        return f"<max-depth object {type(obj).__name__}>"
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if hasattr(obj, "value") and type(obj).__mro__[1].__name__ == "Enum":
        return obj.value
    if hasattr(obj, "model_dump"):
        try:
            return _sanitize(obj.model_dump(), _depth + 1)
        except Exception:
            pass
    if hasattr(obj, "dict") and callable(getattr(obj, "dict", None)):
        try:
            return _sanitize(obj.dict(), _depth + 1)
        except Exception:
            pass
    if isinstance(obj, dict):
        return {str(k): _sanitize(v, _depth + 1) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [_sanitize(v, _depth + 1) for v in obj]
    if isinstance(obj, (bytes, bytearray)):
        return f"<{len(obj)} bytes>"
    return repr(obj)


def _dump(payload: Any) -> str:
    """JSON-stringify with sane formatting and the size cap applied."""
    try:
        text = json.dumps(payload, indent=2, default=str, ensure_ascii=False)
    except Exception as exc:  # pragma: no cover
        return f"<serialize failed: {exc}>"
    if len(text) > _MAX_STEP_CHARS:
        return text[:_MAX_STEP_CHARS] + f"\n... <truncated {len(text) - _MAX_STEP_CHARS} chars>"
    return text


def start_trace(
    analysis_id: str,
    *,
    file_name: str = "",
    user_id: str | None = None,
    batch_size: int = 1,
    extra: dict | None = None,
) -> dict:
    """Begin a trace for one analysis run.

    Emits a banner log line and returns an in-memory dict that subsequent
    :func:`record_step` calls accumulate into. Nothing is written to disk.
    """
    trace: dict = {
        "analysis_id":    analysis_id,
        "file_name":      file_name,
        "user_id":        user_id or "",
        "batch_size":     batch_size,
        "started_at":     time.time(),
        "started_at_iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        "steps":          [],
    }
    if extra:
        trace.update(_sanitize(extra))
    logger.info(
        "── PIPELINE START ── analysis_id=%s file=%s user=%s batch=%d",
        analysis_id, file_name or "-", user_id or "-", batch_size,
    )
    return trace


def record_step(trace: dict, step_name: str, data: Any) -> None:
    """Record one pipeline step. Dumps the payload to the logger in
    pretty-printed JSON so the operator can read each engine's output
    inline during the run.
    """
    if not isinstance(trace, dict):
        return
    safe = _sanitize(data)
    trace.setdefault("steps", []).append({
        "step":        step_name,
        "recorded_at": time.time(),
        "data":        safe,
    })
    logger.info(
        "── STEP %s ── analysis_id=%s\n%s",
        step_name, trace.get("analysis_id", "?"), _dump(safe),
    )


def finalize_trace(
    trace: dict,
    *,
    total_minutes: float | None = None,
    total_usd: float | None = None,
    elapsed_seconds: float | None = None,
    status: str = "ok",
    error: str | None = None,
) -> None:
    """Close a trace — logs a one-line summary. Returns ``None``."""
    if not isinstance(trace, dict):
        return None
    trace["status"]          = status
    trace["error"]           = error or ""
    trace["finished_at"]     = time.time()
    trace["finished_at_iso"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
    if total_minutes is not None:
        trace["total_minutes"] = round(float(total_minutes), 3)
    if total_usd is not None:
        trace["total_usd"] = round(float(total_usd), 2)
    if elapsed_seconds is not None:
        trace["elapsed_seconds"] = round(float(elapsed_seconds), 2)
    logger.info(
        "── PIPELINE END ── analysis_id=%s status=%s elapsed=%.2fs minutes=%s usd=%s%s",
        trace.get("analysis_id", "?"),
        status,
        elapsed_seconds or 0.0,
        trace.get("total_minutes", "-"),
        trace.get("total_usd", "-"),
        f" error={error}" if error else "",
    )
    return None
