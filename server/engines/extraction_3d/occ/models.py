"""Pydantic models for the STEP Assembly Analyzer API."""

from __future__ import annotations

import enum
from typing import Optional

from pydantic import BaseModel, Field


# ── Enums ────────────────────────────────────────────────────────────────────


class PartType(str, enum.Enum):
    SHEET_METAL = "sheet_metal"
    CNC_MILLING = "cnc_milling"
    CNC_LATHE = "cnc_lathe"
    CNC_LATHE_MILLING = "cnc_lathe_milling"
    TUBE_PIPE = "tube_pipe"
    HARDWARE = "hardware"
    UNKNOWN = "unknown"


class FeatureType(str, enum.Enum):
    """Controlled vocabulary — must mirror
    ``server.core.schemas.enums.FeatureType`` (19 values + UNKNOWN).
    """

    # Hole-making
    THROUGH_HOLE = "through_hole"
    BLIND_HOLE = "blind_hole"
    DRILLED_HOLE = "drilled_hole"
    COUNTERBORE = "counterbore"
    COUNTERSINK = "countersink"
    TAPERED_BORE = "tapered_bore"
    # Milling
    POCKET = "pocket"
    STEP = "step"
    FILLET = "fillet"
    CHAMFER = "chamfer"
    THREAD = "thread"
    BOSS = "boss"
    RIB = "rib"
    DRAFT = "draft"
    UNDERCUT = "undercut"
    GROOVE = "groove"
    # Turning
    LATHE_OD = "lathe_od"
    TAPERED_OD = "tapered_od"
    # Facing
    FACE = "face"
    # Sentinel
    UNKNOWN = "unknown"


class ProcessCategory(str, enum.Enum):
    CUTTING = "cutting"
    HOLE_MAKING = "hole_making"
    FORMING = "forming"
    JOINING = "joining"
    FINISHING = "finishing"
    MACHINING = "machining"
    PROCUREMENT = "procurement"


class ProcessType(str, enum.Enum):
    # Cutting
    LASER_CUTTING = "laser_cutting"
    PLASMA_CUTTING = "plasma_cutting"
    WATERJET_CUTTING = "waterjet_cutting"
    BLANKING = "blanking"
    SHEARING = "shearing"
    NIBBLING = "nibbling"
    FINE_BLANKING = "fine_blanking"
    # Hole-making
    PUNCHING = "punching"
    DRILLING = "drilling"
    REAMING = "reaming"
    BORING = "boring"
    LANCING = "lancing"
    PERFORATING = "perforating"
    # Forming
    PRESS_BRAKE_BENDING = "press_brake_bending"
    COINING = "coining"
    EMBOSSING = "embossing"
    BRIDGE_FORMING = "bridge_forming"
    JOGGLE_FORMING = "joggle_forming"
    HEMMING = "hemming"
    BEADING = "beading"
    CURLING = "curling"
    FLANGING = "flanging"
    DEEP_DRAWING = "deep_drawing"
    STRETCH_FORMING = "stretch_forming"
    HYDROFORMING = "hydroforming"
    ROLL_FORMING = "roll_forming"
    STAMPING = "stamping"
    SPINNING = "spinning"
    # Joining
    TIG_WELDING = "tig_welding"
    MIG_WELDING = "mig_welding"
    SPOT_WELDING = "spot_welding"
    SEAM_WELDING = "seam_welding"
    RIVETING = "riveting"
    CLINCHING = "clinching"
    # Finishing
    DEBURRING = "deburring"
    ANODIZING = "anodizing"
    POWDER_COATING = "powder_coating"
    PAINTING = "painting"
    PLATING = "plating"
    PASSIVATION = "passivation"
    POLISHING = "polishing"
    GRINDING = "grinding"
    # CNC machining
    CNC_MILLING = "cnc_milling"
    CNC_TURNING = "cnc_turning"
    TAPPING = "tapping"
    THREAD_MILLING = "thread_milling"
    EDM = "edm"
    FACING = "facing"
    GROOVING = "grooving"
    KNURLING = "knurling"
    # CNC machining — granular types for detailed process planning
    FACE_MILLING = "face_milling"
    SPOT_DRILLING = "spot_drilling"
    PARTING = "parting"
    COUNTERBORING = "counterboring"
    COUNTERSINKING = "countersinking"
    # Tube
    TUBE_LASER_CUTTING = "tube_laser_cutting"
    TUBE_BENDING = "tube_bending"
    CNC_FINISHING = "cnc_finishing"

    # Assembly
    FASTENING = "fastening"
    ASSEMBLY_FIT_UP = "assembly_fit_up"
    # General
    PROCUREMENT = "procurement"
    RAW_MATERIAL_PREP = "raw_material_prep"
    BAR_STOCK_PREP = "bar_stock_prep"
    SURFACE_TREATMENT = "surface_treatment"
    # Setup / auxiliary
    SETUP = "setup"
    TOOL_CHANGE = "tool_change"


class SurfaceType(str, enum.Enum):
    PLANE = "plane"
    CYLINDER = "cylinder"
    CONE = "cone"
    SPHERE = "sphere"
    TORUS = "torus"
    BSPLINE = "bspline"
    OTHER = "other"


class PMIType(str, enum.Enum):
    DIMENSIONAL = "dimensional"
    GEOMETRIC = "geometric"
    SURFACE_FINISH = "surface_finish"
    DATUM = "datum"
    NOTE = "note"


# ── Geometry Sub-Models ──────────────────────────────────────────────────────


class BoundingBox(BaseModel):
    x_min: float
    y_min: float
    z_min: float
    x_max: float
    y_max: float
    z_max: float
    length: float = Field(description="X extent")
    width: float = Field(description="Y extent")
    height: float = Field(description="Z extent")


class Point3D(BaseModel):
    x: float
    y: float
    z: float


class FaceTypeCounts(BaseModel):
    plane: int = 0
    cylinder: int = 0
    cone: int = 0
    sphere: int = 0
    torus: int = 0
    bspline: int = 0
    other: int = 0
    total: int = 0


class ThicknessStats(BaseModel):
    min_mm: float
    max_mm: float
    mean_mm: float
    std_dev_mm: float
    is_uniform: bool = Field(description="std_dev < 5% of mean")


class CutoutPerimeter(BaseModel):
    wire_index: int
    perimeter_mm: float
    is_circular: bool
    diameter_mm: Optional[float] = None


class PerimeterData(BaseModel):
    outer_perimeter_mm: float
    cutout_perimeters: list[CutoutPerimeter] = []
    total_cut_length_mm: float = Field(
        description="outer_perimeter + sum(cutout_perimeters)"
    )


# ── Feature Models ───────────────────────────────────────────────────────────


class FeatureDetail(BaseModel):
    feature_id: str
    feature_type: FeatureType
    count: int = 1
    confidence: float = Field(ge=0.0, le=1.0)
    source: str = Field(description="rule_based | uvnet | merged")
    dimensions: dict = Field(
        default_factory=dict,
        description="Feature-specific dimensions, e.g. {diameter_mm, depth_mm}",
    )
    perimeter_mm: Optional[float] = Field(
        None, description="Cut perimeter length for cut features"
    )
    location: Optional[Point3D] = None
    face_indices: list[int] = Field(default_factory=list)
    orientation: Optional[list[float]] = Field(
        None, description="Unit direction vector [x, y, z] indicating feature orientation"
    )
    key_face_id: Optional[str] = Field(
        None, description="Persistent geometric hash ID of the key face for FreeCAD PATH linkage"
    )


# ── PMI Models ───────────────────────────────────────────────────────────────


class PMIAnnotation(BaseModel):
    annotation_type: PMIType
    value: Optional[str] = None
    tolerance_plus: Optional[float] = None
    tolerance_minus: Optional[float] = None
    datum_refs: list[str] = Field(default_factory=list)
    associated_feature_id: Optional[str] = None


# ── Manufacturing Process Models ─────────────────────────────────────────────


class ManufacturingProcess(BaseModel):
    process_type: ProcessType
    category: ProcessCategory
    sequence_order: int
    operation_count: int = 1
    driven_by_features: list[str] = Field(
        default_factory=list, description="Feature IDs that require this process"
    )
    notes: Optional[str] = None
    cut_length_mm: Optional[float] = Field(
        None, description="Total cut length for cutting processes"
    )
    bend_count: Optional[int] = None
    total_bend_length_mm: Optional[float] = None
    # CNC-specific fields (populated by cnc_process_mapper; None for other part types)
    cycle_time_minutes: Optional[float] = Field(None, description="Estimated machining cycle time in minutes")
    machine_id: Optional[str] = Field(None, description="Selected machine identifier")
    tool_id: Optional[str] = Field(None, description="Selected cutting tool identifier")
    tool_diameter_mm: Optional[float] = Field(None, description="Cutting tool diameter in mm")
    batch_size: Optional[int] = Field(None, description="Number of parts per raw material stock piece")
    raw_material_stock_id: Optional[str] = Field(None, description="Raw material stock identifier")
    spindle_speed_rpm: Optional[float] = None
    feed_rate_mm_min: Optional[float] = None
    stepover_mm: Optional[float] = None
    stepdown_mm: Optional[float] = None
    toolpath_length_mm: Optional[float] = Field(None, description="Total toolpath length in mm")


# ── Simplified Feature ───────────────────────────────────────────────────────


class SimpleFeature(BaseModel):
    feature_type: FeatureType
    count: int = 1
    dimensions: dict = Field(default_factory=dict)
    orientation: Optional[list[float]] = Field(
        None, description="Unit direction vector [x, y, z] indicating feature orientation"
    )
    key_face_id: Optional[str] = Field(
        None, description="Persistent geometric hash ID of the key face for FreeCAD PATH linkage"
    )


# ── Component-Level Response ─────────────────────────────────────────────────


class ComponentAnalysis(BaseModel):
    name: str
    description: str = Field(
        "", description="Product description extracted from the STEP file"
    )
    instance_count: int = Field(1, description="Number of identical instances in the assembly")
    part_type: PartType
    part_type_confidence: float = Field(ge=0.0, le=1.0)
    volume_mm3: float
    surface_area_mm2: float
    bounding_box: BoundingBox
    thickness: Optional[ThicknessStats] = None
    total_perimeter_mm: Optional[float] = None
    features: list[SimpleFeature] = Field(default_factory=list)
    pmi_available: bool = False
    pmi_annotations: list[PMIAnnotation] = Field(default_factory=list)
    manufacturing_processes: list[ManufacturingProcess] = Field(default_factory=list)


# ── Assembly-Level Response ──────────────────────────────────────────────────


class AssemblyAnalysisResponse(BaseModel):
    request_id: str = Field(description="Unique request ID for correlation tracking")
    assembly_name: str
    file_name: str
    component_count: int
    unique_component_count: int = Field(0, description="Number of unique (deduplicated) components")
    total_volume_mm3: Optional[float] = Field(None, description="Total volume in mm³ (from components or top-level shape)")
    processing_time_seconds: Optional[float] = None
    pmi_available: bool = False
    pmi_annotations: list[PMIAnnotation] = Field(default_factory=list)
    manufacturing_processes: list[ManufacturingProcess] = Field(default_factory=list)
    components: list[ComponentAnalysis]


# ── Components-Only Response ─────────────────────────────────────────────────


class ComponentBasicInfo(BaseModel):
    name: str
    assembly_path: str = ""
    volume_mm3: Optional[float] = None
    surface_area_mm2: Optional[float] = None
    bounding_box: Optional[BoundingBox] = None
    error: Optional[str] = None


class ComponentsOnlyResponse(BaseModel):
    request_id: str = Field(description="Unique request ID for correlation tracking")
    assembly_name: str
    component_count: int
    components: list[ComponentBasicInfo]
    processing_time_seconds: float


# ── Async Job Response ───────────────────────────────────────────────────────


class JobStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class JobStatusResponse(BaseModel):
    job_id: str
    status: JobStatus
    progress: Optional[str] = None
    result: Optional[AssemblyAnalysisResponse] = None
    error: Optional[str] = None


# ── Health Check ─────────────────────────────────────────────────────────────


class HealthResponse(BaseModel):
    status: str
    uvnet_model_loaded: bool
    supabase_connected: bool
