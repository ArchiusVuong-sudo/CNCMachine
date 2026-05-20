"""Product Manufacturing Information (PMI) annotations from STEP-AP242."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .enums import PMIType


class PMIAnnotation(BaseModel):
    """One PMI annotation (GD&T, dimensional tolerance, finish, datum, note)."""

    model_config = ConfigDict(extra="allow")

    annotation_type: PMIType
    value:                 str | None = None
    tolerance_plus:        float | None = None
    tolerance_minus:       float | None = None
    datum_refs:            list[str] = Field(default_factory=list)
    associated_feature_id: str | None = None
