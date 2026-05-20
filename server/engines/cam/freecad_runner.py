"""Async subprocess wrapper around :mod:`.freecad_script`.

Cloned from :mod:`server.engines.extraction_3d.welding`. The contract:

  * Inputs — STEP bytes + a job spec dict (the parent builds it from the
    :class:`ProcessPlan`) + an output directory path.
  * Output — a structured ``CAMSubprocessResult`` dict so the engine can
    aggregate / report per-component. **Never raises** — every failure
    (FreeCAD missing, subprocess timeout, JSON parse error, …) collapses
    to ``{"ok": False, "outputs": [], "error": "…"}``.

Why a subprocess: FreeCAD's bundled OCC + Qt are ABI-incompatible with
the parent's cadquery-ocp wheel. Same reason Engine 2 splits OCC and
welding into separate child processes.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from typing import Any

from ...core.settings import get_settings
from .freecad_script import FREECAD_SCRIPT

logger = logging.getLogger("cncserver.engines.cam.freecad_runner")


def _freecad_python() -> str | None:
    """Resolve the FreeCAD-aware interpreter, or None when unavailable.

    Order of resolution:
      1. ``FREECAD_PYTHON`` env var (set in .env on pod or local dev).
      2. The pod's default conda env at ``/workspace/miniconda3/envs/freecad``.

    Returns None when neither is reachable — the caller short-circuits to
    an "unavailable" CAM result instead of spawning a generic Python that
    can't ``import FreeCAD`` (which on Windows just produces noise).
    """
    env_var = os.environ.get("FREECAD_PYTHON")
    if env_var and os.path.isfile(env_var):
        return env_var
    pod_default = "/workspace/miniconda3/envs/freecad/bin/python3"
    if os.path.isfile(pod_default):
        return pod_default
    return None


async def run_cam_subprocess(
    step_bytes: bytes,
    job_spec: dict[str, Any],
    *,
    out_dir: str,
) -> dict[str, Any]:
    """Spawn FreeCAD, run the CAM script, return its parsed JSON result.

    Parameters
    ----------
    step_bytes : raw STEP bytes for one component (or the whole assembly
        when the plan keeps a single component).
    job_spec : dict containing ``operations`` (list of op-specs), plus
        ``post_processor``, ``analysis_id``, ``component_name``. See
        :mod:`.engine` for the canonical builder.
    out_dir : absolute directory path the script will write ``.nc`` files
        into. Created if it doesn't exist.

    Returns
    -------
    ``{"ok": bool, "outputs": [...], "error"?: str, "per_op_errors"?: [...]}``
    """
    timeout = get_settings().process_mapping.gcode_timeout_sec
    python_exe = _freecad_python()

    op_count = len(job_spec.get("operations") or [])
    if python_exe is None:
        logger.info(
            "run_cam_subprocess: FREECAD_PYTHON not configured; "
            "skipping CAM (ops=%d, component=%s)",
            op_count, job_spec.get("component_name") or "-",
        )
        return {
            "ok": False, "outputs": [],
            "error": "FreeCAD not configured for this environment "
                     "(set FREECAD_PYTHON to a Python with FreeCAD installed)",
        }

    logger.info(
        "run_cam_subprocess: ops=%d component=%s post=%s timeout=%ds python=%s",
        op_count,
        job_spec.get("component_name") or "-",
        job_spec.get("post_processor") or "linuxcnc",
        timeout, python_exe,
    )

    with tempfile.TemporaryDirectory(prefix="cam_freecad_") as tmpdir:
        step_file   = os.path.join(tmpdir, "part.step")
        script_file = os.path.join(tmpdir, "cam_runner.py")
        spec_file   = os.path.join(tmpdir, "job_spec.json")

        with open(step_file, "wb") as f:
            f.write(step_bytes)
        with open(script_file, "w", encoding="utf-8") as f:
            f.write(FREECAD_SCRIPT)
        with open(spec_file, "w", encoding="utf-8") as f:
            json.dump(job_spec, f, ensure_ascii=False)

        env = dict(os.environ)
        env.pop("DISPLAY", None)

        try:
            proc = await asyncio.create_subprocess_exec(
                python_exe, script_file, step_file, spec_file, out_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            try:
                stdout_b, stderr_b = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout,
                )
            except asyncio.TimeoutError:
                proc.kill()
                logger.warning("run_cam_subprocess: timed out after %ds", timeout)
                return {
                    "ok": False, "outputs": [],
                    "error": f"FreeCAD CAM subprocess timed out after {timeout}s",
                }

            stdout = stdout_b.decode("utf-8", errors="replace").strip()
            stderr = stderr_b.decode("utf-8", errors="replace").strip()
            if stderr:
                for line in stderr.splitlines()[-30:]:
                    logger.info("cam| %s", line[:300])

            if not stdout:
                return {
                    "ok": False, "outputs": [],
                    "error": f"FreeCAD CAM subprocess produced no stdout (rc={proc.returncode})",
                }

            last_line = next(
                (l.strip() for l in reversed(stdout.splitlines()) if l.strip()), ""
            )
            try:
                result = json.loads(last_line)
            except json.JSONDecodeError as exc:
                logger.warning("run_cam_subprocess: JSON parse failed: %s | raw: %s",
                               exc, last_line[:200])
                return {
                    "ok": False, "outputs": [],
                    "error": f"JSON parse error: {exc}",
                }

            if not result.get("ok"):
                logger.warning(
                    "run_cam_subprocess: subprocess error: %s",
                    result.get("error") or "unknown",
                )
            if result.get("per_op_error_count"):
                logger.warning(
                    "run_cam_subprocess: %d op(s) failed (showing up to 3): %s",
                    result["per_op_error_count"],
                    result.get("per_op_errors") or [],
                )
            outputs = result.get("outputs") or []
            logger.info(
                "run_cam_subprocess DONE: ok=%s wrote=%d .nc file(s)",
                result.get("ok"), len(outputs),
            )
            return result

        except FileNotFoundError:
            logger.error("FreeCAD Python not found: %s", python_exe)
            return {
                "ok": False, "outputs": [],
                "error": f"FreeCAD Python executable not found: {python_exe}",
            }
        except Exception as exc:
            logger.exception("run_cam_subprocess unexpected error")
            return {"ok": False, "outputs": [], "error": str(exc)}


__all__ = ["run_cam_subprocess"]
