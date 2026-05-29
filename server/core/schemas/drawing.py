"""Engine 1 contract — structured 2D drawing extraction.

``DrawingExtraction`` is the wire format Engine 1 (VLM) produces and that
Engine 3 (process mapping) consumes downstream. All sub-models use
``extra='allow'`` so the VLM can emit additional opportunistic fields
(part-mark hints, surface-finish lookups, etc.) without us having to
update the schema every time the prompt changes.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TitleBlock(BaseModel):
    """Title-block fields lifted from the drawing border."""

    model_config = ConfigDict(extra="allow")

    part_number:    str | None = None
    revision:       str | None = None
    title:          str | None = None
    description:    str | None = None
    drawn_by:       str | None = None
    checked_by:     str | None = None
    date:           str | None = None
    company:        str | None = None
    scale:          str | None = None
    sheet:          str | None = None
    dimension_unit: str | None = Field(
        None, description='"mm" or "in" if the title block states it explicitly',
    )


class BomItem(BaseModel):
    """One line item from the drawing's Bill of Materials."""

    model_config = ConfigDict(extra="allow")

    item_no:     int | str | None = None
    part_number: str | None = None
    description: str | None = None
    qty:         int | float | None = None
    tengc:       str | None = Field(
        None, description="Optional TEngC# / Tengineering number for fuzzy matching",
    )
    material:    str | None = None
    part_type:   str | None = Field(
        None,
        description=(
            "Inferred bucket: cnc_machined | sheet_metal | hardware | "
            "tube_pipe | weldment | …"
        ),
    )


class DimensionRow(BaseModel):
    """A single dimension callout extracted from the drawing."""

    model_config = ConfigDict(extra="allow")

    label:           str | None = None
    nominal:         float | str | None = None
    unit:            str | None = None
    tolerance_plus:  float | None = None
    tolerance_minus: float | None = None
    tolerance:       str | None = None
    notes:           str | None = None


class GdtCallout(BaseModel):
    """One GD&T / FCF (feature-control frame) callout."""

    model_config = ConfigDict(extra="allow")

    symbol:        str | None = None
    tolerance:     str | None = None
    datum_refs:    list[str] = Field(default_factory=list)
    feature_label: str | None = None


class ThreadSpec(BaseModel):
    """One thread callout (e.g. ``M6x1.0``, ``1/4-20 UNC``)."""

    model_config = ConfigDict(extra="allow")

    spec:        str | None = None
    label:       str | None = None
    count:       int | None = None
    depth_mm:    float | None = None
    is_blind:    bool | None = None


class DrawingExtraction(BaseModel):
    """Engine 1 output — the canonical 2D-drawing payload.

    Field names mirror the existing ``engine_extract_2d`` return dict so the
    new pipeline can be A/B tested against the old one without remapping.
    """

    model_config = ConfigDict(extra="allow")

    part_number:    str = ""
    revision:       str = ""
    description:    str = ""
    material:       str = ""
    surface_finish: str | None = None
    dimension_unit: str = Field("mm", description='"mm" | "in"')
    # Drawing-level "mfg spec" (brief Page 3 OCR output). Mirrors the
    # VLM's `assembly_method` JSON key — bolted | welded | riveted |
    # bonded | null. Drives top-level `part_category` derivation.
    assembly_method: str | None = None
    # Drawing-level part category (brief Page 3 OCR output, distinct
    # from per-row BomItem.part_type). Derived from assembly_method +
    # BOM heterogeneity:
    #   assembly_method=welded   → "weldment"
    #   assembly_method=bolted   → "assembly_bolted"
    #   assembly_method=riveted  → "assembly_riveted"
    #   assembly_method=bonded   → "assembly_bonded"
    #   single BOM row           → that row's part_type
    #   multi-row, no method     → "assembly"
    part_category:  str | None = None
    title_block:    TitleBlock | dict | None = None
    bom_items:      list[BomItem | dict] = Field(default_factory=list)
    drawing_notes:  list[str] = Field(default_factory=list)
    dimensions:     list[DimensionRow | dict] = Field(default_factory=list)
    gdt_callouts:   list[GdtCallout | dict] = Field(default_factory=list)
    threads:        list[ThreadSpec | dict] = Field(default_factory=list)

    @classmethod
    def empty(cls) -> DrawingExtraction:
        """Return the schema-valid sentinel used when VLM produces nothing."""
        return cls()

    def as_dict(self) -> dict[str, Any]:
        """Convenience: snapshot ready for SSE final_answer payload."""
        return self.model_dump(mode="json")
