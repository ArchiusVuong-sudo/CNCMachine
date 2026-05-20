"""Process-mapping helpers — shared by the agentic engine.

Originally this package held the full rule-based Engine 3. After the
agentic rollout the imperative engine was removed; only the helpers that
the LLM coordinator reuses live here:

  * :mod:`.bom_mapper`         — drawing-BOM ↔ 3D-component fuzzy matcher.
  * :mod:`.category_reconciler`— OCR-declared vs AFR-detected part type.
  * :mod:`.dim_tagger`         — drawing dims/GD&T/threads → AFR features.
  * :mod:`.cost_engine`        — labor + machine + tool → USD per component.

The public Engine-3 entry now lives at
:func:`server.engines.agentic.dispatch`. Callers should never import a
``run`` function from this package.
"""
from __future__ import annotations

from ...core.schemas import ProcessPlan

__all__ = ["ProcessPlan"]
