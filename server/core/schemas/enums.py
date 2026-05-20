"""String enums shared across all engines.

Every value is a lowercase snake_case string — the catalog, Supabase, the
front-end, and CSV exports all rely on this. Never change a string value
without auditing all call sites.
"""
from __future__ import annotations

import enum


class PartType(str, enum.Enum):
    """High-level manufacturing family for one component."""

    SHEET_METAL       = "sheet_metal"
    CNC_MILLING       = "cnc_milling"
    CNC_LATHE         = "cnc_lathe"
    CNC_LATHE_MILLING = "cnc_lathe_milling"
    TUBE_PIPE         = "tube_pipe"
    HARDWARE          = "hardware"
    UNKNOWN           = "unknown"


class FeatureType(str, enum.Enum):
    """Atomic geometric features recognised on a STEP body.

    Controlled vocabulary (19 values + UNKNOWN sentinel) — authoritative
    for the agentic engine, the KB, and the cost engine. Keep aligned
    with :class:`server.engines.extraction_3d.occ.models.FeatureType`.
    """

    # Hole-making
    THROUGH_HOLE  = "through_hole"
    BLIND_HOLE    = "blind_hole"
    DRILLED_HOLE  = "drilled_hole"
    COUNTERBORE   = "counterbore"
    COUNTERSINK   = "countersink"
    TAPERED_BORE  = "tapered_bore"
    # Milling
    POCKET        = "pocket"
    STEP          = "step"
    FILLET        = "fillet"
    CHAMFER       = "chamfer"
    THREAD        = "thread"
    BOSS          = "boss"
    RIB           = "rib"
    DRAFT         = "draft"
    UNDERCUT      = "undercut"
    GROOVE        = "groove"
    # Turning
    LATHE_OD      = "lathe_od"
    TAPERED_OD    = "tapered_od"
    # Facing
    FACE          = "face"
    # Sentinel
    UNKNOWN       = "unknown"


class ProcessCategory(str, enum.Enum):
    """Coarse routing buckets used by the cost engine."""

    CUTTING      = "cutting"
    HOLE_MAKING  = "hole_making"
    FORMING      = "forming"
    JOINING      = "joining"
    FINISHING    = "finishing"
    MACHINING    = "machining"
    PROCUREMENT  = "procurement"


class ProcessType(str, enum.Enum):
    """Specific manufacturing operations a routing row can carry."""

    # Cutting
    LASER_CUTTING      = "laser_cutting"
    PLASMA_CUTTING     = "plasma_cutting"
    WATERJET_CUTTING   = "waterjet_cutting"
    BLANKING           = "blanking"
    SHEARING           = "shearing"
    NIBBLING           = "nibbling"
    FINE_BLANKING      = "fine_blanking"
    # Hole-making
    PUNCHING           = "punching"
    DRILLING           = "drilling"
    REAMING            = "reaming"
    BORING             = "boring"
    LANCING            = "lancing"
    PERFORATING        = "perforating"
    SPOT_DRILLING      = "spot_drilling"
    COUNTERBORING      = "counterboring"
    COUNTERSINKING     = "countersinking"
    # Forming
    PRESS_BRAKE_BENDING = "press_brake_bending"
    COINING            = "coining"
    EMBOSSING          = "embossing"
    BRIDGE_FORMING     = "bridge_forming"
    JOGGLE_FORMING     = "joggle_forming"
    HEMMING            = "hemming"
    BEADING            = "beading"
    CURLING            = "curling"
    FLANGING           = "flanging"
    DEEP_DRAWING       = "deep_drawing"
    STRETCH_FORMING    = "stretch_forming"
    HYDROFORMING       = "hydroforming"
    ROLL_FORMING       = "roll_forming"
    STAMPING           = "stamping"
    SPINNING           = "spinning"
    # Joining
    TIG_WELDING        = "tig_welding"
    MIG_WELDING        = "mig_welding"
    SPOT_WELDING       = "spot_welding"
    SEAM_WELDING       = "seam_welding"
    RIVETING           = "riveting"
    CLINCHING          = "clinching"
    FASTENING          = "fastening"
    ASSEMBLY_FIT_UP    = "assembly_fit_up"
    # Finishing
    DEBURRING          = "deburring"
    ANODIZING          = "anodizing"
    POWDER_COATING     = "powder_coating"
    PAINTING           = "painting"
    PLATING            = "plating"
    PASSIVATION        = "passivation"
    POLISHING          = "polishing"
    GRINDING           = "grinding"
    # CNC machining
    CNC_MILLING        = "cnc_milling"
    CNC_TURNING        = "cnc_turning"
    CNC_FINISHING      = "cnc_finishing"
    TAPPING            = "tapping"
    THREAD_MILLING     = "thread_milling"
    EDM                = "edm"
    FACING             = "facing"
    FACE_MILLING       = "face_milling"
    GROOVING           = "grooving"
    KNURLING           = "knurling"
    PARTING            = "parting"
    # Tube
    TUBE_LASER_CUTTING = "tube_laser_cutting"
    TUBE_BENDING       = "tube_bending"
    # General / auxiliary
    PROCUREMENT        = "procurement"
    RAW_MATERIAL_PREP  = "raw_material_prep"
    BAR_STOCK_PREP     = "bar_stock_prep"
    SURFACE_TREATMENT  = "surface_treatment"
    SETUP              = "setup"
    TOOL_CHANGE        = "tool_change"
    INSPECTION         = "inspection"


class SurfaceType(str, enum.Enum):
    """OCC surface kinds — straight from BRep_Tool::Surface."""

    PLANE    = "plane"
    CYLINDER = "cylinder"
    CONE     = "cone"
    SPHERE   = "sphere"
    TORUS    = "torus"
    BSPLINE  = "bspline"
    OTHER    = "other"


class PMIType(str, enum.Enum):
    """STEP-AP242 PMI annotation kinds."""

    DIMENSIONAL    = "dimensional"
    GEOMETRIC      = "geometric"
    SURFACE_FINISH = "surface_finish"
    DATUM          = "datum"
    NOTE           = "note"


class JobStatus(str, enum.Enum):
    """Async analysis job status (used by polling endpoints)."""

    PENDING   = "pending"
    RUNNING   = "running"
    COMPLETED = "completed"
    FAILED    = "failed"
