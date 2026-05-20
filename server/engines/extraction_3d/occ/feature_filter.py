"""Post-classification feature filter.

Filters detected features based on the classified part type so that
only features relevant to the manufacturing domain are retained.
Also applies heuristic sanity checks (e.g., minimum depth-to-diameter
ratio for holes, minimum bend length for sheet metal bends).
"""

from __future__ import annotations

import logging
from typing import Optional

from .models import BoundingBox, FeatureDetail, FeatureType, PartType, ThicknessStats

logger = logging.getLogger(__name__)

# ── Valid feature types per part classification ──────────────────────────

# Sheet-metal feature set removed — FeatureType is locked to the 19 CNC
# values + UNKNOWN. If a sheet-metal part reaches this filter, it falls
# through to the empty allow-list and every detected feature is dropped.

_CNC_MILLING_FEATURES: set[FeatureType] = {
    FeatureType.THROUGH_HOLE,
    FeatureType.BLIND_HOLE,
    FeatureType.DRILLED_HOLE,
    FeatureType.COUNTERBORE,
    FeatureType.COUNTERSINK,
    FeatureType.POCKET,
    FeatureType.STEP,
    FeatureType.FILLET,
    FeatureType.CHAMFER,
    FeatureType.THREAD,
    FeatureType.BOSS,
    FeatureType.RIB,
    FeatureType.DRAFT,
    FeatureType.GROOVE,
    FeatureType.UNDERCUT,
    FeatureType.TAPERED_BORE,
}

_CNC_LATHE_FEATURES: set[FeatureType] = {
    FeatureType.THROUGH_HOLE,
    FeatureType.BLIND_HOLE,
    FeatureType.DRILLED_HOLE,
    FeatureType.COUNTERBORE,
    FeatureType.COUNTERSINK,
    FeatureType.CHAMFER,
    FeatureType.FILLET,
    FeatureType.BOSS,
    FeatureType.GROOVE,
    FeatureType.STEP,
    FeatureType.TAPERED_BORE,
    FeatureType.TAPERED_OD,
}

_CNC_LATHE_MILLING_FEATURES: set[FeatureType] = {
    FeatureType.THROUGH_HOLE,
    FeatureType.BLIND_HOLE,
    FeatureType.DRILLED_HOLE,
    FeatureType.COUNTERBORE,
    FeatureType.COUNTERSINK,
    FeatureType.POCKET,
    FeatureType.STEP,
    FeatureType.CHAMFER,
    FeatureType.FILLET,
    FeatureType.BOSS,
    FeatureType.GROOVE,
    FeatureType.UNDERCUT,
    FeatureType.TAPERED_BORE,
    FeatureType.TAPERED_OD,
}

# TUBE_PIPE classification disabled.
# _TUBE_PIPE_FEATURES: set[FeatureType] = {
#     FeatureType.THROUGH_HOLE,
#     FeatureType.COUNTERSINK,
#     FeatureType.CHAMFER,
#     FeatureType.FILLET,
#     FeatureType.POCKET,
# }

# Hardware parts are purchased/standard components — exclude sheet metal
# forming features which cannot appear on turned/ground/fastener stock.
_HARDWARE_FEATURES: set[FeatureType] = {
    FeatureType.THROUGH_HOLE,
    FeatureType.BLIND_HOLE,
    FeatureType.DRILLED_HOLE,
    FeatureType.COUNTERBORE,
    FeatureType.COUNTERSINK,
    FeatureType.POCKET,
    FeatureType.STEP,
    FeatureType.FILLET,
    FeatureType.CHAMFER,
    FeatureType.THREAD,
    FeatureType.BOSS,
    FeatureType.RIB,
    FeatureType.DRAFT,
    FeatureType.GROOVE,
    FeatureType.UNDERCUT,
    FeatureType.TAPERED_BORE,
}

_FEATURE_MAP: dict[PartType, set[FeatureType]] = {
    # Sheet-metal entry intentionally dropped — vocabulary is CNC-only.
    PartType.CNC_MILLING: _CNC_MILLING_FEATURES,
    PartType.CNC_LATHE: _CNC_LATHE_FEATURES,
    PartType.CNC_LATHE_MILLING: _CNC_LATHE_MILLING_FEATURES,
    # TUBE_PIPE classification disabled.
    # PartType.TUBE_PIPE: _TUBE_PIPE_FEATURES,
    PartType.HARDWARE: _HARDWARE_FEATURES,
}


# ── Heuristic sanity checks ─────────────────────────────────────────────

def _is_valid_bend(f: FeatureDetail, part_type: PartType) -> bool:
    """Filter false-positive bends (corner fillets vs. real forming bends)."""
    dims = f.dimensions or {}
    radius = dims.get("bend_radius_mm", 0)
    length = dims.get("bend_length_mm", 0)

    # A real sheet metal bend spans a significant length of the part.
    # Corner fillets are typically very short (< 10mm).
    if length < 10:
        return False

    # Bend radius should be reasonable for sheet metal (typically 0.5-50mm)
    if radius < 0.3 or radius > 100:
        return False

    return True


def _is_valid_hole(f: FeatureDetail) -> bool:
    """Filter shallow embosses/forms mistakenly detected as holes."""
    dims = f.dimensions or {}
    diameter = dims.get("diameter_mm", 0)
    depth = dims.get("depth_mm", 0)

    if diameter <= 0:
        return False

    # Depth-to-diameter ratio: real holes have ratio > 0.1 typically.
    # A Ø7mm "hole" at 0.95mm depth (ratio=0.136) is borderline.
    # A Ø4mm "hole" at 0.43mm depth (ratio=0.108) is likely an emboss.
    # Use 0.15 as threshold for blind holes; through holes are always valid.
    if f.feature_type == FeatureType.BLIND_HOLE:
        ratio = depth / diameter
        if ratio < 0.15:
            return False

    return True


def _is_valid_pocket(
    f: FeatureDetail,
    part_type: PartType,
    bbox: Optional[BoundingBox] = None,
) -> bool:
    """Filter false pockets on sheet metal and implausible deep pockets."""
    # Reject degenerate pockets with near-zero width or length (numerical
    # artefacts from face adjacency at sharp edges).
    dims = f.dimensions or {}
    w = dims.get("width_mm", 0)
    if 0 < w < 0.5:
        return False
    length = dims.get("length_mm", 0)
    if 0 < length < 0.5:
        return False

    # The feature recognizer already enforces depth ≤ dim_along_gn (the part
    # extent in the pocket's normal direction), so no additional depth guard
    # is needed here.  A naive min_dim check incorrectly rejects valid deep
    # pockets on parts whose narrowest axis is perpendicular to the pocket
    # depth direction (e.g., a 244×12.7×44mm bar with 29.5mm-deep slots).

    return True


def _is_valid_slot(
    f: FeatureDetail,
    part_type: PartType,
    thickness_stats: Optional[ThicknessStats] = None,
    bbox: Optional[BoundingBox] = None,
) -> bool:
    """Filter false slots on sheet metal parts.

    For sheet metal, a valid slot is a punched opening whose width
    is close to the sheet thickness (the cut goes through the full
    sheet).  Narrow side-wall faces (width << thickness) and very
    long edge walls are rejected.

    # TUBE_PIPE classification disabled — the tube_pipe branch below is
    # commented out.  Parts formerly classified as tube/pipe now route
    # through SHEET_METAL or CNC_MILLING logic.
    #
    # For tube_pipe, inner bore faces of rectangular/square tubes are
    # incorrectly detected as slots.  They are identified by a very small
    # depth-to-width ratio (depth ≈ wall thickness, width ≈ tube ID).
    # Real machined slots (keyways, access slots) have depth/width ≥ 0.1.
    """
    if part_type == PartType.SHEET_METAL:
        dims = f.dimensions or {}
        length = dims.get("length_mm", 0)
        width = dims.get("width_mm", 0)

        # Reject very long faces (edge walls / flanges)
        if length > 100:
            return False

        # Width should approximate sheet thickness
        if thickness_stats and thickness_stats.min_mm > 0:
            t = thickness_stats.min_mm
            if not (0.7 * t <= width <= 1.5 * t):
                return False
        else:
            # No thickness info — reject very narrow faces
            if width < 2:
                return False

    # TUBE_PIPE classification disabled — slot validation for tube/pipe
    # parts is no longer executed.
    # elif part_type == PartType.TUBE_PIPE:
    #     dims = f.dimensions or {}
    #     length = dims.get("length_mm", 0)
    #     depth = dims.get("depth_mm", 0)
    #     width = dims.get("width_mm", 0)
    #
    #     # Reject bore-face false positives: inner tube faces have a very
    #     # small depth-to-width ratio (depth ≈ wall thickness << tube ID).
    #     # Real machined slots (keyways, vents) have depth/width >= 0.1.
    #     if width > 0 and depth > 0 and depth / width < 0.1:
    #         return False
    #
    #     # Reject tube-profile false positives: the flat faces of a square/
    #     # rectangular tube run the full part length and are detected as
    #     # elongated recessed faces.  A real slot is always significantly
    #     # shorter than the part itself.
    #     if bbox is not None and length > 0:
    #         longest_dim = max(bbox.length, bbox.width, bbox.height)
    #         if longest_dim > 0 and length / longest_dim > 0.9:
    #             return False

    elif part_type == PartType.CNC_MILLING:
        dims = f.dimensions or {}
        length = dims.get("length_mm", 0)

        # Same full-length check for cnc_milling parts
        if bbox is not None and length > 0:
            longest_dim = max(bbox.length, bbox.width, bbox.height)
            if longest_dim > 0 and length / longest_dim > 0.9:
                return False

    return True


def _is_valid_blind_hole_for_sheet_metal(
    f: FeatureDetail,
    thickness_stats: Optional[ThicknessStats] = None,
) -> bool:
    """Blind holes on sheet metal are only valid if they are close to
    sheet thickness (countersink-like through punches)."""
    if not thickness_stats or thickness_stats.min_mm <= 0:
        return False
    dims = f.dimensions or {}
    depth = dims.get("depth_mm", 0)
    t = thickness_stats.min_mm
    # Depth should be close to sheet thickness (a real punch)
    return depth >= 0.5 * t


def _is_valid_chamfer(f: FeatureDetail) -> bool:
    """Reject spurious chamfers with implausible dimensions."""
    dims = f.dimensions or {}
    width = dims.get("width_mm", 0)
    if width <= 0 or width > 50:
        return False
    return True


def _is_valid_thread(f: FeatureDetail) -> bool:
    """Reject thread detections without diameter info."""
    dims = f.dimensions or {}
    diameter = dims.get("diameter_mm", 0)
    return diameter > 0


def _is_valid_boss(f: FeatureDetail) -> bool:
    """Reject boss detections without reasonable dimensions."""
    dims = f.dimensions or {}
    diameter = dims.get("diameter_mm", 0)
    height = dims.get("height_mm", 0)
    return diameter > 0 and height > 0


def _is_valid_draft(f: FeatureDetail) -> bool:
    """Reject draft angles outside expected manufacturing range."""
    dims = f.dimensions or {}
    angle = dims.get("draft_angle_deg", 0)
    return 0.5 <= angle <= 30


def _is_valid_rib(
    f: FeatureDetail,
    bbox: Optional[BoundingBox] = None,
) -> bool:
    """Reject false ribs whose height matches the part's thinnest axis.

    On flat bars/plates the short edge faces (aspect > 5, small area) pass
    the rib detector, but their height equals the sheet/plate thickness.
    A real stiffening rib protrudes beyond the part's minimum dimension.
    """
    if bbox is not None:
        dims = f.dimensions or {}
        height = dims.get("height_mm", 0)
        min_dim = min(bbox.length, bbox.width, bbox.height)
        if height > 0 and min_dim > 0:
            # If rib height is within 20 % of the thinnest axis it is
            # just a through-thickness edge face, not a real rib.
            if abs(height - min_dim) / min_dim < 0.2:
                return False
    return True


# ── Main filter entry point ─────────────────────────────────────────────

def filter_features_by_part_type(
    features: list[FeatureDetail],
    part_type: PartType,
    thickness_stats: Optional[ThicknessStats] = None,
    bbox: Optional[BoundingBox] = None,
) -> list[FeatureDetail]:
    """
    Filter features to only those valid for the detected part type,
    then apply heuristic sanity checks on dimensions.

    Args:
        features: All detected features (merged rule-based + UV-Net)
        part_type: The classified part type
        thickness_stats: Wall thickness info (used for bend validation)

    Returns:
        Filtered list of FeatureDetail objects
    """
    allowed = _FEATURE_MAP.get(part_type)
    if allowed is None:
        # Unknown part type — return all features unfiltered
        return features

    filtered: list[FeatureDetail] = []
    removed_type = 0
    removed_heuristic = 0

    for f in features:
        # Step 1: Type filter — is this feature type valid for the part type?
        if f.feature_type not in allowed:
            removed_type += 1
            continue

        # Step 2: Heuristic dimension checks
        keep = True

        if f.feature_type in (FeatureType.BLIND_HOLE, FeatureType.THROUGH_HOLE):
            keep = _is_valid_hole(f)

        elif f.feature_type == FeatureType.POCKET:
            keep = _is_valid_pocket(f, part_type, bbox)

        elif f.feature_type == FeatureType.CHAMFER:
            keep = _is_valid_chamfer(f)

        elif f.feature_type == FeatureType.THREAD:
            keep = _is_valid_thread(f)

        elif f.feature_type == FeatureType.BOSS:
            keep = _is_valid_boss(f)

        elif f.feature_type == FeatureType.RIB:
            keep = _is_valid_rib(f, bbox)

        elif f.feature_type == FeatureType.DRAFT:
            keep = _is_valid_draft(f)

        if not keep:
            removed_heuristic += 1
            continue

        filtered.append(f)

    total_removed = removed_type + removed_heuristic
    if total_removed > 0:
        logger.info(
            "Feature filter (%s): kept %d, removed %d "
            "(type-mismatch=%d, heuristic=%d) from %d total",
            part_type.value,
            len(filtered),
            total_removed,
            removed_type,
            removed_heuristic,
            len(features),
        )

    return filtered
