"""Part type classification using geometry heuristics, component name keywords,
and UV-Net face labels.

Classifies components into one of 6 part types (sheet_metal, cnc_milling,
cnc_lathe, cnc_lathe_milling, tube_pipe, hardware) using
weighted scoring across multiple geometry metrics and keyword matching
on the component name / description.
"""

from __future__ import annotations

import logging
import math
from typing import Optional

from .models import (
    BoundingBox,
    FaceTypeCounts,
    FeatureDetail,
    FeatureType,
    PartType,
    ThicknessStats,
)

logger = logging.getLogger(__name__)


# ── Name-based keyword patterns ──────────────────────────────────────────────
# Each entry maps a PartType to (keywords, strong_keywords).
# A keyword hit adds a moderate boost; a strong keyword hit adds a large boost.
_NAME_KEYWORDS: dict[PartType, tuple[list[str], list[str]]] = {
    PartType.HARDWARE: (
        # generic
        ["bolt", "screw", "nut", "washer", "rivet", "pin", "fastener",
         "insert", "spacer", "standoff", "bushing", "bearing",
         "retaining ring", "snap ring", "e-clip", "dowel",
         "stud", "anchor", "clamp", "clip", "grommet", "eyebolt",
         "thumbscrew", "setscrew", "cap screw", "machine screw",
         "heli-coil", "helicoil", "rivnut", "clinch",
         "shcs", "bhcs", "fhcs", "hhcs",  # socket / button / flat / hex head cap screw
         "socket head", "button head", "flat head", "hex head",
         "soc hd", "btn hd", "flt hd", "hex hd",
         "lock washer", "flat washer", "spring washer", "split washer",
         "lk wash", "fl wash", "spr wash", "spl wash",
         "flange nut", "jam nut", "castle nut", "wing nut", "t-nut",
         "fl nut", "cstle nut", "wng nut",
         "nyloc", "nylock", "prevailing torque",
         "cotter", "clevis", "shoulder bolt", "shoulder screw",
         "shld bolt", "shld screw",
         "o-ring", "seal", "gasket", "spring",
         # short-form / abbreviation patterns
         "blt", "scr", "wsh", "riv", "fstnr", "fsnr",
         "hdw", "hdwr", "hw_", "_hw",
         "spcr", "stdf", "brng", "bshg",
         "ret ring", "ret rng", "snp rng",
         "cpscr", "mscr", "mach scr"],
        # strong — unambiguous
        ["bolt", "screw", "nut", "washer", "rivet", "dowel pin",
         "shcs", "bhcs", "fhcs", "hhcs",
         "blt", "scr", "wsh", "hdwr", "hdw", "fstnr"],
    ),
    PartType.SHEET_METAL: (
        ["bracket", "panel", "plate", "shield", "enclosure", "cover",
         "shroud", "baffle", "duct", "tray", "chassis", "door",
         "sheet", "skin", "wrapper", "guard", "deflector",
         "mounting plate", "base plate", "gusset",
         # short-form
         "brkt", "bkt", "pnl", "plt", "shld", "encl", "cvr",
         "mtg plate", "mtg plt", "base plt", "gsst"],
        ["sheet metal", "sheetmetal", "sm_", "sht mtl", "shtmtl",
         "sht met", "s/m"],
    ),
    PartType.CNC_MILLING: (
        ["block", "manifold", "housing", "body", "adapter",
         "fixture", "jig", "mount", "rail", "slide",
         "machined", "milled", "billet",
         # short-form
         "blk", "hsg", "hsng", "adpt", "adptr",
         "fxtr", "mnt", "mch", "mchd"],
        ["cnc", "machined", "milled", "billet",
         "mchd", "mch'd"],
    ),
    # TUBE_PIPE classification disabled — parts formerly classified as tube/pipe
    # now route through SHEET_METAL or CNC_MILLING logic.
    # PartType.TUBE_PIPE: (
    #     ["tube", "pipe", "conduit", "hose", "tubing", "nipple",
    #      "elbow", "tee", "coupling", "union", "ferrule",
    #      # short-form
    #      "tb", "pp", "cnduit", "cplg", "cpln"],
    #     ["tube", "pipe", "tubing",
    #      "tb_", "_tb"],
    # ),
    PartType.CNC_LATHE: (
        ["shaft", "spindle", "axle", "rod", "pin", "roller",
         "piston", "sleeve", "collet", "arbor", "mandrel",
         "turned", "lathe", "mill-turn", "turn-mill",
         "collar", "hub", "pulley", "stud",
         # short-form
         "shft", "sft", "spndl", "slv", "rllr", "pstn",
         "cllt", "mndrl"],
        ["shaft", "turned", "lathe", "turning",
         "mill-turn", "turn-mill", "millturn", "turnmill",
         "shft", "sft"],
    ),
    PartType.WELDMENT: (
        ["weldment", "weld assembly", "welded assembly",
         "weld assy", "welded assy", "bonded assembly",
         "bonded assy", "solvent bond", "bonded",
         "wldmnt", "wldmt"],
        ["weldment", "wldmnt"],
    ),
}


def _score_name_keywords(name: str) -> dict[PartType, float]:
    """Return per-PartType bonus scores derived from the component name."""
    bonuses: dict[PartType, float] = {}
    if not name:
        return bonuses
    name_lower = name.lower()
    # Apply keyword matching for hardware AND weldments — both are
    # name-driven (weldments aren't a single-body geometric pattern, they
    # are an assembly-level concept). Other part types rely on geometry.
    for pt in [PartType.HARDWARE, PartType.WELDMENT]:
        keywords, strong_keywords = _NAME_KEYWORDS[pt]
        bonus = 0.0
        for kw in strong_keywords:
            if kw in name_lower:
                bonus = max(bonus, 6.0)
                break
        if bonus == 0.0:
            for kw in keywords:
                if kw in name_lower:
                    bonus = max(bonus, 3.0)
                    break
        if bonus > 0.0:
            bonuses[pt] = bonus
    return bonuses


def classify_part(
    volume_mm3: float,
    surface_area_mm2: float,
    bbox: BoundingBox,
    face_counts: FaceTypeCounts,
    thickness_stats: Optional[ThicknessStats],
    features: list[FeatureDetail],
    component_name: str = "",
    component_description: str = "",
    has_closed_cross_section: bool = False,
    rotational_symmetry: Optional[dict] = None,
) -> tuple[PartType, float, list[dict]]:
    """
    Classify a component into a part type using geometry heuristics and
    keyword matching on the component name and STEP product description.

    Returns:
        (best_type, confidence, candidates) where candidates is a list
        of {type, confidence} for top-N results.
    """
    scores: dict[PartType, float] = {}

    # Name-based bonuses (from both name and STEP description)
    name_bonuses = _score_name_keywords(component_name)
    desc_bonuses = _score_name_keywords(component_description)
    # Merge: take the max bonus per part type from either source
    all_bonus_pts = set(name_bonuses) | set(desc_bonuses)
    merged_bonuses = {
        pt: max(name_bonuses.get(pt, 0.0), desc_bonuses.get(pt, 0.0))
        for pt in all_bonus_pts
    }

    for pt in PartType:
        if pt == PartType.UNKNOWN:
            continue
        scores[pt] = _score_part_type(
            pt, volume_mm3, surface_area_mm2, bbox, face_counts,
            thickness_stats, features, has_closed_cross_section,
            rotational_symmetry,
        ) + merged_bonuses.get(pt, 0.0)

    # Normalize scores
    total = sum(scores.values())
    if total > 0:
        for pt in scores:
            scores[pt] /= total
    else:
        return PartType.UNKNOWN, 0.0, []

    # Sort by score descending
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    best_type, best_score = ranked[0]

    # Build candidates list (top-3)
    candidates = [
        {"type": pt.value, "confidence": round(conf, 4)}
        for pt, conf in ranked[:3]
        if conf > 0.05
    ]

    # If best score is below threshold, mark as unknown
    if best_score < 0.15:
        return PartType.UNKNOWN, best_score, candidates

    return best_type, round(best_score, 4), candidates


def _score_part_type(
    part_type: PartType,
    volume: float,
    surface_area: float,
    bbox: BoundingBox,
    face_counts: FaceTypeCounts,
    thickness: Optional[ThicknessStats],
    features: list[FeatureDetail],
    has_closed_cross_section: bool = False,
    rotational_symmetry: Optional[dict] = None,
) -> float:
    """Compute a raw score for a given part type."""

    bbox_vol = bbox.length * bbox.width * bbox.height
    vol_ratio = volume / bbox_vol if bbox_vol > 0 else 0
    dims = sorted([bbox.length, bbox.width, bbox.height])
    min_dim, mid_dim, max_dim = dims[0], dims[1], dims[2]
    aspect_ratio = max_dim / min_dim if min_dim > 0 else 0
    flatness = min_dim / max_dim if max_dim > 0 else 0

    total_faces = face_counts.total or 1
    plane_frac = face_counts.plane / total_faces
    cyl_frac = face_counts.cylinder / total_faces
    bspline_frac = face_counts.bspline / total_faces
    cone_frac = face_counts.cone / total_faces
    torus_frac = face_counts.torus / total_faces

    # Feature counts
    hole_count = sum(
        f.count for f in features
        if f.feature_type in {
            FeatureType.THROUGH_HOLE, FeatureType.BLIND_HOLE,
            FeatureType.COUNTERBORE, FeatureType.COUNTERSINK,
        }
    )
    pocket_count = sum(f.count for f in features if f.feature_type == FeatureType.POCKET)
    # BEND removed from FeatureType vocab — sheet-metal classification is
    # out of scope for this CNC-only feature set. Forcing 0 disables the
    # sheet-metal classification boost in the heuristics below.
    bend_count = 0
    fillet_count = sum(f.count for f in features if f.feature_type == FeatureType.FILLET)
    # Large fillets (radius >= 3mm) are edge rounds typical of CNC machined
    # parts, not sheet metal.
    large_fillet_count = sum(
        f.count for f in features
        if f.feature_type == FeatureType.FILLET
        and (f.dimensions or {}).get("radius_mm", 0) >= 3.0
    )
    draft_count = sum(f.count for f in features if f.feature_type == FeatureType.DRAFT)
    thread_count = sum(f.count for f in features if f.feature_type == FeatureType.THREAD)
    boss_count = sum(f.count for f in features if f.feature_type == FeatureType.BOSS)
    step_count = sum(f.count for f in features if f.feature_type == FeatureType.STEP)
    chamfer_count = sum(f.count for f in features if f.feature_type == FeatureType.CHAMFER)

    # Off-axis hole/thread count: features whose axis is NOT aligned with
    # the dominant (longest) bounding-box axis.  For a turned part, the
    # lathe spindle axis runs along the longest dimension.
    _HOLE_THREAD_TYPES = {
        FeatureType.THROUGH_HOLE, FeatureType.BLIND_HOLE,
        FeatureType.COUNTERBORE, FeatureType.COUNTERSINK,
        FeatureType.THREAD,
    }
    # Determine dominant axis direction from bbox
    _dims_ax = [(bbox.length, 0), (bbox.width, 1), (bbox.height, 2)]
    _dims_ax.sort(key=lambda x: x[0], reverse=True)
    _dominant_idx = _dims_ax[0][1]
    _dominant_dir = [0.0, 0.0, 0.0]
    _dominant_dir[_dominant_idx] = 1.0

    def _is_off_axis(feat: FeatureDetail) -> bool:
        ax = feat.dimensions.get("axis")
        if not ax or len(ax) != 3:
            return False
        # Dot product with dominant axis — if < 0.7 (~45°), off-axis
        dot = abs(ax[0] * _dominant_dir[0] + ax[1] * _dominant_dir[1] + ax[2] * _dominant_dir[2])
        return dot < 0.7

    off_axis_hole_count = sum(
        f.count for f in features
        if f.feature_type in _HOLE_THREAD_TYPES and _is_off_axis(f)
    )

    is_uniform_thickness = thickness.is_uniform if thickness else False
    mean_thickness = thickness.mean_mm if thickness else 0

    score = 0.0

    # ------------------------------------------------------------------
    # SHEET_METAL classification is deactivated — all sheet-metal scoring
    # logic below is commented out so that no part can be classified as
    # sheet_metal via geometry heuristics.
    # ------------------------------------------------------------------
    # if part_type == PartType.SHEET_METAL:
    #     # Flat, uniform thickness, possibly with bends
    #     if flatness < 0.1:
    #         # A machined plate (e.g. 30 mm thick Al tooling plate) is also
    #         # geometrically flat.  Gate the strong +3 bonus on the shortest
    #         # bbox dimension being within sheet-stock gauge range (≤ 13 mm)
    #         # OR on the thickness being uniform throughout.  A thick part with
    #         # non-uniform thickness is a machined solid, not a sheet blank.
    #         if min_dim <= 13 or is_uniform_thickness:
    #             score += 3.0
    #         else:
    #             score += 1.0
    #     elif flatness < 0.2:
    #         score += 1.5
    #
    #     if is_uniform_thickness:
    #         score += 2.5
    #     if mean_thickness > 0 and mean_thickness < 10:
    #         # The mean-thickness signal is only meaningful when the overall
    #         # part is also thin (min bbox dim ≤ 13 mm) or uniformly thick.
    #         # On a machined plate the ray-cast mean just samples the thinnest
    #         # pocket floors, giving a misleadingly small value.
    #         if min_dim <= 13 or is_uniform_thickness:
    #             score += 2.0
    #         else:
    #             score += 0.5
    #
    #     if bend_count > 0:
    #         score += 2.0 * min(bend_count, 5)
    #
    #     # Penalize tube-like parts: elongated profile with bends at
    #     # corners and high cylinder fraction is a formed tube, not
    #     # a sheet-metal bracket/panel.
    #     # A closed rectangular tube needs exactly 3–4 corner bends.
    #     # Parts with >4 bends are complex open sections (channels,
    #     # hat-sections, frame rails) — keep them as sheet metal.
    #     if aspect_ratio > 10 and cyl_frac > 0.3 and 2 <= bend_count <= 4:
    #         score -= 3.0 * min(bend_count, 4)
    #
    #     if plane_frac > 0.4:
    #         score += 1.0
    #
    #     # Very low volume ratio strongly suggests sheet metal (thin shell)
    #     if vol_ratio < 0.15:
    #         score += 2.5
    #     elif vol_ratio < 0.25:
    #         score += 1.5
    #     # High volume ratio means solid block, not thin sheet
    #     elif vol_ratio > 0.5:
    #         score -= 2.0
    #
    #     # High cylinder fraction from bends/formed features is common
    #     if cyl_frac > 0.2 and plane_frac > 0.3:
    #         score += 1.0
    #
    #     # Penalize features not typical of sheet metal
    #     if boss_count > 0:
    #         score -= 0.5
    #     if bspline_frac > 0.2:
    #         score -= 1.0
    #     # Penalize tiny parts — likely hardware, not sheet metal
    #     if volume < 500 and max_dim < 15:
    #         score -= 3.0
    #     # Non-uniform, thick parts are machined solids, not sheet metal.
    #     # Also catches parts where the coefficient of variation (std/mean)
    #     # exceeds 0.8 — extreme thickness spread regardless of mean value
    #     # is a machined-plate signature (deep pockets, facing steps).
    #     if thickness and not is_uniform_thickness:
    #         _cv = thickness.std_dev_mm / thickness.mean_mm if thickness.mean_mm > 0 else 0
    #         if mean_thickness > 10 or _cv > 0.8:
    #             score -= 1.5
    #         # Very thick parts (min dimension > 50 mm) are machined solids,
    #         # not sheet metal blanks — penalise heavily.
    #         if min_dim > 50:
    #             score -= 3.0
    #     # Fillets on a part with no bends indicate CNC machining, not
    #     # sheet metal.  Only penalize for large fillets (≥ 3mm radius)
    #     # which are edge rounds on machined blocks/plates.
    #     if large_fillet_count > 0 and bend_count == 0:
    #         score -= 2.0 * min(large_fillet_count, 5)
    #     # Cross-section topology: a fully enclosed cross-section (tube)
    #     # is not a flat sheet metal part.
    #     if has_closed_cross_section:
    #         score -= 3.0
    #
    #     # Deep pockets (depth > 1.5 × mean thickness) are machined features,
    #     # not sheet-metal punchings. Penalise when several are present.
    #     if thickness:
    #         _deep_pocket_count = sum(
    #             f.count for f in features
    #             if f.feature_type == FeatureType.POCKET
    #             and (f.dimensions or {}).get("depth_mm", 0) > thickness.mean_mm * 1.5
    #         )
    #         if _deep_pocket_count > 2:
    #             score -= 2.0 * min(_deep_pocket_count, 5)

    if part_type == PartType.CNC_MILLING:
        # Solid block with pockets, holes, slots
        if 0.3 < vol_ratio < 0.85:
            score += 2.0
        elif vol_ratio < 0.15:
            # Very low fill ratio is unlikely for CNC (more likely sheet metal)
            score -= 2.0
        if hole_count + pocket_count > 3:
            score += 2.5
        if pocket_count > 0:
            score += 1.5
        if plane_frac > 0.3:
            score += 0.5
        if fillet_count > 0:
            score += 0.5
        # Steps, bosses, and chamfers are machining features
        if step_count > 0:
            score += 1.0
        if boss_count > 0:
            score += 1.0
        if chamfer_count > 0:
            score += 0.5
        # Highly variable wall thickness (CV > 0.5) means machined pockets /
        # steps removed material from a solid blank — strong CNC indicator.
        if thickness and not is_uniform_thickness:
            _cv = thickness.std_dev_mm / thickness.mean_mm if thickness.mean_mm > 0 else 0
            if _cv > 0.5:
                score += 1.5
        # Penalize sheet metal indicators
        if bend_count > 0:
            score -= 2.0
        if is_uniform_thickness and flatness < 0.1:
            score -= 1.5
        # Penalize tiny parts — likely hardware, not CNC
        if volume < 500 and max_dim < 15:
            score -= 3.0

    # TUBE_PIPE classification disabled — scoring block commented out.
    # elif part_type == PartType.TUBE_PIPE:
    #     # Hollow cylindrical / formed tube profile
    #     if cyl_frac > 0.4:
    #         score += 3.0
    #     elif cyl_frac > 0.3:
    #         score += 1.5
    #     if aspect_ratio > 3:
    #         score += 2.0
    #     if aspect_ratio > 10:
    #         score += 2.0  # very elongated — strong tube signal
    #     if is_uniform_thickness:
    #         score += 1.5
    #     # Check near-cylindrical profile (hollow elongated shape)
    #     if vol_ratio < 0.5 and cyl_frac > 0.3:
    #         score += 1.5
    #     # Square/rectangular tubes: high aspect, extreme flatness,
    #     # bends at corners, roughly equal cyl and plane fractions.
    #     # Only award this bonus when the cross-section is confirmed closed —
    #     # a 2-bend C/U-channel passes the same geometric tests but is open.
    #     if (has_closed_cross_section and aspect_ratio > 10 and flatness < 0.05
    #             and 2 <= bend_count <= 4 and cyl_frac > 0.25):
    #         score += 4.0
    #     # Bends in elongated parts are tube-forming, not sheet bends.
    #     # Only applies when the cross-section is confirmed closed; an open
    #     # section with bends is a channel/frame rail, not a tube.
    #     if has_closed_cross_section and bend_count > 0 and aspect_ratio > 5 and bend_count <= 4:
    #         score += 1.5 * min(bend_count, 4)
    #     if plane_frac > 0.5:
    #         score -= 1.0
    #     # Cross-section topology is the most reliable tube/open-section signal.
    #     # A closed cross-section (all wires form loops) at every slice along the
    #     # length confirms a tube or pipe regardless of bend count or face types.
    #     # An open cross-section (any free wire end) confirms an open sheet metal
    #     # profile — strongly penalise tube_pipe in that case.
    #     if has_closed_cross_section:
    #         score += 5.0
    #     elif aspect_ratio > 2.5:
    #         # Elongated but open section — not a tube
    #         score -= 5.0

    elif part_type == PartType.HARDWARE:
        # Small, often radially symmetric, threads
        # ── Size signals ──
        if max_dim < 50:
            score += 2.0
        elif max_dim < 100:
            score += 1.0

        # Very small volume is a strong hardware signal
        if volume < 500:
            score += 3.0
        elif volume < 2000:
            score += 1.5

        if thread_count > 0:
            score += 3.0
        if cyl_frac > 0.3:
            score += 1.0
        # Standard dimensions check (M3-M24 bolt heads)
        if 2.5 <= max_dim <= 60 and cyl_frac > 0.2:
            score += 0.5

        # ── Countersink / counterbore on small parts → screw/bolt head ──
        countersink_count = sum(
            f.count for f in features
            if f.feature_type in {FeatureType.COUNTERSINK, FeatureType.COUNTERBORE}
        )
        if countersink_count > 0 and max_dim < 30:
            score += 2.5

        # ── Washer pattern: flat disc + single hole + very small ──
        if (flatness < 0.15 and hole_count == 1
                and max_dim < 25 and volume < 1000):
            score += 4.0

        # ── Nut pattern: squat + central hole + small ──
        if (0.2 < flatness < 0.6 and hole_count > 0
                and max_dim < 20 and volume < 500):
            score += 3.0

        # ── Simple geometry on tiny parts ──
        if total_faces < 20 and max_dim < 15:
            score += 1.5
        # Steps and bosses are machining features, not typical of
        # fasteners / off-the-shelf hardware.
        if step_count > 0:
            score -= 2.0
        if boss_count > 0:
            score -= 1.5

    elif part_type == PartType.CNC_LATHE:
        # Rotational symmetry detected via cross-section area comparison
        rot_sym = rotational_symmetry or {}
        best_count = rot_sym.get("best_count", 0)
        best_axis = rot_sym.get("best_axis")

        # Guard: a turned part has a circular cross-section perpendicular to
        # the spindle axis.  The rotational-symmetry metric is unreliable on
        # flat elongated bars (all slices give similar edge-length totals).
        # Gate the symmetry bonus on the two perpendicular bbox dims being
        # close (perp_ratio ≥ 0.5 → the cross-section is roughly circular).
        if best_axis is not None and best_count > 2:
            if best_axis == "x":
                _perp = sorted([bbox.width, bbox.height])
            elif best_axis == "y":
                _perp = sorted([bbox.length, bbox.height])
            else:  # z
                _perp = sorted([bbox.length, bbox.width])
            _perp_ratio = _perp[0] / _perp[1] if _perp[1] > 0 else 0
            if _perp_ratio < 0.5:
                best_count = 0  # not a circular cross-section → no lathe bonus

        if best_count > 3:
            score += 5.0
        elif best_count > 2:
            score += 2.0
        if plane_frac > 0.5:
            score -= 1.0
        if bend_count > 0:
            score -= 2.0

    elif part_type == PartType.WELDMENT:
        # Weldments are assembly-level parts; geometry is secondary to the name
        # keywords (handled in _score_name_keywords). Give a small constant
        # floor so a name-keyword hit isn't competing against 0.0 while every
        # other type accrues positive geometry score.
        score += 1.5
        if plane_frac > 0.3:        # cut-stock / machined interface pads
            score += 1.0
        elif plane_frac > 0.15:
            score += 0.5
        if bspline_frac + torus_frac > 0.1:  # weld-bead / fillet topology
            score += 1.0
        if total_faces > 50:        # multi-body welded assemblies expose many faces
            score += 0.5

    elif part_type == PartType.CNC_LATHE_MILLING:
        # Circular cross-section guard: the two bbox dims perpendicular to the
        # spindle axis must be nearly equal, confirming a circular outer profile.
        # The spindle can be along any axis, so we check BOTH adjacent dim pairs
        # (min/mid and mid/max) and take the larger ratio — this handles both:
        #   • Long cylinders/shafts: X≈Y small, Z long → min/mid ≈ 1
        #   • Short cups/discs:      X≈Y large, Z small → mid/max ≈ 1
        # A rectangular milling block fails both pairs.
        cross_ratio = max(
            min_dim / mid_dim if mid_dim > 0 else 0,
            mid_dim / max_dim if max_dim > 0 else 0,
        )

        # Rotational symmetry corroborates a circular cross-section.
        rot_sym = rotational_symmetry or {}
        best_count = rot_sym.get("best_count", 0)

        if cross_ratio > 0.8:
            if best_count >= 5:
                score += 5.0
            elif best_count >= 3:
                score += 2.0
            # Bonus for genuine turned surfaces (not just cylinders from holes)
            if cone_frac > 0.05:
                score += 0.5
            if torus_frac > 0.05:
                score += 0.5
            # Milling feature bonuses — these are what separates lathe_milling
            # from pure lathe
            if pocket_count > 0:
                score += 2.0
            if off_axis_hole_count > 0:
                score += 1.5
            if hole_count > 0:
                score += 0.5
            if step_count > 0:
                score += 1.0
            if chamfer_count > 0:
                score += 0.5

        if bend_count > 0:
            score -= 3.0
        if plane_frac > 0.7:
            score -= 2.0

    return max(score, 0.0)


def maybe_promote_lathe(
    part_type: PartType,
    features: list[FeatureDetail],
    bbox: BoundingBox,
) -> PartType:
    """Promote CNC_LATHE → CNC_LATHE_MILLING when milling features are present.

    Called after feature recognition but before feature filtering, so that
    milling features (which would be filtered out under CNC_LATHE) are still
    visible for the promotion check.
    """
    if part_type != PartType.CNC_LATHE:
        return part_type

    # Determine dominant (spindle) axis from bbox longest dimension
    _dims_ax = [(bbox.length, 0), (bbox.width, 1), (bbox.height, 2)]
    _dims_ax.sort(key=lambda x: x[0], reverse=True)
    _dominant_idx = _dims_ax[0][1]
    _dominant_dir = [0.0, 0.0, 0.0]
    _dominant_dir[_dominant_idx] = 1.0

    def _is_off_axis(feat: FeatureDetail) -> bool:
        ax = feat.dimensions.get("axis")
        if not ax or len(ax) != 3:
            return False
        dot = abs(ax[0] * _dominant_dir[0] + ax[1] * _dominant_dir[1] + ax[2] * _dominant_dir[2])
        return dot < 0.7

    _MILLING_TYPES = {
        FeatureType.POCKET, FeatureType.STEP,
    }
    _HOLE_TYPES = {
        FeatureType.THROUGH_HOLE, FeatureType.BLIND_HOLE,
        FeatureType.COUNTERBORE, FeatureType.COUNTERSINK,
    }

    has_milling_features = any(
        f.feature_type in _MILLING_TYPES for f in features
    )
    has_off_axis_holes = any(
        f.feature_type in _HOLE_TYPES and _is_off_axis(f) for f in features
    )

    if has_milling_features or has_off_axis_holes:
        return PartType.CNC_LATHE_MILLING

    return PartType.CNC_LATHE
