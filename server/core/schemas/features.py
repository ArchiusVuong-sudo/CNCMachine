"""Recognised 3D features attached to a component."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .enums import FeatureType
from .geometry import Point3D


class FeatureDetail(BaseModel):
    """A single feature recognised on a component, with full provenance.

    Carries the orientation vector and ``key_face_id`` because FreeCAD Path
    needs to map back from features to OCC face hashes when generating
    G-code operations.
    """

    model_config = ConfigDict(extra="allow")

    feature_id:    str
    feature_type:  FeatureType
    count:         int = 1
    confidence:    float = Field(ge=0.0, le=1.0)
    source:        str = Field(description="rule_based | uvnet | merged")
    dimensions:    dict = Field(
        default_factory=dict,
        description="Feature-specific dims, e.g. {diameter_mm, depth_mm}",
    )
    perimeter_mm:  float | None = Field(
        None, description="Cut perimeter length for cut-style features",
    )
    location:      Point3D | None = None
    face_indices:  list[int] = Field(default_factory=list)
    orientation:   list[float] | None = Field(
        None, description="Unit direction vector [x, y, z]",
    )
    key_face_id:   str | None = Field(
        None, description="Persistent geometric hash for FreeCAD Path linkage",
    )


class SimpleFeature(BaseModel):
    """Slim feature view exposed in the assembly response."""

    model_config = ConfigDict(extra="allow")

    feature_type: FeatureType
    count:        int = 1
    dimensions:   dict = Field(default_factory=dict)
    orientation:  list[float] | None = None
    key_face_id:  str | None = None
