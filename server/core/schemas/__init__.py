"""Pydantic boundary contracts for the modular monolith.

Engines never trade in opaque ``dict`` blobs at their public surface — they
return one of the models defined here, and the orchestrator passes those
same models on to the next engine. This guarantees that:

  * Inter-engine wire shapes stay declarative and refactor-friendly.
  * The SSE final_answer payload is a single ``model_dump()`` call away.
  * Any extra diagnostic keys engines want to bolt on travel through
    because we set ``extra="allow"`` on the contract models — the
    declared fields are validated, the rest is preserved.

The shared kernel intentionally re-exports the most common names so
engines can do ``from server.core.schemas import DrawingExtraction``
without spelunking into the submodules.
"""
from __future__ import annotations

from .enums import (
    FeatureType,
    JobStatus,
    PartType,
    PMIType,
    ProcessCategory,
    ProcessType,
    SurfaceType,
)
from .geometry import (
    BoundingBox,
    CutoutPerimeter,
    FaceTypeCounts,
    PerimeterData,
    Point3D,
    ThicknessStats,
)
from .features import FeatureDetail, SimpleFeature
from .pmi import PMIAnnotation
from .drawing import (
    BomItem,
    DimensionRow,
    DrawingExtraction,
    GdtCallout,
    ThreadSpec,
    TitleBlock,
)
from .assembly import AssemblyData, Component, WeldingContact
from .plan import (
    CostBreakdown,
    ManufacturingProcess,
    ProcessPlan,
    RoutingRow,
)
from .events import SSEEvent
from .api import AnalyzeRequest, HealthResponse

__all__ = [
    # enums
    "FeatureType", "JobStatus", "PartType", "PMIType",
    "ProcessCategory", "ProcessType", "SurfaceType",
    # geometry
    "BoundingBox", "CutoutPerimeter", "FaceTypeCounts",
    "PerimeterData", "Point3D", "ThicknessStats",
    # features / pmi
    "FeatureDetail", "SimpleFeature", "PMIAnnotation",
    # drawing (engine 1)
    "BomItem", "DimensionRow", "DrawingExtraction",
    "GdtCallout", "ThreadSpec", "TitleBlock",
    # assembly (engine 2)
    "AssemblyData", "Component", "WeldingContact",
    # plan (engine 3)
    "CostBreakdown", "ManufacturingProcess",
    "ProcessPlan", "RoutingRow",
    # transport
    "SSEEvent",
    # API
    "AnalyzeRequest", "HealthResponse",
]
