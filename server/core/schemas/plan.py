"""Engine 3 contract — process planning, routing, and cost.

Three nested models:
  * :class:`ManufacturingProcess` — one logical operation with its
    cutting parameters and (optionally) the machine + tool the cost engine
    selected.
  * :class:`RoutingRow` — one row of the shop-floor routing (setup + run
    times, sequence number, op description). The pipeline keeps a list per
    component for the SSE final_answer payload.
  * :class:`ProcessPlan` — full Engine 3 output: per-component process
    lists, routing matrix, cost breakdown, and the catalog snapshot used
    for the cost calculation.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .enums import ProcessCategory, ProcessType
from .assembly import Component


OperationType = Literal["Roughing", "Finishing"]


class ManufacturingProcess(BaseModel):
    """One logical manufacturing operation on a component.

    All CNC-specific fields are optional — sheet-metal & hardware
    processes leave them None, milling/turning processes populate them
    with the chosen machine + tool + cutting parameters.
    """

    model_config = ConfigDict(extra="allow")

    process_type:        ProcessType
    category:            ProcessCategory
    sequence_order:      int
    operation_count:     int = 1
    driven_by_features:  list[str] = Field(
        default_factory=list,
        description="Feature IDs whose existence requires this process",
    )
    notes:               str | None = None
    cut_length_mm:       float | None = None
    bend_count:          int | None = None
    total_bend_length_mm: float | None = None
    # CNC-specific routing fields ----------------------------------------
    operation_type:      OperationType | None = Field(
        None,
        description="Roughing vs Finishing — only set for material-removal ops",
    )
    cycle_time_minutes:  float | None = None
    machine_id:          str | None = None
    tool_id:             str | None = None
    tool_type:           str | None = Field(
        None,
        description="Tool family from Phase C: End Mill | Chamfer Mill | "
                    "Ball Mill | Face Mill | Drill | Thread Mill | Form Tool | "
                    "Radius Mill | Slitting Saw | Dovetail",
    )
    tool_diameter_mm:    float | None = None
    tool_dimensions:     dict[str, float] | None = Field(
        None,
        description="Tool geometry key-values: diameter_mm, length_mm, "
                    "width_mm, height_mm, corner_radius_mm",
    )
    batch_size:          int | None = None
    raw_material_stock_id: str | None = None
    spindle_speed_rpm:   float | None = None
    feed_rate_mm_min:    float | None = None
    stepover_mm:         float | None = None
    stepdown_mm:         float | None = None
    toolpath_length_mm:  float | None = None


class RoutingRow(BaseModel):
    """One row of the shop-floor routing for a component.

    Matches the customer's spreadsheet shape: per-lot setup time and
    per-piece run time combine into the row's ``cycle_time_min``.
    """

    model_config = ConfigDict(extra="allow")

    sequence:           int
    op_code:            str = Field(
        description="Short code like 'CNCM_ROUGH', 'LASER_CUT', 'DEBUR', 'INSPECT'",
    )
    description:        str = ""
    process_type:       ProcessType | str | None = None
    category:           ProcessCategory | str | None = None
    operation_type:     OperationType | None = Field(
        None,
        description="Roughing vs Finishing — only set for material-removal rows",
    )
    setup_min_per_lot:  float = 0.0
    run_min_per_part:   float = 0.0
    cycle_time_min:     float = 0.0
    machine_id:         str | None = None
    machine_name:       str | None = None
    tool_ids:           list[str] = Field(default_factory=list)
    tool_type:          str | None = Field(
        None,
        description="Tool family from Phase C (one of the 10 Tool Type values)",
    )
    tool_dimensions:    dict[str, float] | None = Field(
        None,
        description="Tool geometry key-values: diameter_mm, length_mm, "
                    "width_mm, height_mm, corner_radius_mm",
    )
    feature_ids:        list[str] = Field(default_factory=list)
    notes:              str | None = None


class ComponentCost(BaseModel):
    """Per-component cost breakdown — entry in ``CostBreakdown.by_component``."""

    model_config = ConfigDict(extra="allow")

    component_index:     int
    component_name:      str = ""
    total_usd:           float = 0.0
    raw_material_usd:    float = 0.0
    setup_usd:           float = 0.0
    machining_total_usd: float = 0.0
    machining_usd_by_process: dict[str, float] = Field(default_factory=dict)
    deburr_usd:          float = 0.0
    inspection_usd:      float = 0.0
    overhead_usd:        float = 0.0
    finishing_usd:       float = 0.0


class CostBreakdown(BaseModel):
    """Aggregate cost result for the whole assembly."""

    model_config = ConfigDict(extra="allow")

    total_usd:    float = 0.0
    by_component: list[ComponentCost | dict] = Field(
        default_factory=list,
        alias="breakdown_by_component",
    )
    currency:     str = "USD"
    batch_size:   int = 1


class CategoryDecision(BaseModel):
    """One reconciler decision: OCR-declared vs AFR-detected part type."""

    model_config = ConfigDict(extra="allow")

    component_index:        int
    component_name:         str = ""
    afr_part_type:          str | None = None
    bom_part_type:          str | None = None
    reconciled_part_type:   str | None = None
    changed:                bool = False
    reason:                 str = ""
    confidence:             float = 0.0


class ProcessPlan(BaseModel):
    """Engine 3 output — the canonical process-planning payload."""

    model_config = ConfigDict(extra="allow")

    components:              list[Component | dict] = Field(default_factory=list)
    processes_per_component: list[list[RoutingRow | dict]] = Field(
        default_factory=list,
        description="One routing-row list per component, in component_index order",
    )
    cost:                    CostBreakdown = Field(default_factory=CostBreakdown)
    category_decisions:      list[CategoryDecision | dict] = Field(default_factory=list)
    catalog:                 dict = Field(
        default_factory=dict,
        description="Snapshot of labor/machines/tools/materials catalog used",
    )

    def as_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True)

    @classmethod
    def empty(
        cls,
        *,
        components: list[Component | dict] | None = None,
        catalog: dict | None = None,
        error: str | None = None,
    ) -> "ProcessPlan":
        """Sentinel for a failed planner run — orchestrator + persistence treat
        this exactly like a successful empty plan (no routing, zero cost).

        Mirrors the ``DrawingExtraction.empty()`` / ``AssemblyData.empty()``
        pattern in Engines 1 and 2, so any planner engine can return this
        shape on irrecoverable failure instead of raising. The optional
        ``error`` is attached as an extra field (allowed by extra='allow')
        so the orchestrator can surface it in the trace without coupling
        to a specific engine's internal error shape.
        """
        comps = list(components or [])
        plan = cls(
            components=comps,
            processes_per_component=[[] for _ in comps],
            cost=CostBreakdown(),
            category_decisions=[],
            catalog=catalog or {},
        )
        if error:
            # extra='allow' carries this through to the SSE final_answer.
            plan.__pydantic_extra__["error"] = error  # type: ignore[union-attr]
        return plan
