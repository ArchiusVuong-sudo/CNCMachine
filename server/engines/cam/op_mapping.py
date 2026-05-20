"""Op-code → FreeCAD Path operation mapping.

Pure data module. No FreeCAD imports here — this table is serialized into
the JSON job spec the parent process hands to the FreeCAD subprocess, and
:mod:`.freecad_script` reads the strings back to pick a concrete Path
constructor at runtime.

Vocabulary
----------
* **op_code** — short routing code emitted by Phase B (Engine 3):
  ``CNCM_*`` for mill ops, ``CNCT_*`` for lathe ops. Non-CAM rows like
  ``DEBUR`` / ``INSPECT`` / ``LASER_CUT`` are deliberately absent — the
  CAM engine skips them.
* **path_op** — the FreeCAD Path workbench operation name. Mill ops use
  vanilla ``Path.Pocket`` / ``Path.Profile`` / ``Path.Drilling`` from
  core FreeCAD; lathe ops use ``Path.Turn*`` from the Path-Turn addon.
* **kind** — high-level family so the script knows which boilerplate
  (tool controller wiring, post-processor selection) to apply.

The dict order matters for nothing — lookup is by op_code.
"""
from __future__ import annotations

from typing import Literal, TypedDict

OpKind = Literal["mill", "drill", "tap", "lathe", "thread"]


class OpEntry(TypedDict):
    """One op_code → FreeCAD-op binding."""

    path_op: str
    kind:    OpKind
    notes:   str


# fmt: off
OP_MAPPING: dict[str, OpEntry] = {
    # ── Milling ──────────────────────────────────────────────────────────
    "CNCM_ROUGH":   {"path_op": "Path.Pocket",    "kind": "mill",
                     "notes": "Adaptive rough; full stepdown allowed"},
    "CNCM_FINISH":  {"path_op": "Path.Profile",   "kind": "mill",
                     "notes": "Contour finish along feature boundary"},
    "CNCM_POCKET":  {"path_op": "Path.Pocket",    "kind": "mill",
                     "notes": "Closed-pocket clearing"},
    "CNCM_SLOT":    {"path_op": "Path.Profile",   "kind": "mill",
                     "notes": "Open-ended slot — profile along centerline"},
    "CNCM_CHAMFER": {"path_op": "Path.Profile",   "kind": "mill",
                     "notes": "Edge chamfer; tool chosen by Phase C"},
    "CNCM_FACE":    {"path_op": "Path.Surface",   "kind": "mill",
                     "notes": "Face-mill the top stock face"},
    "CNCM_ENGRAVE": {"path_op": "Path.Engrave",   "kind": "mill",
                     "notes": "Text or vector engraving"},
    # ── Drilling & Tapping ───────────────────────────────────────────────
    "CNCM_DRILL":   {"path_op": "Path.Drilling",  "kind": "drill",
                     "notes": "Peck or straight drill cycle (G83/G81)"},
    "CNCM_REAM":    {"path_op": "Path.Drilling",  "kind": "drill",
                     "notes": "Reaming pass — feed-based G85"},
    "CNCM_TAP":     {"path_op": "Path.Drilling",  "kind": "tap",
                     "notes": "Rigid-tap canned cycle (G84) — script sets dwell"},
    # ── Turning (lathe) ──────────────────────────────────────────────────
    "CNCT_FACE":    {"path_op": "Path.TurnFace",  "kind": "lathe",
                     "notes": "Facing pass on lathe spindle"},
    "CNCT_TURN":    {"path_op": "Path.TurnProfile", "kind": "lathe",
                     "notes": "OD/ID turning profile pass"},
    "CNCT_ROUGH":   {"path_op": "Path.TurnProfile", "kind": "lathe",
                     "notes": "Roughing pass — multiple depths"},
    "CNCT_FINISH":  {"path_op": "Path.TurnProfile", "kind": "lathe",
                     "notes": "Finishing pass — single depth"},
    "CNCT_BORE":    {"path_op": "Path.TurnProfile", "kind": "lathe",
                     "notes": "Internal turning (boring)"},
    "CNCT_GROOVE":  {"path_op": "Path.TurnGroove", "kind": "lathe",
                     "notes": "Plunge groove with form tool"},
    "CNCT_PARTOFF": {"path_op": "Path.TurnGroove", "kind": "lathe",
                     "notes": "Parting cut — full-depth groove"},
    "CNCT_THREAD":  {"path_op": "Path.TurnThread", "kind": "thread",
                     "notes": "Single-point threading (G76)"},
}
# fmt: on


def lookup(op_code: str) -> OpEntry | None:
    """Return the FreeCAD binding for ``op_code`` or ``None`` if non-CAM."""
    return OP_MAPPING.get((op_code or "").strip().upper())


def is_cam_op(op_code: str) -> bool:
    """True when this op produces toolpaths the CAM engine should emit."""
    return lookup(op_code) is not None


__all__ = ["OP_MAPPING", "OpEntry", "OpKind", "lookup", "is_cam_op"]
