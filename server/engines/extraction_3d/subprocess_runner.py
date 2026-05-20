"""Async wrapper around the OCC subprocess.

OCP segfaults on malformed STEP files are common enough that we always
run the recognizer in a child process — a crash there returns a fallback
dict instead of taking the FastAPI server down with it.

The wrapper:
  1. Writes ``step_bytes`` + :data:`RUNNER_SCRIPT` to a tempdir.
  2. Spawns ``settings.geometry.occ_python`` with ``PYTHONPATH`` set to
     the repo root (parent of ``server/``) so the runner can import the
     vendored OCC package.
  3. Streams the child's stderr line-by-line into the parent logger so
     per-component progress is visible during long runs.
  4. Parses the last non-empty stdout line as JSON.

Returns a dict matching the wire shape (``ok``, ``components``, …) that
:func:`engine.run` will lift into :class:`AssemblyData`.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from pathlib import Path

from ...core.settings import get_settings
from .runner_script import RUNNER_SCRIPT

logger = logging.getLogger("cncserver.engines.extraction_3d.subprocess_runner")

# Repo root: .../server/engines/extraction_3d/subprocess_runner.py
#         →  .../server                                       (parent of `engines/`)
#         →  .../                                             (parent of `server/`)
# The runner imports ``server.engines.extraction_3d.occ.*`` so PYTHONPATH must
# point at the directory that *contains* the ``server`` package.
_REPO_ROOT = Path(__file__).resolve().parents[3]


def _fallback_response(error: str) -> dict:
    """Minimal valid response shape when the runner cannot be invoked."""
    return {
        "ok": False,
        "_error": error,
        "request_id": "",
        "assembly_name": "",
        "file_name": "",
        "component_count": 1,
        "unique_component_count": 1,
        "total_volume_mm3": 0.0,
        "pmi_available": False,
        "pmi_annotations": [],
        "manufacturing_processes": [],
        "components": [
            {
                "component_index": 0,
                "name": "part",
                "description": "",
                "instance_count": 1,
                "part_type": "cnc_milling",
                "part_type_confidence": 0.5,
                "volume_mm3": 0.0,
                "surface_area_mm2": 0.0,
                "bbox": {},
                "thickness": {},
                "total_perimeter_mm": 0.0,
                "features": [],
                "pmi_available": False,
                "pmi_annotations": [],
            }
        ],
    }


async def analyze_step_assembly(step_bytes: bytes) -> dict:
    """Run the OCC recognizer subprocess and return its parsed JSON result.

    Always returns a valid dict — a child crash or timeout produces a
    fallback so the orchestrator can still build a usable AssemblyData.
    """
    s = get_settings().geometry
    python_exe = s.occ_python
    timeout    = s.stepanalyzer_timeout_sec

    logger.info(
        "analyze_step_assembly: python=%s timeout=%ds bytes=%d repo_root=%s",
        python_exe, timeout, len(step_bytes), _REPO_ROOT,
    )

    with tempfile.TemporaryDirectory(prefix="extraction_3d_") as tmpdir:
        step_file   = os.path.join(tmpdir, "part.step")
        runner_file = os.path.join(tmpdir, "occ_runner.py")

        with open(step_file, "wb") as f:
            f.write(step_bytes)
        with open(runner_file, "w", encoding="utf-8") as f:
            f.write(RUNNER_SCRIPT)

        env = dict(os.environ)
        existing_pp = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = (
            str(_REPO_ROOT) + (os.pathsep + existing_pp if existing_pp else "")
        )

        try:
            proc = await asyncio.create_subprocess_exec(
                python_exe, runner_file, step_file,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )

            # Stream stderr line-by-line. The child emits structured progress
            # logs there; piping into the parent logger surfaces them in the
            # SSE stream's log tail rather than burying them at process exit.
            async def _drain_stderr() -> str:
                chunks: list[str] = []
                if proc.stderr is None:
                    return ""
                while True:
                    line = await proc.stderr.readline()
                    if not line:
                        break
                    decoded = line.decode("utf-8", errors="replace").rstrip()
                    if decoded:
                        logger.info("occ| %s", decoded)
                        chunks.append(decoded)
                return "\n".join(chunks)

            stderr_task = asyncio.create_task(_drain_stderr())

            try:
                stdout_bytes = await asyncio.wait_for(
                    proc.stdout.read() if proc.stdout else asyncio.sleep(0, result=b""),
                    timeout=timeout,
                )
                rc = await asyncio.wait_for(proc.wait(), timeout=5.0)
                stderr_text = await stderr_task
            except asyncio.TimeoutError:
                proc.kill()
                try:
                    await stderr_task
                except Exception:
                    pass
                logger.error("analyze_step_assembly: timed out after %ds", timeout)
                return _fallback_response(
                    f"OCC runner timed out after {timeout}s"
                )

            stdout = stdout_bytes.decode("utf-8", errors="replace").strip() if stdout_bytes else ""

            if rc != 0:
                logger.warning(
                    "OCC runner exited with rc=%d — stderr tail: %s",
                    rc, stderr_text[-400:] if stderr_text else "-",
                )

            if not stdout:
                return _fallback_response("OCC runner produced no output")

            # The runner may emit warnings on stdout before the final JSON line;
            # pick the last non-empty line as the payload.
            last_line = ""
            for line in reversed(stdout.splitlines()):
                if line.strip():
                    last_line = line.strip()
                    break

            try:
                result = json.loads(last_line)
                elapsed = result.get("processing_time_seconds") or 0
                logger.info(
                    "analyze_step_assembly DONE: ok=%s components=%d pmi=%s runner=%.2fs",
                    result.get("ok"),
                    len(result.get("components", [])),
                    result.get("pmi_available"),
                    float(elapsed),
                )
                for _c in result.get("components", []) or []:
                    logger.info(
                        "comp[%d]: name=%s part_type=%s conf=%.2f vol=%.1f features=%d pmi=%d",
                        _c.get("component_index", -1), _c.get("name", "?"),
                        _c.get("part_type", "?"),
                        float(_c.get("part_type_confidence") or 0),
                        float(_c.get("volume_mm3") or 0),
                        len(_c.get("features") or []),
                        len(_c.get("pmi_annotations") or []),
                    )
                return result
            except json.JSONDecodeError as exc:
                logger.error(
                    "OCC runner JSON parse error: %s | raw: %s",
                    exc, last_line[:300],
                )
                return _fallback_response(f"JSON parse error: {exc}")

        except FileNotFoundError:
            logger.error("OCC runner Python not found: %s", python_exe)
            return _fallback_response(
                f"Python executable not found: {python_exe}"
            )
        except Exception as exc:
            logger.exception("analyze_step_assembly unexpected error")
            return _fallback_response(str(exc))
