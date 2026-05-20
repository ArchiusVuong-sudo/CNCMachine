"""Cycle-time math primitive for the agentic engine.

The agent reasons about which analogue or heuristic to apply; the actual
arithmetic for NC-to-cycle-time calibration lives here so it stays
deterministic and unit-testable (augmented-LLM pattern).

The calibration table is verbatim from
``KNOWLEDGE_BASE/patterns/cycle_time_model.md``. Lathe / 5-axis / turn-mill
have ``k=1.0`` only because their .MAC estimates are unreliable — for
those classes the agent should prefer an analogue rather than trusting
the calibrated number; ``source`` flags that condition.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("cncserver.engines.agentic.tools.compute")


_K_BY_MACHINE_CLASS: dict[str, float] = {
    "vmc_3_axis": 1.27,
    "vmc_3_axis_well_behaved": 1.11,
    "vmc_4_axis": 1.10,
    "router": 1.30,
    "vmc_5_axis": 1.0,
    "turn_mill": 1.0,
    "lathe": 1.0,
}
_DEFAULT_K = 1.25  # unknown class — conservative
_UNRELIABLE_CLASSES = frozenset({"vmc_5_axis", "turn_mill", "lathe"})


def compute_cycle_time(
    nc_minutes_raw: float,
    machine_class: str,
    n_pieces_per_program: int = 1,
) -> dict[str, Any]:
    """Convert raw NC-estimator minutes to a calibrated per-piece cycle time.

    Applies the multi-piece divisor first, then the machine-class ``k`` factor.

    Returns
    -------
    ``{"nc_minutes_raw", "n_pieces_per_program", "per_piece_raw_min",
       "machine_class", "k", "calibrated_min", "source"}``
    or ``{"error": "..."}`` on bad input.
    """
    try:
        raw = float(nc_minutes_raw)
    except (TypeError, ValueError):
        return {"error": f"nc_minutes_raw must be numeric, got {nc_minutes_raw!r}"}
    if raw < 0:
        return {"error": "nc_minutes_raw must be non-negative"}

    n = max(1, int(n_pieces_per_program or 1))
    per_piece_raw = raw / n

    klass = (machine_class or "").lower().strip()
    if klass in _K_BY_MACHINE_CLASS:
        k = _K_BY_MACHINE_CLASS[klass]
        if klass in _UNRELIABLE_CLASSES:
            source = "calibrated_unreliable_prefer_analogue"
        else:
            source = "calibrated"
    else:
        k = _DEFAULT_K
        source = "default_k_unknown_class"

    calibrated = per_piece_raw * k
    return {
        "nc_minutes_raw": round(raw, 3),
        "n_pieces_per_program": n,
        "per_piece_raw_min": round(per_piece_raw, 3),
        "machine_class": klass or "unknown",
        "k": round(k, 3),
        "calibrated_min": round(calibrated, 3),
        "source": source,
        # k-factor table is verbatim from this KB file; cite it.
        "citation_hint": "kb:patterns/cycle_time_model.md",
    }


COMPUTE_TOOL_SPECS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "compute_cycle_time",
            "description": (
                "Calibrate raw NC-program minutes into per-piece cycle time. "
                "Applies multi-piece divisor first, then machine-class k. "
                "Machine class: vmc_3_axis (k=1.27), vmc_3_axis_well_behaved (k=1.11), "
                "vmc_4_axis (k=1.10), router (k=1.30), "
                "vmc_5_axis/turn_mill/lathe (k=1.0, .MAC unreliable — prefer analogue)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "nc_minutes_raw": {"type": "number"},
                    "machine_class": {
                        "type": "string",
                        "description": "vmc_3_axis | vmc_3_axis_well_behaved | vmc_4_axis | vmc_5_axis | router | turn_mill | lathe",
                    },
                    "n_pieces_per_program": {
                        "type": "integer",
                        "description": "Default 1; use the -NPC- divisor from the program name when applicable.",
                    },
                },
                "required": ["nc_minutes_raw", "machine_class"],
            },
        },
    },
]
