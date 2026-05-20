"""Engine 2 contract — STEP assembly decomposition + feature recognition.

``AssemblyData`` is the wire format Engine 2 produces. It carries the
per-component breakdown (with features, PMI, bbox, etc.) plus the
welding contacts the welding detector found between components.

Engine 3 mutates ``components`` in-place (adding stock, machine, tooling,
G-code, etc.) so each ``Component`` is intentionally loose
(``extra='allow'``) — the declared fields are the *minimum* contract;
anything Engine 3 bolts on flows through to the SSE response.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .enums import PartType
from .features import SimpleFeature
from .geometry import BoundingBox, FaceTypeCounts, PerimeterData, ThicknessStats
from .pmi import PMIAnnotation


class Component(BaseModel):
    """One leaf body in the STEP assembly (or the lone body of a part file).

    Engine 2 populates the geometry / classification fields; Engine 3
    decorates it with material, stock match, machine, tooling, G-code,
    routing, cost — all carried as ``extra`` fields rather than declared
    here so the contract stays narrow.
    """

    model_config = ConfigDict(extra="allow")

    component_index:        int = 0
    name:                   str = ""
    description:            str = ""
    instance_count:         int = 1
    part_type:              PartType = PartType.UNKNOWN
    part_type_confidence:   float = Field(0.0, ge=0.0, le=1.0)
    volume_mm3:             float = 0.0
    surface_area_mm2:       float = 0.0
    bbox:                   BoundingBox | dict | None = None
    bounding_box:           BoundingBox | dict | None = Field(
        None, description="Alias for bbox; preserved for legacy callers",
    )
    face_type_counts:       FaceTypeCounts | dict | None = None
    thickness:              ThicknessStats | dict | None = None
    perimeter:              PerimeterData | dict | None = None
    total_perimeter_mm:     float | None = None
    features:               list[SimpleFeature | dict] = Field(default_factory=list)
    pmi_available:          bool = False
    pmi_annotations:        list[PMIAnnotation | dict] = Field(default_factory=list)


class WeldingContact(BaseModel):
    """One detected contact between two STEP components."""

    model_config = ConfigDict(extra="allow")

    component_a_index: int | None = None
    component_b_index: int | None = None
    component_a:       str | None = None
    component_b:       str | None = None
    contact_type:      str | None = Field(
        None, description="butt | lap | fillet | edge | tee | corner …",
    )
    contact_area_mm2:  float | None = None
    weld_length_mm:    float | None = None
    confidence:        float | None = None


class AssemblyData(BaseModel):
    """Engine 2 output — the canonical 3D-feature-recognition payload."""

    model_config = ConfigDict(extra="allow")

    ok:                bool = True
    assembly_name:     str = ""
    file_name:         str = ""
    component_count:   int = 0
    total_volume_mm3:  float = 0.0
    pmi_available:     bool = False
    components:        list[Component | dict] = Field(default_factory=list)
    welding_contacts:  list[WeldingContact | dict] = Field(default_factory=list)
    error:             str | None = Field(None, description="Populated on failure")

    @classmethod
    def empty(cls, *, error: str | None = None) -> AssemblyData:
        """Schema-valid sentinel used when the subprocess fails outright."""
        return cls(ok=False, error=error)

    def as_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
