"""extraction_3d — STEP assembly decomposition + B-Rep feature recognition.

Public entry point: :func:`run` (bytes in, :class:`AssemblyData` out).

Sub-modules:
  * :mod:`subprocess_runner` — async wrapper around the OCC child Python.
  * :mod:`runner_script`     — the heredoc executed by that child.
  * :mod:`welding`           — FreeCAD pairwise contact detector.
  * :mod:`occ.*`             — the vendored cadquery-ocp feature recognizer.

The ``occ`` subpackage requires ``cadquery-ocp`` to import, which is
incompatible with FreeCAD inside one Python — hence the subprocess split.
"""
from ...core.schemas import AssemblyData
from .engine import run

__all__ = ["run", "AssemblyData"]
