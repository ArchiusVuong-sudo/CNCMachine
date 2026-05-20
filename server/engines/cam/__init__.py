"""Engine 4 — CAM (Computer-Aided Manufacturing) consumer.

Consumes the :class:`ProcessPlan` from Engine 3 + the STEP bytes from
Phase 0 and produces G-code (.nc) files via a FreeCAD Path subprocess.

The engine is intentionally isolated in a subprocess because the
FreeCAD Python (built against its own Qt + OCC) is ABI-incompatible
with the cadquery-ocp wheel the parent FastAPI uses for Engine 2. The
subprocess pattern is cloned from
:mod:`server.engines.extraction_3d.welding`.

Public entry: :func:`server.engines.cam.engine.run`.
"""
from __future__ import annotations

from .engine import CAMOutput, run

__all__ = ["run", "CAMOutput"]
