"""Geometric primitives shared between Engine 2 and Engine 3."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Point3D(BaseModel):
    """A point in part-local mm coordinates."""

    x: float
    y: float
    z: float


class BoundingBox(BaseModel):
    """Axis-aligned bounding box in mm.

    The min/max corners come straight from OCC; ``length / width / height``
    are derivable but stored for convenience because routing & cost code
    references them by name in dozens of places.
    """

    x_min: float
    y_min: float
    z_min: float
    x_max: float
    y_max: float
    z_max: float
    length: float = Field(description="X extent (x_max - x_min) in mm")
    width:  float = Field(description="Y extent (y_max - y_min) in mm")
    height: float = Field(description="Z extent (z_max - z_min) in mm")


class FaceTypeCounts(BaseModel):
    """Histogram of surface types on a body — drives part classification."""

    plane:    int = 0
    cylinder: int = 0
    cone:     int = 0
    sphere:   int = 0
    torus:    int = 0
    bspline:  int = 0
    other:    int = 0
    total:    int = 0


class ThicknessStats(BaseModel):
    """Wall-thickness statistics for sheet-metal classification."""

    min_mm:      float
    max_mm:      float
    mean_mm:     float
    std_dev_mm:  float
    is_uniform:  bool = Field(description="True when std_dev < 5% of mean")


class CutoutPerimeter(BaseModel):
    """One internal cut-out boundary on a sheet-metal blank."""

    wire_index:   int
    perimeter_mm: float
    is_circular:  bool
    diameter_mm:  float | None = None


class PerimeterData(BaseModel):
    """Outer + inner cut perimeters for laser/waterjet time estimation."""

    model_config = ConfigDict(extra="allow")

    outer_perimeter_mm:    float
    cutout_perimeters:     list[CutoutPerimeter] = Field(default_factory=list)
    total_cut_length_mm:   float = Field(
        description="outer_perimeter + sum(cutout_perimeters) in mm",
    )
