"""Rule-based feature recognition engine (Engine A).

Detects manufacturing features from B-Rep topology using
deterministic geometry heuristics.  High-confidence for simple
features like holes, chamfers, fillets; lower for complex shapes.
"""

from __future__ import annotations

import logging
import math
import uuid
from typing import Optional

from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.BRepGProp import BRepGProp
from OCP.BRepLProp import BRepLProp_SLProps
from OCP.GeomAbs import (
    GeomAbs_BSplineCurve,
    GeomAbs_Circle,
    GeomAbs_Cone,
    GeomAbs_Cylinder,
    GeomAbs_Plane,
    GeomAbs_Torus,
)
from OCP.GProp import GProp_GProps
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_REVERSED, TopAbs_WIRE
from OCP.TopExp import TopExp, TopExp_Explorer
from OCP.BRepTools import BRepTools
from OCP.TopoDS import TopoDS, TopoDS_Shape

from .models import FeatureDetail, FeatureType, PartType, Point3D, ThicknessStats

logger = logging.getLogger(__name__)


def _fid() -> str:
    return f"rb_{uuid.uuid4().hex[:8]}"


def _normalize_axis(v: tuple | list | None) -> list[float] | None:
    """Normalize a 3-D direction vector to unit length."""
    if v is None:
        return None
    x, y, z = float(v[0]), float(v[1]), float(v[2])
    mag = math.sqrt(x * x + y * y + z * z)
    if mag < 1e-10:
        return None
    return [round(x / mag, 6), round(y / mag, 6), round(z / mag, 6)]


def _gp_vec_to_list(v) -> list[float] | None:
    """Normalize an OCP gp_Vec / gp_Dir to a Python unit vector."""
    mag = v.Magnitude()
    if mag < 1e-10:
        return None
    return [round(v.X() / mag, 6), round(v.Y() / mag, 6), round(v.Z() / mag, 6)]


def _compute_face_persistent_id(face_info: dict) -> str:
    """Compute a persistent geometric hash ID for a face.

    The ID combines a FreeCAD-style face index (Face1, Face2, …) with a
    SHA-256 geometric fingerprint.  The fingerprint is based on surface
    type, area, centroid, bounding box and surface-specific parameters
    (radius, normal, semi-angle, etc.) that survive re-imports of the
    same STEP file.  This makes the ID suitable for linking detected
    features to FreeCAD PATH workbench Base Geometry entries.
    """
    import hashlib

    parts = [face_info.get("type", "unknown")]

    # Area (rounded to avoid floating-point noise)
    area = face_info.get("area_mm2", 0)
    parts.append(f"A={area:.2f}")

    # Centroid
    center = _face_center(face_info["face"])
    if center:
        parts.append(f"C=({center.x:.2f},{center.y:.2f},{center.z:.2f})")

    # Surface-specific geometric parameters
    ftype = face_info.get("type")
    if ftype == "cylinder":
        parts.append(f"R={face_info.get('radius_mm', 0):.4f}")
        ax = face_info.get("axis", (0, 0, 1))
        parts.append(f"AX=({ax[0]:.4f},{ax[1]:.4f},{ax[2]:.4f})")
        parts.append(f"O={face_info.get('orientation', 'forward')}")
    elif ftype == "plane":
        n = face_info.get("normal", (0, 0, 1))
        parts.append(f"N=({n[0]:.4f},{n[1]:.4f},{n[2]:.4f})")
        parts.append(f"O={face_info.get('orientation', 'forward')}")
    elif ftype == "cone":
        parts.append(f"SA={face_info.get('semi_angle_deg', 0):.4f}")
        ax = face_info.get("axis", (0, 0, 1))
        parts.append(f"AX=({ax[0]:.4f},{ax[1]:.4f},{ax[2]:.4f})")
    elif ftype == "torus":
        parts.append(f"R={face_info.get('major_radius_mm', 0):.4f}")
        parts.append(f"r={face_info.get('minor_radius_mm', 0):.4f}")
    elif ftype == "sphere":
        parts.append(f"R={face_info.get('radius_mm', 0):.4f}")

    # Bounding box for additional disambiguation
    try:
        from OCP.Bnd import Bnd_Box
        from OCP.BRepBndLib import BRepBndLib
        bb = Bnd_Box()
        BRepBndLib.Add_s(face_info["face"], bb)
        x1, y1, z1, x2, y2, z2 = bb.Get()
        parts.append(
            f"BB=({x1:.2f},{y1:.2f},{z1:.2f},{x2:.2f},{y2:.2f},{z2:.2f})"
        )
    except Exception:
        pass

    h = hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]

    # FreeCAD uses 1-based face indices (Face1, Face2, …)
    fc_idx = face_info.get("index", 0) + 1
    return f"Face{fc_idx}_{h}"


def _face_center(face) -> Optional[Point3D]:
    """Compute centroid of a face via surface properties."""
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(face, props)
    c = props.CentreOfMass()
    return Point3D(x=round(c.X(), 3), y=round(c.Y(), 3), z=round(c.Z(), 3))


def _axes_aligned(axis1: tuple, axis2: tuple, tol: float = 0.95) -> bool:
    """Check if two axis direction vectors are aligned (parallel or anti-parallel).

    Args:
        axis1: (X, Y, Z) direction vector
        axis2: (X, Y, Z) direction vector
        tol: absolute dot-product threshold (0.95 ≈ 18° tolerance)
    """
    dot = abs(axis1[0] * axis2[0] + axis1[1] * axis2[1] + axis1[2] * axis2[2])
    return dot > tol


def _feature_volume_check(feature: FeatureDetail, total_volume_mm3: float) -> bool:
    """Reject features whose implied volume exceeds a fraction of the part volume.

    Catches false detections where e.g. a large cylinder covers most of the
    part and is incorrectly labelled as a blind hole.
    Returns True if the feature passes (is plausible), False to reject.
    """
    if total_volume_mm3 <= 0:
        return True
    dims = feature.dimensions or {}
    feat_vol = 0.0
    diameter = dims.get("diameter_mm", 0)
    depth = dims.get("depth_mm", 0)
    height = dims.get("height_mm", 0)
    if diameter > 0 and (depth > 0 or height > 0):
        r = diameter / 2
        h = depth if depth > 0 else height
        feat_vol = math.pi * r * r * h  # cylinder approximation

    if feat_vol <= 0:
        return True
    # A single feature shouldn't exceed 60% of total part volume
    return feat_vol < 0.6 * total_volume_mm3


# ═══════════════════════════════════════════════════════════════════════════
# Per-face adjacency helper
# ═══════════════════════════════════════════════════════════════════════════

def _build_face_adjacency(shape: TopoDS_Shape, face_infos: list[dict]) -> dict[int, set[int]]:
    """
    Build face adjacency map: face_index → set of adjacent face indices.
    Two faces are adjacent if they share at least one edge.

    Uses TopTools_IndexedMapOfShape for stable face identity instead of
    Python hash() which can differ between OCP wrapper instances of the
    same underlying C++ TopoDS_Face.
    """
    from OCP.TopTools import (
        TopTools_IndexedDataMapOfShapeListOfShape,
        TopTools_IndexedMapOfShape,
    )

    # Build a stable face-index map using the OCCT indexed map
    face_map = TopTools_IndexedMapOfShape()
    for fi in face_infos:
        face_map.Add(fi["face"])

    # Map from OCCT 1-based map index → our 0-based face_info index
    occt_idx_to_fi: dict[int, int] = {}
    for fi in face_infos:
        occt_idx = face_map.FindIndex(fi["face"])
        if occt_idx > 0:
            occt_idx_to_fi[occt_idx] = fi["index"]

    edge_face_map = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(shape, TopAbs_EDGE, TopAbs_FACE, edge_face_map)

    adjacency: dict[int, set[int]] = {fi["index"]: set() for fi in face_infos}

    for i in range(1, edge_face_map.Extent() + 1):
        face_list = edge_face_map.FindFromIndex(i)
        indices = []
        for f in face_list:
            occt_idx = face_map.FindIndex(f)
            if occt_idx > 0 and occt_idx in occt_idx_to_fi:
                indices.append(occt_idx_to_fi[occt_idx])
        for a in indices:
            for b in indices:
                if a != b:
                    adjacency[a].add(b)

    return adjacency


# ── Adjacency chain-following ────────────────────────────────────────────

# Face types that act as "transition" surfaces — blend radii, chamfer cones,
# etc. that sit between a feature's primary face and its adjacent planar
# cap/base.  When one of these is the *only* neighbour, we hop through it
# to reach the actual structural face on the other side.
_TRANSITION_TYPES = {"torus", "cone"}


def _follow_through_transitions(
    start_index: int,
    adjacency: dict[int, set[int]],
    face_infos: list[dict],
    *,
    target_type: str = "plane",
    max_hops: int = 2,
) -> list[dict]:
    """Follow adjacency through transition faces (torus/cone) to find target faces.

    Starting from *start_index* (excluded from results), walk up to *max_hops*
    through torus and cone faces to find faces of *target_type*.

    Returns a list of face_info dicts that match the target type.
    """
    info_by_idx = {fi["index"]: fi for fi in face_infos}
    visited: set[int] = {start_index}
    frontier: set[int] = set(adjacency.get(start_index, set()))
    found: list[dict] = []

    for _hop in range(max_hops):
        next_frontier: set[int] = set()
        for idx in frontier:
            if idx in visited:
                continue
            visited.add(idx)
            fi = info_by_idx.get(idx)
            if fi is None:
                continue
            if fi["type"] == target_type:
                found.append(fi)
            elif fi["type"] in _TRANSITION_TYPES:
                # Keep walking through this transition face
                next_frontier.update(adjacency.get(idx, set()))
        frontier = next_frontier

    return found


# ═══════════════════════════════════════════════════════════════════════════
# Hole Detection
# ═══════════════════════════════════════════════════════════════════════════

def _detect_holes(
    face_infos: list[dict],
    adjacency: dict[int, set[int]],
    bbox_height: float,
    claimed_faces: set[int] | None = None,
) -> list[FeatureDetail]:
    """Detect through-holes, blind holes, counterbores, and countersinks."""
    from OCP.gp import gp_Pnt, gp_Vec

    features: list[FeatureDetail] = []
    # Sort ascending by radius so inner (smaller) cylinders are always processed
    # before outer (larger) cylinders — this ensures counterbore inner/outer
    # assignment is always correct regardless of face ordering in the STEP file.
    cylindrical = sorted(
        [f for f in face_infos if f["type"] == "cylinder"],
        key=lambda f: f.get("radius_mm", 0),
    )
    used_indices: set[int] = set()
    _claimed = claimed_faces or set()
    plane_index_set: set[int] = {f["index"] for f in face_infos if f["type"] == "plane"}
    fi_area: dict[int, float] = {f["index"]: f.get("area_mm2", 0.0) for f in face_infos}

    def _plane_proj(plane_face, axis):
        """Project a plane face's centre onto an axis direction."""
        ca = BRepAdaptor_Surface(plane_face)
        cu = (ca.FirstUParameter() + ca.LastUParameter()) / 2
        cv = (ca.FirstVParameter() + ca.LastVParameter()) / 2
        cp = gp_Pnt(); _du = gp_Vec(); _dv = gp_Vec()
        ca.D1(cu, cv, cp, _du, _dv)
        return cp.X() * axis[0] + cp.Y() * axis[1] + cp.Z() * axis[2]

    def _hole_depth_span(feature_face_indices, axis, direct_caps=None):
        """Compute hole depth as span between the two extreme reachable
        planes along *axis*.  Searches through transition faces from every
        face in *feature_face_indices* and includes *direct_caps*.
        """
        all_planes: dict[int, dict] = {}
        for fi_idx in feature_face_indices:
            for p in _follow_through_transitions(
                fi_idx, adjacency, face_infos, target_type="plane"
            ):
                all_planes[p["index"]] = p
        if direct_caps:
            for p in direct_caps:
                all_planes[p["index"]] = p
        if len(all_planes) < 2:
            return None
        projections = [_plane_proj(p["face"], axis) for p in all_planes.values()]
        span = max(projections) - min(projections)
        return span if span > 0.01 else None

    for cf in cylindrical:
        if cf["index"] in used_indices or cf["index"] in _claimed:
            continue

        radius = cf.get("radius_mm", 0)
        if radius < 0.1:
            continue

        # Orientation check: inner cylinders (REVERSED) are holes;
        # outer cylinders (FORWARD) are bosses/shafts — skip them.
        orientation = cf.get("orientation", "forward")
        if orientation == "forward":
            continue

        # Skip degenerate arc fragments (< 60°) — real holes can appear as
        # complementary partial arcs (e.g. two 180° halves) in STEP exports where
        # a seam plane splits the cylindrical bore into separate half-cylinder faces.
        is_closed = cf.get("is_closed_u", False)
        u_range = cf.get("u_range")
        if not is_closed:
            if u_range is None:
                continue
            u_span = abs(u_range[1] - u_range[0])
            if u_span < math.pi / 3:  # less than 60° → arc fragment, skip
                continue
        else:
            u_span = 2 * math.pi

        cf_axis = cf.get("axis", (0, 0, 1))

        # Circumferential-wall guard: skip cylinders that are too shallow relative
        # to their radius.  Real drilled/milled holes have height ≥ 30% of radius.
        # C-shape pocket walls at large radii have h/r far below this threshold.
        _arc_len_h = radius * u_span
        _cyl_h = cf["area_mm2"] / _arc_len_h if _arc_len_h > 0 else 0.0
        if _cyl_h < radius * 0.30:
            continue

        # For partial arcs (60°–270°), pre-claim the complementary arc(s) that
        # together complete the same bore/hole (same radius + axis, spans sum to 360°).
        # This prevents each half from being detected as a separate hole feature.
        #
        # KEY GUARD: require shared adjacent faces (adjacency intersection).
        # Two halves of the SAME bore share their seam plane, cap, and/or drill
        # cone in the adjacency graph.  Two different holes at the same radius
        # (e.g. 12 bolt-circle holes of equal diameter) have completely disjoint
        # adjacency sets — so this prevents claiming all same-radius holes as one.
        if not is_closed and u_span < math.pi * 1.5:
            _arc_len_cf = radius * u_span
            _h_cf = cf["area_mm2"] / _arc_len_cf if _arc_len_cf > 0 else 0.0
            _cf_adj = adjacency.get(cf["index"], set())
            for _pf in face_infos:
                if (_pf["index"] == cf["index"]
                        or _pf["index"] in used_indices
                        or _pf["index"] in _claimed):
                    continue
                if _pf["type"] != "cylinder" or _pf.get("orientation") != "reversed":
                    continue
                if abs(_pf.get("radius_mm", 0) - radius) > radius * 0.01 + 0.1:
                    continue
                if not _axes_aligned(cf_axis, _pf.get("axis", (0, 0, 1)), tol=0.99):
                    continue
                _pf_range = _pf.get("u_range")
                if _pf_range is None:
                    continue
                _span_p = abs(_pf_range[1] - _pf_range[0])
                if abs((u_span + _span_p) - 2 * math.pi) > 0.35:
                    continue
                _arc_len_p = radius * _span_p
                _h_p = _pf["area_mm2"] / _arc_len_p if _arc_len_p > 0 else 0.0
                if abs(_h_p - _h_cf) > max(_h_cf * 0.15, 0.5):
                    continue
                # Only claim arcs that share at least one SMALL adjacent face with cf.
                # Large shared faces (OD surface, disc faces) are shared by ALL bores
                # of the same radius — they don't prove two arcs belong to the same bore.
                # Seam planes and drill cones are small (area << bore_cross × 10).
                _pf_adj = adjacency.get(_pf["index"], set())
                _bore_cross = math.pi * radius * radius
                _shared = {fi for fi in (_cf_adj & _pf_adj)
                           if fi_area.get(fi, 0.0) < _bore_cross * 10}
                if not _shared:
                    continue
                used_indices.add(_pf["index"])

        # Check adjacent faces to determine hole type
        adj_indices = adjacency.get(cf["index"], set())
        adj_faces = [f for f in face_infos if f["index"] in adj_indices]

        # Count planar caps (bottom faces of blind holes).
        # Upper bound: no larger than a full disc of the same radius.
        # Lower bound: ≥ 35% of a full disc — annular ring pocket floors
        # (e.g. C-shape pocket floors adjacent to large bore walls) have
        # area << π×r² and would be false caps.
        _min_cap_area = math.pi * radius * radius * 0.35
        planar_caps = [
            f for f in adj_faces
            if f["type"] == "plane"
            and _min_cap_area <= f["area_mm2"] < math.pi * radius * radius * 1.3
        ]

        # Check for coaxial larger cylinder (counterbore)
        # In real counterbores, the larger cylinder may not be directly
        # adjacent to the smaller one — an annular planar shelf separates
        # them.  Search both direct adjacency AND one-hop through planes.

        cf_origin = cf.get("axis_origin")  # axis line position for coaxiality check

        def _axis_perp_dist(o_a, o_b, d):
            """Perpendicular distance between two parallel lines (origins o_a, o_b; direction d)."""
            dx, dy, dz = o_b[0]-o_a[0], o_b[1]-o_a[1], o_b[2]-o_a[2]
            dot = dx*d[0] + dy*d[1] + dz*d[2]
            px, py, pz = dx-dot*d[0], dy-dot*d[1], dz-dot*d[2]
            return math.sqrt(px*px + py*py + pz*pz)

        def _coaxial_with_cf(f):
            """True if f's cylinder axis line coincides with cf's axis line (within 2mm)."""
            if cf_origin is None:
                return True  # no position data → can't filter, allow
            f_origin = f.get("axis_origin")
            if f_origin is None:
                return True
            return _axis_perp_dist(cf_origin, f_origin, cf_axis) < 2.0

        def _find_coaxial_larger_cyls(seed_adj_faces, search_depth=1):
            """Find larger coaxial reversed cylinders, optionally through planar shelves."""
            found = []
            def _is_full_cylinder(f):
                """Return True if f spans at least 60° — a real bore wall, not a sliver."""
                if f.get("is_closed_u", False):
                    return True
                ur = f.get("u_range")
                return ur is not None and abs(ur[1] - ur[0]) >= math.pi / 3

            # Direct adjacency
            for f in seed_adj_faces:
                if (f["type"] == "cylinder"
                    and f["index"] not in used_indices
                    and f["index"] not in _claimed
                    and abs(f.get("radius_mm", 0) - radius) > 0.5
                    and f.get("radius_mm", 0) < radius * 5  # counterbore max 5× inner
                    and f.get("orientation", "forward") == "reversed"
                    and _axes_aligned(cf_axis, f.get("axis", (0, 0, 1)))
                    and _is_full_cylinder(f)
                    and _coaxial_with_cf(f)):
                    found.append(f)

            if found or search_depth <= 0:
                return found

            # One-hop through adjacent planar faces (the annular shelf)
            for pf in seed_adj_faces:
                if pf["type"] != "plane":
                    continue
                # The shelf plane area should be smaller than a reasonable
                # annular ring (we don't want to walk through the big stock face)
                if pf["area_mm2"] > math.pi * (radius * 5) ** 2:
                    continue
                shelf_adj_indices = adjacency.get(pf["index"], set())
                shelf_adj_faces = [fi for fi in face_infos if fi["index"] in shelf_adj_indices]
                for f in shelf_adj_faces:
                    if (f["type"] == "cylinder"
                        and f["index"] != cf["index"]
                        and f["index"] not in used_indices
                        and f["index"] not in _claimed
                        and f.get("radius_mm", 0) > radius + 0.5
                        and f.get("radius_mm", 0) < radius * 5  # counterbore max 5× inner
                        and f.get("orientation", "forward") == "reversed"
                        and _axes_aligned(cf_axis, f.get("axis", (0, 0, 1)))
                        and _is_full_cylinder(f)
                        and _coaxial_with_cf(f)):
                        # The connecting plane must be consistent with a real
                        # annular shelf (area ≈ π×(r_o²-r_i²)).  A large disc
                        # face shared by unrelated parallel bores would be many
                        # times larger than the expected shelf.  Allow 15× for
                        # seam-split shelves and minor geometry variation.
                        # When a candidate is rejected, suppress its index so the
                        # outer bore arc is not later re-detected as a countersink.
                        _r_o = f.get("radius_mm", 0)
                        _exp = math.pi * abs(_r_o ** 2 - radius ** 2)
                        if _exp > 0 and pf["area_mm2"] > _exp * 15:
                            used_indices.add(f["index"])
                            continue
                        found.append(f)
            return found

        coaxial_cyls = _find_coaxial_larger_cyls(adj_faces)

        # Check for adjacent cone (countersink) — verify coaxiality
        adj_cones = [
            f for f in adj_faces
            if f["type"] == "cone"
            and f["index"] not in used_indices
            and f["index"] not in _claimed
            and _axes_aligned(cf_axis, f.get("axis", (0, 0, 1)))
        ]

        if coaxial_cyls:
            # Counterbore: two coaxial cylinders at different radii
            larger = max(coaxial_cyls, key=lambda f: f.get("radius_mm", 0))

            # Depth-ratio guard: the outer bore step must be at least 8% as
            # deep as the inner bore.  A very shallow outer bore relative to a
            # deep inner bore indicates a false pairing — two unrelated bores
            # at different positions connected through a shared disc face.
            # (E.g. Ø19.05mm h=57mm inner / Ø21.082mm h=4.32mm outer → 7.6%.)
            _lg_ur2 = larger.get("u_range")
            _lg_span2 = abs(_lg_ur2[1] - _lg_ur2[0]) if _lg_ur2 else 2 * math.pi
            _lg_arc2 = larger.get("radius_mm", 0) * _lg_span2
            _lg_h2 = larger["area_mm2"] / _lg_arc2 if _lg_arc2 > 0 else 0.0
            if _lg_h2 < _cyl_h * 0.08:
                coaxial_cyls = []

        if coaxial_cyls:
            larger = max(coaxial_cyls, key=lambda f: f.get("radius_mm", 0))
            used_indices.add(cf["index"])
            used_indices.add(larger["index"])

            # If the outer (larger) cylinder is a partial arc (seam-split bore),
            # pre-claim its complementary arc so it is not re-processed as a
            # separate feature (e.g. false COUNTERSINK from the unclaimed half).
            _lg_radius = larger.get("radius_mm", 0)
            _lg_ur = larger.get("u_range")
            _lg_is_closed = larger.get("is_closed_u", False)
            if not _lg_is_closed and _lg_ur is not None:
                _lg_span = abs(_lg_ur[1] - _lg_ur[0])
                if _lg_span < math.pi * 1.5:
                    _lg_adj = adjacency.get(larger["index"], set())
                    _lg_axis = larger.get("axis", (0, 0, 1))
                    _lg_arc_len = _lg_radius * _lg_span
                    _lg_h = larger["area_mm2"] / _lg_arc_len if _lg_arc_len > 0 else 0.0
                    _lg_cross = math.pi * _lg_radius * _lg_radius
                    for _pf2 in face_infos:
                        if (_pf2["index"] == larger["index"]
                                or _pf2["index"] in used_indices
                                or _pf2["index"] in _claimed):
                            continue
                        if _pf2["type"] != "cylinder" or _pf2.get("orientation") != "reversed":
                            continue
                        if abs(_pf2.get("radius_mm", 0) - _lg_radius) > _lg_radius * 0.01 + 0.1:
                            continue
                        if not _axes_aligned(_lg_axis, _pf2.get("axis", (0, 0, 1)), tol=0.99):
                            continue
                        _pf2_ur = _pf2.get("u_range")
                        if _pf2_ur is None:
                            continue
                        _pf2_span = abs(_pf2_ur[1] - _pf2_ur[0])
                        if abs((_lg_span + _pf2_span) - 2 * math.pi) > 0.35:
                            continue
                        _pf2_arc = _lg_radius * _pf2_span
                        _pf2_h = _pf2["area_mm2"] / _pf2_arc if _pf2_arc > 0 else 0.0
                        if abs(_pf2_h - _lg_h) > max(_lg_h * 0.15, 0.5):
                            continue
                        _pf2_adj = adjacency.get(_pf2["index"], set())
                        _shared2 = {fi for fi in (_lg_adj & _pf2_adj)
                                    if fi_area.get(fi, 0.0) < _lg_cross * 10}
                        if not _shared2:
                            continue
                        used_indices.add(_pf2["index"])

            # Collect face_indices including any shelf planes between the two cylinders
            cb_face_indices = [cf["index"], larger["index"]]
            for pf in adj_faces:
                if pf["type"] == "plane" and larger["index"] in adjacency.get(pf["index"], set()):
                    cb_face_indices.append(pf["index"])
                    used_indices.add(pf["index"])

            # Compute counterbore depth using span between reachable planes
            cb_depth = _hole_depth_span(cb_face_indices, cf_axis, planar_caps)
            cb_dims = {
                "inner_diameter_mm": round(radius * 2, 3),
                "outer_diameter_mm": round(larger.get("radius_mm", 0) * 2, 3),
                "axis": [round(cf_axis[0], 6), round(cf_axis[1], 6), round(cf_axis[2], 6)],
            }
            if cb_depth is not None:
                cb_dims["depth_mm"] = round(cb_depth, 3)

            features.append(FeatureDetail(
                feature_id=_fid(),
                feature_type=FeatureType.COUNTERBORE,
                confidence=0.85,
                source="rule_based",
                dimensions=cb_dims,
                location=_face_center(cf["face"]),
                face_indices=cb_face_indices,
                orientation=_normalize_axis(cf_axis),
                key_face_id=_compute_face_persistent_id(cf),
            ))

        elif adj_cones and not planar_caps:
            # Cones present with no flat bottom cap.
            # Classify each adjacent coaxial cone as above (entry) or below (drill point).
            # A cone at the entry (countersink) is adjacent to a planar outer surface face.
            # A cone at the bottom (drill point) has no adjacent plane other than back
            # through the cylinder itself.
            # NOTE: when planar_caps IS non-empty, we skip this block so the hole
            # falls through to the BLIND_HOLE handler — entry chamfers on flat-bottom
            # holes should not cause a COUNTERSINK classification.
            countersink_cones = []
            drill_point_cones = []
            for cone in adj_cones:
                cone_adj = adjacency.get(cone["index"], set()) - {cf["index"]}
                if cone_adj & plane_index_set:
                    countersink_cones.append(cone)
                else:
                    drill_point_cones.append(cone)

            if drill_point_cones:
                # Drill-point cone at bottom (no adjacent plane) → DRILLED_HOLE.
                # This check runs BEFORE countersink_cones so that a drilled hole
                # with an entry chamfer is never mis-classified as COUNTERSINK.
                cone = drill_point_cones[0]
                used_indices.add(cf["index"])
                used_indices.add(cone["index"])
                dh_depth = _hole_depth_span(
                    [cf["index"], cone["index"]], cf_axis, planar_caps
                )
                if dh_depth is None:
                    _reachable = _follow_through_transitions(
                        cf["index"], adjacency, face_infos, target_type="plane"
                    )
                    if planar_caps:
                        _reachable = list(planar_caps) + [
                            p for p in _reachable if p["index"] not in {c["index"] for c in planar_caps}
                        ]
                    if _reachable:
                        _opening = _reachable[0]
                        _op = _plane_proj(_opening["face"], cf_axis)
                        _cone_a = BRepAdaptor_Surface(cone["face"])
                        _v0 = _cone_a.FirstVParameter()
                        _v1 = _cone_a.LastVParameter()
                        _u_mid = (_cone_a.FirstUParameter() + _cone_a.LastUParameter()) / 2
                        _p0 = gp_Pnt(); _p1 = gp_Pnt()
                        _du2 = gp_Vec(); _dv2 = gp_Vec()
                        _cone_a.D1(_u_mid, _v0, _p0, _du2, _dv2)
                        _cone_a.D1(_u_mid, _v1, _p1, _du2, _dv2)
                        _proj0 = _p0.X()*cf_axis[0] + _p0.Y()*cf_axis[1] + _p0.Z()*cf_axis[2]
                        _proj1 = _p1.X()*cf_axis[0] + _p1.Y()*cf_axis[1] + _p1.Z()*cf_axis[2]
                        _near_proj = _proj0 if abs(_proj0 - _op) < abs(_proj1 - _op) else _proj1
                        dh_depth = abs(_near_proj - _op)
                circumference = 2 * math.pi * radius
                dh_dims = {
                    "diameter_mm": round(radius * 2, 3),
                    "drill_angle_deg": round(cone.get("semi_angle_deg", 59) * 2, 1),
                    "axis": [round(cf_axis[0], 6), round(cf_axis[1], 6), round(cf_axis[2], 6)],
                }
                if dh_depth is not None:
                    dh_dims["depth_mm"] = round(dh_depth, 3)
                features.append(FeatureDetail(
                    feature_id=_fid(),
                    feature_type=FeatureType.DRILLED_HOLE,
                    confidence=0.85,
                    source="rule_based",
                    dimensions=dh_dims,
                    perimeter_mm=round(circumference, 3),
                    location=_face_center(cf["face"]),
                    face_indices=[cf["index"], cone["index"]],
                    orientation=_normalize_axis(cf_axis),
                    key_face_id=_compute_face_persistent_id(cf),
                ))

            elif countersink_cones:
                # Cone at the entry (adjacent to part surface) → COUNTERSINK
                # Real countersinks have semi-angles of 30°-50° (60°-100° included angle)
                valid_cones = [
                    c for c in countersink_cones
                    if 25 <= abs(c.get("semi_angle_deg", 0)) <= 55
                ]
                cone = valid_cones[0] if valid_cones else countersink_cones[0]
                used_indices.add(cf["index"])
                used_indices.add(cone["index"])
                # Depth = span between reachable planes on both sides.
                # If only one plane is reachable (cone is a dead end), measure
                # from that plane to the far end of the cone along the axis.
                cs_depth = _hole_depth_span(
                    [cf["index"], cone["index"]], cf_axis, planar_caps
                )
                if cs_depth is None:
                    reachable = []
                    for fi_idx in [cf["index"], cone["index"]]:
                        reachable.extend(_follow_through_transitions(
                            fi_idx, adjacency, face_infos, target_type="plane"
                        ))
                    if planar_caps:
                        reachable.extend(planar_caps)
                    if reachable:
                        opening = reachable[0]
                        op = _plane_proj(opening["face"], cf_axis)
                        cone_a = BRepAdaptor_Surface(cone["face"])
                        v0 = cone_a.FirstVParameter()
                        v1 = cone_a.LastVParameter()
                        u_mid = (cone_a.FirstUParameter() + cone_a.LastUParameter()) / 2
                        p0 = gp_Pnt(); p1 = gp_Pnt()
                        _du = gp_Vec(); _dv = gp_Vec()
                        cone_a.D1(u_mid, v0, p0, _du, _dv)
                        cone_a.D1(u_mid, v1, p1, _du, _dv)
                        proj0 = p0.X()*cf_axis[0] + p0.Y()*cf_axis[1] + p0.Z()*cf_axis[2]
                        proj1 = p1.X()*cf_axis[0] + p1.Y()*cf_axis[1] + p1.Z()*cf_axis[2]
                        near_proj = proj0 if abs(proj0 - op) < abs(proj1 - op) else proj1
                        cs_depth = abs(near_proj - op)
                cs_dims = {
                    "diameter_mm": round(radius * 2, 3),
                    "countersink_angle_deg": cone.get("semi_angle_deg", 45) * 2,
                    "axis": [round(cf_axis[0], 6), round(cf_axis[1], 6), round(cf_axis[2], 6)],
                }
                if cs_depth is not None:
                    cs_dims["depth_mm"] = round(cs_depth, 3)
                features.append(FeatureDetail(
                    feature_id=_fid(),
                    feature_type=FeatureType.COUNTERSINK,
                    confidence=0.85,
                    source="rule_based",
                    dimensions=cs_dims,
                    location=_face_center(cf["face"]),
                    face_indices=[cf["index"], cone["index"]],
                    orientation=_normalize_axis(cf_axis),
                    key_face_id=_compute_face_persistent_id(cf),
                ))

        elif len(planar_caps) == 0:
            # No directly adjacent planar caps — but check if caps are
            # reachable through transition faces (fillets/chamfers at the
            # hole opening).
            indirect_caps = [
                f for f in _follow_through_transitions(
                    cf["index"], adjacency, face_infos, target_type="plane"
                )
                if f["area_mm2"] < math.pi * radius * radius * 1.3
            ]
            if indirect_caps:
                # Blind hole with fillet/chamfer at opening
                used_indices.add(cf["index"])
                circumference = 2 * math.pi * radius
                # Depth = span between reachable planes on both sides
                span_depth = _hole_depth_span([cf["index"]], cf_axis)
                if span_depth is not None:
                    depth = span_depth
                else:
                    u_range = cf.get("u_range")
                    arc_len = radius * abs(u_range[1] - u_range[0]) if u_range else circumference
                    depth = cf["area_mm2"] / arc_len if arc_len > 0 else 0
                # Claim indirect cap faces so pocket detector won't
                # re-detect them as pocket floors.
                cap_indices = [ic["index"] for ic in indirect_caps]
                for ci in cap_indices:
                    used_indices.add(ci)
                features.append(FeatureDetail(
                    feature_id=_fid(),
                    feature_type=FeatureType.BLIND_HOLE,
                    confidence=0.85,
                    source="rule_based",
                    dimensions={
                        "diameter_mm": round(radius * 2, 3),
                        "depth_mm": round(depth, 3),
                        "axis": [round(cf_axis[0], 6), round(cf_axis[1], 6), round(cf_axis[2], 6)],
                    },
                    perimeter_mm=round(circumference, 3),
                    location=_face_center(cf["face"]),
                    face_indices=[cf["index"]] + cap_indices,
                    orientation=_normalize_axis(cf_axis),
                    key_face_id=_compute_face_persistent_id(cf),
                ))
            else:
                # Through-hole: cylinder truly open on both ends.
                # Guard: any adjacent REVERSED plane that *encloses* this
                # cylinder (i.e. is not merely passed through) indicates a
                # pocket wall, not a drilled through-hole.
                # Topology-first: if the cylinder edge sits on an inner wire
                # of the plane, the plane has a matching hole and does not
                # close the bore.  Area ratio (≥ 5× hole cross-section) is
                # kept as a fallback for degenerate STEP files that lack
                # proper inner-wire topology.
                _hole_cross = math.pi * radius * radius
                _blocked = False
                for _af in adj_faces:
                    if _af["type"] != "plane" or _af.get("orientation") != "reversed":
                        continue
                    if _is_through_hole_in_floor(_af["face"], cf["face"]):
                        continue  # plane has matching hole — not a cap
                    if _af["area_mm2"] >= _hole_cross * 5.0:
                        continue  # large surrounding plane — not a cap
                    _blocked = True
                    break
                if _blocked:
                    continue
                used_indices.add(cf["index"])
                circumference = 2 * math.pi * radius
                u_range = cf.get("u_range")
                if u_range:
                    u_span = abs(u_range[1] - u_range[0])
                    arc_len = radius * u_span
                else:
                    arc_len = circumference
                depth = cf["area_mm2"] / arc_len if arc_len > 0 else 0
                features.append(FeatureDetail(
                    feature_id=_fid(),
                    feature_type=FeatureType.THROUGH_HOLE,
                    confidence=0.9,
                    source="rule_based",
                    dimensions={
                        "diameter_mm": round(radius * 2, 3),
                        "depth_mm": round(depth, 3),
                        "axis": [round(cf_axis[0], 6), round(cf_axis[1], 6), round(cf_axis[2], 6)],
                    },
                    perimeter_mm=round(circumference, 3),
                    location=_face_center(cf["face"]),
                    face_indices=[cf["index"]],
                    orientation=_normalize_axis(cf_axis),
                    key_face_id=_compute_face_persistent_id(cf),
                ))

        elif len(planar_caps) >= 1:
            # Blind hole: cylinder with a bottom cap
            used_indices.add(cf["index"])
            circumference = 2 * math.pi * radius
            # Depth = span between reachable planes on both sides
            span_depth = _hole_depth_span([cf["index"]], cf_axis, planar_caps)
            if span_depth is not None:
                depth = span_depth
            else:
                u_range = cf.get("u_range")
                arc_len = radius * abs(u_range[1] - u_range[0]) if u_range else circumference
                depth = cf["area_mm2"] / arc_len if arc_len > 0 else 0
            # Claim bottom cap faces so pocket detector won't re-detect them
            cap_indices = [pc["index"] for pc in planar_caps]
            for ci in cap_indices:
                used_indices.add(ci)
            features.append(FeatureDetail(
                feature_id=_fid(),
                feature_type=FeatureType.BLIND_HOLE,
                confidence=0.85,
                source="rule_based",
                dimensions={
                    "diameter_mm": round(radius * 2, 3),
                    "depth_mm": round(depth, 3),
                    "axis": [round(cf_axis[0], 6), round(cf_axis[1], 6), round(cf_axis[2], 6)],
                },
                perimeter_mm=round(circumference, 3),
                location=_face_center(cf["face"]),
                face_indices=[cf["index"]] + cap_indices,
                orientation=_normalize_axis(cf_axis),
                key_face_id=_compute_face_persistent_id(cf),
            ))

    return features


# ═══════════════════════════════════════════════════════════════════════════


def _are_walls_connected(idx0: int, idx1: int, adjacency: dict[int, set[int]], host_set: set[int]) -> bool:
    """BFS from idx0 to idx1 through faces that are not in host_set."""
    if idx0 == idx1:
        return True
    visited: set[int] = {idx0}
    stack = [idx0]
    while stack:
        cur = stack.pop()
        for nbr in adjacency.get(cur, set()):
            if nbr in host_set:
                continue
            if nbr == idx1:
                return True
            if nbr not in visited:
                visited.add(nbr)
                stack.append(nbr)
    return False

def _is_through_hole_in_floor(floor_face, cyl_face) -> bool:
    """Return True if *cyl_face* is a drilled hole passing through *floor_face*.

    A cylinder whose circular edge coincides with an inner wire (hole) of the
    floor face is a through-feature penetrating the floor, not a pocket wall.
    Uses OCC topology (inner wires) so it works for any floor shape and any
    hole-to-floor size ratio without requiring threshold constants.

    Falls back to False when the floor face has no inner wires (e.g. in
    topologically degenerate STEP files), letting the ratio fallback guard
    in the caller handle those cases.
    """
    from OCP.BRepTools import BRepTools

    outer_wire = BRepTools.OuterWire_s(floor_face)
    inner_edges: list = []
    wire_expl = TopExp_Explorer(floor_face, TopAbs_WIRE)
    while wire_expl.More():
        w = wire_expl.Current()
        if not w.IsSame(outer_wire):
            edge_expl = TopExp_Explorer(w, TopAbs_EDGE)
            while edge_expl.More():
                inner_edges.append(edge_expl.Current())
                edge_expl.Next()
        wire_expl.Next()

    if not inner_edges:
        return False

    cyl_expl = TopExp_Explorer(cyl_face, TopAbs_EDGE)
    while cyl_expl.More():
        cyl_edge = cyl_expl.Current()
        for ie in inner_edges:
            if cyl_edge.IsSame(ie):
                return True
        cyl_expl.Next()

    return False


# Pocket / Slot Detection
# ═══════════════════════════════════════════════════════════════════════════

def _detect_pockets_and_slots(
    face_infos: list[dict],
    adjacency: dict[int, set[int]],
    shape: TopoDS_Shape,
    claimed_faces: set[int] | None = None,
) -> list[FeatureDetail]:
    """Detect pockets and slots from recessed planar faces."""
    features: list[FeatureDetail] = []
    _claimed = claimed_faces or set()

    from OCP.gp import gp_Pnt, gp_Vec
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    import math

    planar_faces = [f for f in face_infos if f["type"] == "plane"]
    if len(planar_faces) < 2:
        return features

    fi_by_idx: dict[int, dict] = {f["index"]: f for f in face_infos}

    planar_faces.sort(key=lambda f: f["area_mm2"], reverse=True)

    def _face_point_normal(face):
        a = BRepAdaptor_Surface(face)
        u = (a.FirstUParameter() + a.LastUParameter()) / 2
        v = (a.FirstVParameter() + a.LastVParameter()) / 2
        p, du, dv = gp_Pnt(), gp_Vec(), gp_Vec()
        a.D1(u, v, p, du, dv)
        n = du.Crossed(dv)
        if n.Magnitude() > 1e-10:
            n.Normalize()
        return p, n

    def _wall_normal_for_face(wf_info):
        """Get an effective normal for a wall face (plane, cylinder, torus)."""
        face = wf_info["face"]
        ftype = wf_info["type"]
        if ftype == "plane":
            _, wn = _face_point_normal(face)
            return wn
        elif ftype == "cylinder":
            a = BRepAdaptor_Surface(face)
            ax = a.Cylinder().Axis().Direction()
            return gp_Vec(ax.X(), ax.Y(), ax.Z())
        elif ftype == "torus":
            a = BRepAdaptor_Surface(face)
            ax = a.Torus().Axis().Direction()
            return gp_Vec(ax.X(), ax.Y(), ax.Z())
        return None

    def _is_at_boundary(fc_x, fc_y, fc_z, n_x, n_y, n_z, margin):
        """Check if a face centre is near the part bounding-box boundary."""
        if abs(n_x) > 0.3 and (abs(fc_x - pxmin) < margin or abs(fc_x - pxmax) < margin):
            return True
        if abs(n_y) > 0.3 and (abs(fc_y - pymin) < margin or abs(fc_y - pymax) < margin):
            return True
        if abs(n_z) > 0.3 and (abs(fc_z - pzmin) < margin or abs(fc_z - pzmax) < margin):
            return True
        return False

    def _find_corner_radii(floor_idx, wall_indices, allow_seen=False):
        """Find corner fillet radii from torus/small-cylinder faces
        adjacent to both the floor and a wall.

        allow_seen: when True, also examine faces already in seen_face_indices
        (needed for the orphaned circular reference face path where concentric
        pocket detection has already consumed the small fillet cylinders).
        """
        radii = []
        floor_adj = adjacency.get(floor_idx, set())
        wall_set = set(wall_indices)
        for fi_idx, fi in enumerate(face_infos):
            if fi_idx in _claimed:
                continue
            if not allow_seen and fi_idx in seen_face_indices:
                continue
            if fi["type"] not in ("torus", "cylinder"):
                continue
            # Only REVERSED cylinders are concave pocket corner fillets.
            # FORWARD cylinders are convex outer surfaces, not corner radii.
            if fi["type"] == "cylinder" and fi.get("orientation") != "reversed":
                continue
            if fi_idx not in floor_adj:
                continue
            # Must also be adjacent to at least one wall
            fi_adj = adjacency.get(fi_idx, set())
            if not fi_adj.intersection(wall_set):
                continue
            try:
                a = BRepAdaptor_Surface(fi["face"])
                if fi["type"] == "torus":
                    r = a.Torus().MinorRadius()
                else:
                    r = a.Cylinder().Radius()
                if 0.1 < r < 50:  # reasonable corner radius range
                    radii.append(round(r, 3))
            except Exception:
                pass
        return radii

    top_pt, top_n = _face_point_normal(planar_faces[0]["face"])

    # Compute the part's overall bounding box.
    part_bbox = Bnd_Box()
    BRepBndLib.Add_s(shape, part_bbox)
    pxmin, pymin, pzmin, pxmax, pymax, pzmax = part_bbox.Get()
    part_max_dim = max(pxmax - pxmin, pymax - pymin, pzmax - pzmin)

    # Improvement #8: relative boundary margin instead of fixed 2mm.
    bnd_margin = max(0.5, min(5.0, part_max_dim * 0.005))

    # Find opposite reference surface for each group (improvement #7).
    def _find_opp_proj(ref_pt, ref_n, ref_proj_val):
        """Find the opposite parallel surface projection for a given ref."""
        for pf in planar_faces[1:]:
            p_pt, pf_n = _face_point_normal(pf["face"])
            if pf_n.Magnitude() < 1e-10:
                continue
            dot_r = abs(pf_n.X() * ref_n.X() + pf_n.Y() * ref_n.Y() + pf_n.Z() * ref_n.Z())
            if dot_r < 0.95:
                continue
            fp = p_pt.X() * ref_n.X() + p_pt.Y() * ref_n.Y() + p_pt.Z() * ref_n.Z()
            d = abs(ref_proj_val - fp)
            if d > 0.5:
                return fp
        return None

    ref_proj = top_pt.X() * top_n.X() + top_pt.Y() * top_n.Y() + top_pt.Z() * top_n.Z()

    groups: list[dict] = [{
        "normal": top_n,
        "ref_point": top_pt,
        "ref_area": planar_faces[0]["area_mm2"],
        "ref_index": planar_faces[0]["index"],
        "opp_proj": _find_opp_proj(top_pt, top_n, ref_proj),
    }]

    # Add secondary reference groups from outer boundary faces for other orientations.
    # Using boundary faces (not interior faces) ensures raw_depth from the reference
    # equals the true machining depth from the opening face.
    # Only large faces qualify — tiny end-caps produce unrealistic pocket depths.
    _largest_area = planar_faces[0]["area_mm2"]
    for _pf in planar_faces[1:]:
        if _pf["area_mm2"] < max(_largest_area * 0.08, 5.0):
            break  # sorted descending; remaining faces too small
        _ppt, _pn = _face_point_normal(_pf["face"])
        if _pn.Magnitude() < 1e-10:
            continue
        _pfb = Bnd_Box()
        BRepBndLib.Add_s(_pf["face"], _pfb)
        _fx1, _fy1, _fz1, _fx2, _fy2, _fz2 = _pfb.Get()
        _fcx, _fcy, _fcz = (_fx1+_fx2)/2, (_fy1+_fy2)/2, (_fz1+_fz2)/2
        if not _is_at_boundary(_fcx, _fcy, _fcz, _pn.X(), _pn.Y(), _pn.Z(), bnd_margin):
            continue
        _is_new = True
        for _g in groups:
            _gn = _g["normal"]
            _dot = abs(_pn.X()*_gn.X() + _pn.Y()*_gn.Y() + _pn.Z()*_gn.Z())
            if _dot > 0.3:
                _is_new = False
                break
        if not _is_new:
            continue
        _rp = _ppt.X() * _pn.X() + _ppt.Y() * _pn.Y() + _ppt.Z() * _pn.Z()
        groups.append({
            "normal": _pn,
            "ref_point": _ppt,
            "ref_area": _pf["area_mm2"],
            "ref_index": _pf["index"],
            "opp_proj": _find_opp_proj(_ppt, _pn, _rp),
        })

    seen_face_indices: set[int] = set()
    # Improvement #6: track floor-face → detected-pocket mapping so the
    # wall-based detector can skip pockets already found via their floor.
    floor_to_pocket: dict[int, int] = {}  # floor face idx → pocket feature idx

    for grp_idx, grp in enumerate(groups):
        gn = grp["normal"]
        rpt = grp["ref_point"]
        ref_proj_g = rpt.X() * gn.X() + rpt.Y() * gn.Y() + rpt.Z() * gn.Z()
        dim_along_gn = (abs(gn.X()) * (pxmax - pxmin) +
                        abs(gn.Y()) * (pymax - pymin) +
                        abs(gn.Z()) * (pzmax - pzmin))
        grp_opp_proj = grp.get("opp_proj")  # improvement #7

        for pf in planar_faces:
            if pf["index"] == grp.get("ref_index"):
                continue
            if pf["index"] in seen_face_indices:
                continue
            if pf["index"] in _claimed:
                continue
            # Pocket floors must be internal faces, not the outer skin.
            # Both forward and reversed faces can be pocket floors; reject only
            # faces that lie on the part boundary (tight margin).
            p_pt, pf_n = _face_point_normal(pf["face"])
            if pf_n.Magnitude() < 1e-10:
                continue
            _fb = Bnd_Box()
            BRepBndLib.Add_s(pf["face"], _fb)
            _fx1, _fy1, _fz1, _fx2, _fy2, _fz2 = _fb.Get()
            _fcx = (_fx1 + _fx2) / 2
            _fcy = (_fy1 + _fy2) / 2
            _fcz = (_fz1 + _fz2) / 2
            _skin_margin = 0.15
            if _is_at_boundary(_fcx, _fcy, _fcz, pf_n.X(), pf_n.Y(), pf_n.Z(), _skin_margin):
                continue

            dot_ref = abs(
                pf_n.X() * gn.X() + pf_n.Y() * gn.Y() + pf_n.Z() * gn.Z()
            )
            if dot_ref < 0.95:
                continue

            face_proj = p_pt.X() * gn.X() + p_pt.Y() * gn.Y() + p_pt.Z() * gn.Z()
            raw_depth = abs(ref_proj_g - face_proj)
            if raw_depth < 0.1:
                continue


            # Improvement #1: accept cylinder/torus walls alongside planar walls
            adj_idx = adjacency.get(pf["index"], set())

            # Pre-collect the floor's outer-wire edges once. Walls that share
            # only inner-wire (hole) edges with the floor bound a sub-pocket
            # *on* the floor — they are not walls of this pocket.
            _outer_wire = BRepTools.OuterWire_s(pf["face"])
            _floor_outer_edges: list = []
            _foe_exp = TopExp_Explorer(_outer_wire, TopAbs_EDGE)
            while _foe_exp.More():
                _floor_outer_edges.append(_foe_exp.Current())
                _foe_exp.Next()

            wall_faces: list[dict] = []
            wall_angles: list[float] = []
            for wf in face_infos:
                if wf["index"] not in adj_idx:
                    continue
                # Reject walls whose shared edge with the floor lies only on
                # an inner wire — those delimit a sub-pocket, not this pocket.
                if _floor_outer_edges:
                    _wfe = TopExp_Explorer(wf["face"], TopAbs_EDGE)
                    _shares_outer = False
                    while _wfe.More():
                        if any(_wfe.Current().IsSame(_oe) for _oe in _floor_outer_edges):
                            _shares_outer = True
                            break
                        _wfe.Next()
                    if not _shares_outer:
                        continue
                if wf["type"] == "plane":
                    wpt, wn = _face_point_normal(wf["face"])
                    if wn.Magnitude() < 1e-10:
                        continue
                    wall_dot = abs(
                        pf_n.X() * wn.X() + pf_n.Y() * wn.Y() + pf_n.Z() * wn.Z()
                    )
                    if wall_dot < 0.5:
                        # Boundary (opening) walls are exempt from the inward
                        # check — they mark the pocket mouth and their normal
                        # cannot be expected to point toward the floor center.
                        wb = Bnd_Box()
                        BRepBndLib.Add_s(wf["face"], wb)
                        wbx1, wby1, wbz1, wbx2, wby2, wbz2 = wb.Get()
                        wbc_x = (wbx1 + wbx2) / 2
                        wbc_y = (wby1 + wby2) / 2
                        wbc_z = (wbz1 + wbz2) / 2
                        wall_on_bnd = _is_at_boundary(
                            wbc_x, wbc_y, wbc_z,
                            wn.X(), wn.Y(), wn.Z(),
                            bnd_margin,
                        )
                        if not wall_on_bnd:
                            # REVERSED faces have geometric normals pointing
                            # INTO the solid (away from the pocket void).
                            # Negate so we test the pocket-facing direction.
                            sign = (
                                -1.0
                                if wf.get("orientation", "forward") == "reversed"
                                else 1.0
                            )
                            inward = sign * (
                                wn.X() * (p_pt.X() - wpt.X())
                                + wn.Y() * (p_pt.Y() - wpt.Y())
                                + wn.Z() * (p_pt.Z() - wpt.Z())
                            )
                            if inward <= 0:
                                continue
                        wall_faces.append(wf)
                        wall_angles.append(round(math.degrees(math.acos(min(wall_dot, 1.0))), 1))
                elif wf["type"] in ("cylinder", "torus"):
                    # Only partial-arc (open) reversed cylinders qualify as curved
                    # pocket walls — e.g. a radiused corner on a rectangular slot.
                    # Full-revolution cylinders are holes or circular pockets and
                    # are handled exclusively by _detect_circular_pockets (shallow,
                    # depth/diameter < 0.5) and _detect_holes (deeper).  Claiming
                    # them here would block those detectors from finding the hole.
                    if wf["type"] == "cylinder":
                        if wf.get("orientation", "forward") == "forward":
                            continue  # external convex surface, not a pocket wall
                        if wf.get("is_closed_u", False):
                            continue  # full-revolution → hole or circular pocket
                    # A torus adjacent to a reversed cylinder is the fillet at
                    # the bottom of a blind hole — not a pocket wall.
                    if wf["type"] == "torus":
                        torus_nbrs = adjacency.get(wf["index"], set())
                        if any(
                            fi_by_idx.get(ni, {}).get("type") == "cylinder"
                            and fi_by_idx.get(ni, {}).get("orientation", "forward") == "reversed"
                            for ni in torus_nbrs
                        ):
                            continue
                    wn = _wall_normal_for_face(wf)
                    if wn is None or wn.Magnitude() < 1e-10:
                        continue
                    # Cylinder/torus axis should be roughly parallel to the
                    # pocket floor normal (wall wraps around it)
                    axis_dot = abs(
                        pf_n.X() * wn.X() + pf_n.Y() * wn.Y() + pf_n.Z() * wn.Z()
                    )
                    if axis_dot > 0.5:
                        wall_faces.append(wf)
                        wall_angles.append(90.0)
            if not wall_faces:
                continue

            smallest_wall = min(w["area_mm2"] for w in wall_faces)
            max_wall_ratio = 20 if grp_idx == 0 else 2
            if smallest_wall > pf["area_mm2"] * max_wall_ratio:
                continue

            if pf["area_mm2"] > 0.98 * grp["ref_area"]:
                continue

            # Compute pocket depth from wall-direction heuristic.
            # Wall centres sit between the floor and the pocket opening.
            # The side they lean toward (in the group-normal direction) is the
            # opening side, so depth = distance from floor to that boundary.
            _bnd_p1 = pxmin * gn.X() + pymin * gn.Y() + pzmin * gn.Z()
            _bnd_p2 = pxmax * gn.X() + pymax * gn.Y() + pzmax * gn.Z()
            _bnd_lo = min(_bnd_p1, _bnd_p2)
            _bnd_hi = max(_bnd_p1, _bnd_p2)
            _planar_wall_projs = []
            _boundary_wall_projs = []
            for _wf in wall_faces:
                if _wf["type"] == "plane":
                    _wpt, _wn = _face_point_normal(_wf["face"])
                    _proj = (
                        _wpt.X() * gn.X() + _wpt.Y() * gn.Y() + _wpt.Z() * gn.Z()
                    )
                    # Separate outer boundary walls from internal pocket walls
                    # so that global boundary faces do not bias the depth.
                    _wb = Bnd_Box()
                    BRepBndLib.Add_s(_wf["face"], _wb)
                    _wx1, _wy1, _wz1, _wx2, _wy2, _wz2 = _wb.Get()
                    _wcx = (_wx1 + _wx2) / 2
                    _wcy = (_wy1 + _wy2) / 2
                    _wcz = (_wz1 + _wz2) / 2
                    if _is_at_boundary(_wcx, _wcy, _wcz, _wn.X(), _wn.Y(), _wn.Z(), bnd_margin):
                        _boundary_wall_projs.append(_proj)
                    else:
                        _planar_wall_projs.append(_proj)
            _wall_projs_to_use = _planar_wall_projs if _planar_wall_projs else _boundary_wall_projs
            if _wall_projs_to_use:
                _avg_wall_proj = sum(_wall_projs_to_use) / len(_wall_projs_to_use)
                if _avg_wall_proj > face_proj:
                    depth = _bnd_hi - face_proj
                else:
                    depth = face_proj - _bnd_lo
            else:
                depth = raw_depth
                # Torus-walled pockets: raw_depth from the global group reference
                # may span the entire part height (e.g. a spot-face at the far end
                # of a disc gets depth = full disc height instead of 2-3mm).
                # BFS up to 5 hops through torus/cone transition faces; stop at
                # the first hop that yields a plane parallel to the pocket floor —
                # that plane is the actual opening surface.
                # Typical path: floor → rev-torus → rev-cone → fwd-torus → disc-face
                _torus_walls = [wf for wf in wall_faces if wf["type"] == "torus"]
                if _torus_walls:
                    _found_torus_depth = None   # parallel-plane result (preferred)
                    _fallback_torus_depth = None  # area-based result (fallback)
                    _visited_tw = {pf["index"]}
                    _frontier = set()
                    for _tw in _torus_walls:
                        _visited_tw.add(_tw["index"])
                        _frontier.update(adjacency.get(_tw["index"], set()))
                    for _hop in range(5):
                        _next_frontier = set()
                        for _adj_ti in _frontier:
                            if _adj_ti in _visited_tw:
                                continue
                            _visited_tw.add(_adj_ti)
                            _adj_tf = fi_by_idx.get(_adj_ti)
                            if _adj_tf is None:
                                continue
                            if _adj_tf["type"] == "plane":
                                _adj_tp, _adj_tn = _face_point_normal(_adj_tf["face"])
                                _adj_tproj = (
                                    _adj_tp.X() * gn.X()
                                    + _adj_tp.Y() * gn.Y()
                                    + _adj_tp.Z() * gn.Z()
                                )
                                _td = abs(face_proj - _adj_tproj)
                                if _td <= 0.1:
                                    continue
                                _para_dot = abs(
                                    _adj_tn.X() * gn.X()
                                    + _adj_tn.Y() * gn.Y()
                                    + _adj_tn.Z() * gn.Z()
                                )
                                if _para_dot >= 0.99:
                                    # Parallel to floor — preferred result
                                    if _found_torus_depth is None or _td < _found_torus_depth:
                                        _found_torus_depth = _td
                                elif _adj_tf["area_mm2"] > pf["area_mm2"]:
                                    # Not parallel but large — area-based fallback
                                    if _fallback_torus_depth is None or _td < _fallback_torus_depth:
                                        _fallback_torus_depth = _td
                            elif _adj_tf["type"] in ("torus", "cone"):
                                _next_frontier.update(adjacency.get(_adj_ti, set()))
                        if _found_torus_depth is not None:
                            break  # stop at first hop that yields a parallel plane
                        _frontier = _next_frontier
                        if not _frontier:
                            break
                    _best_tw_depth = (
                        _found_torus_depth
                        if _found_torus_depth is not None
                        else _fallback_torus_depth
                    )
                    if _best_tw_depth is not None and _best_tw_depth < depth:
                        depth = _best_tw_depth
            if depth < 0.1:
                continue

            # Reject depths exceeding the part's physical extent in that direction.
            if depth > dim_along_gn:
                continue


            # Improvement #9: detect through-pockets
            is_through = depth > 0.95 * dim_along_gn

            if depth < 0.3:
                continue

            fb = Bnd_Box()
            BRepBndLib.Add_s(pf["face"], fb)
            xmin, ymin, zmin, xmax, ymax, zmax = fb.Get()
            dims = sorted([xmax - xmin, ymax - ymin, zmax - zmin], reverse=True)
            length = dims[0]
            width = dims[1] if len(dims) > 1 else dims[0]

            # Detect irregular (frame/ring) floors: actual area << bounding-box area.
            # For these the bbox L×W is meaningless; report area_mm2 instead.
            _bbox_area = length * width
            _fill_ratio = pf["area_mm2"] / _bbox_area if _bbox_area > 0 else 1.0
            _is_irregular_floor = _fill_ratio < 0.5

            # Improvement #10: collect wall face indices, excluding diagonal
            # corner chamfer faces so they remain unclaimed for the chamfer
            # detector.  These faces are kept in wall_faces for depth/area
            # checks but are not added to seen_face_indices or face_indices.
            wall_indices = []
            for _wf in wall_faces:
                if _wf["type"] == "plane":
                    _, _wn = _face_point_normal(_wf["face"])
                    _pd = (pf_n.X()*_wn.X() + pf_n.Y()*_wn.Y()
                           + pf_n.Z()*_wn.Z())
                    _wp_x = _wn.X() - _pd * pf_n.X()
                    _wp_y = _wn.Y() - _pd * pf_n.Y()
                    _wp_z = _wn.Z() - _pd * pf_n.Z()
                    _wm = math.sqrt(_wp_x**2 + _wp_y**2 + _wp_z**2)
                    if (_wm > 1e-10
                            and max(abs(_wp_x), abs(_wp_y), abs(_wp_z)) / _wm < 0.8
                            and _wf["area_mm2"] < 0.25 * pf["area_mm2"]):
                        continue
                wall_indices.append(_wf["index"])
            all_face_indices = [pf["index"]] + wall_indices

            # Improvement #4: detect corner radii
            corner_radii = _find_corner_radii(pf["index"], wall_indices)

            # Improvement #3: approximate pocket volume
            pocket_volume = round(pf["area_mm2"] * depth, 3)

            # Improvement #5: average wall angle
            avg_wall_angle = round(sum(wall_angles) / len(wall_angles), 1) if wall_angles else 90.0

            seen_face_indices.add(pf["index"])
            for wi in wall_indices:
                seen_face_indices.add(wi)

            # Claim adjacent reversed partial-arc cylinders that sit on inner
            # wires of this floor.  These are corner radii or walls of
            # sub-pockets / slots within the floor (e.g. a rectangular
            # through-opening) — not independent holes.  Claiming them
            # prevents the hole detector from misclassifying them as
            # through-holes.
            for _ai in adj_idx:
                if _ai in seen_face_indices or _ai in _claimed:
                    continue
                _af = fi_by_idx.get(_ai)
                if _af is None or _af["type"] != "cylinder":
                    continue
                if _af.get("orientation", "forward") != "reversed":
                    continue
                if _af.get("is_closed_u", False):
                    continue
                if _floor_outer_edges and _is_through_hole_in_floor(
                    pf["face"], _af["face"]
                ):
                    seen_face_indices.add(_ai)
                    _claimed.add(_ai)

            floor_to_pocket[pf["index"]] = len(features)

            if _is_irregular_floor:
                pocket_dims: dict = {
                    "area_mm2": round(pf["area_mm2"], 3),
                    "depth_mm": round(depth, 3),
                    "volume_mm3": pocket_volume,
                    "wall_angle_deg": avg_wall_angle,
                }
                # Detect partial-ring (C-shape / arc) pockets: an irregular
                # floor with a REVERSED cylindrical inner wall and a FORWARD
                # cylindrical outer wall.  Collect radii from wall_faces (which
                # already filtered to REVERSED only) and from direct floor
                # adjacency for the FORWARD outer wall.
                _arc_inner_r: float | None = None
                _arc_outer_r: float | None = None
                for _wf in wall_faces:
                    if _wf["type"] == "cylinder" and _wf.get("orientation") == "reversed":
                        _wr = _wf.get("radius_mm", 0.0)
                        if _wr > 0 and (_arc_inner_r is None or _wr < _arc_inner_r):
                            _arc_inner_r = _wr
                # Outer wall (FORWARD cylinder) was filtered from wall_faces;
                # probe floor adjacency directly.
                _floor_adj = adjacency.get(pf["index"], set())
                for _fai in _floor_adj:
                    _faf = fi_by_idx.get(_fai)
                    if _faf and _faf["type"] == "cylinder" and _faf.get("orientation") == "forward":
                        _far = _faf.get("radius_mm", 0.0)
                        if _far > 0 and (_arc_outer_r is None or _far > _arc_outer_r):
                            _arc_outer_r = _far
                if (
                    _arc_inner_r is not None
                    and _arc_outer_r is not None
                    and _arc_outer_r > _arc_inner_r + 0.5
                ):
                    pocket_dims["is_arc_pocket"] = True
                    pocket_dims["inner_diameter_mm"] = round(_arc_inner_r * 2, 3)
                    pocket_dims["outer_diameter_mm"] = round(_arc_outer_r * 2, 3)
                    pocket_dims["ring_width_mm"] = round(_arc_outer_r - _arc_inner_r, 3)
            else:
                pocket_dims: dict = {
                    "length_mm": round(length, 3),
                    "width_mm": round(width, 3),
                    "depth_mm": round(depth, 3),
                    "volume_mm3": pocket_volume,
                    "wall_angle_deg": avg_wall_angle,
                }
            if is_through:
                pocket_dims["through_pocket"] = True
            if corner_radii:
                pocket_dims["corner_radius_mm"] = min(corner_radii)

            # Undercut: wall faces include torus faces that are not adjacent to
            # any reversed cylinder (i.e. they are pocket-boundary tori, not bore
            # entry fillets).  A torus boundary creates an overhang that a straight
            # end mill cannot reach — requires a specialised undercut tool.
            _has_undercut = any(
                wf["type"] == "torus"
                and not any(
                    fi_by_idx.get(ni, {}).get("type") == "cylinder"
                    and fi_by_idx.get(ni, {}).get("orientation", "forward") == "reversed"
                    for ni in adjacency.get(wf["index"], set())
                )
                for wf in wall_faces
            )
            if _has_undercut:
                pocket_dims["undercut"] = True

            # Annotate circular / annular pockets using geometry of the floor face.
            # A circular floor has a square bounding box (L ≈ W) but its actual
            # area is less than the full disc (π*(L/2)²) because it is either a
            # disc with a hole (annular) or because it is a true circle (not
            # square).  A genuine square pocket has floor_area ≈ L², well above
            # the disc area, so it does not trigger this check.
            if not _is_irregular_floor and length > 0 and abs(length - width) / length < 0.05:
                _disc_area = math.pi * (length / 2) ** 2
                _ar = pf["area_mm2"] / _disc_area
                if _ar < 0.85:  # floor area < 85 % of full disc → circular or annular
                    pocket_dims["is_circular"] = True
                    pocket_dims["diameter_mm"] = round((length + width) / 2, 3)
                    if _ar < 0.65:
                        pocket_dims["is_annular"] = True

            features.append(FeatureDetail(
                feature_id=_fid(),
                feature_type=FeatureType.POCKET,
                confidence=0.75,
                source="rule_based",
                dimensions=pocket_dims,
                location=_face_center(pf["face"]),
                face_indices=all_face_indices,
                orientation=_gp_vec_to_list(gn),
                key_face_id=_compute_face_persistent_id(pf),
            ))

    # ------------------------------------------------------------------
    # Wall-based pocket detection for through / deep pockets.
    # ------------------------------------------------------------------
    gn = groups[0]["normal"]
    perp_walls: list[dict] = []
    for wf in face_infos:
        if wf["type"] not in ("plane", "cylinder", "torus"):
            continue
        if wf["index"] in seen_face_indices or wf["index"] in _claimed:
            continue

        if wf["type"] == "plane":
            wpt, wn = _face_point_normal(wf["face"])
            if wn.Magnitude() < 1e-10:
                continue
            wall_dot = abs(wn.X() * gn.X() + wn.Y() * gn.Y() + wn.Z() * gn.Z())
            if wall_dot > 0.3:
                continue
            if wf["area_mm2"] < max(5.0, pf["area_mm2"] * 0.01):
                continue
            wb = Bnd_Box()
            BRepBndLib.Add_s(wf["face"], wb)
            wxmin, wymin, wzmin, wxmax, wymax, wzmax = wb.Get()
            fc_x = (wxmin + wxmax) / 2
            fc_y = (wymin + wymax) / 2
            fc_z = (wzmin + wzmax) / 2
            wn_x, wn_y, wn_z = wn.X(), wn.Y(), wn.Z()
            if _is_at_boundary(fc_x, fc_y, fc_z, wn_x, wn_y, wn_z, bnd_margin):
                continue
            wall_dims = [wxmax - wxmin, wymax - wymin, wzmax - wzmin]
            wall_depth = (
                abs(wall_dims[0] * gn.X())
                + abs(wall_dims[1] * gn.Y())
                + abs(wall_dims[2] * gn.Z())
            )
            if wall_depth < 0.3:
                continue
            wn_tup = (round(wn_x, 3), round(wn_y, 3), round(wn_z, 3))
            wall_pos = wpt.X() * abs(wn_x) + wpt.Y() * abs(wn_y) + wpt.Z() * abs(wn_z)
            perp_walls.append({
                "fi": wf,
                "normal": wn_tup,
                "pos": round(wall_pos, 3),
                "depth": wall_depth,
            })
        else:
            # Concave cylindrical or torus wall.
            # Only REVERSED cylinders are internal pocket walls; forward
            # cylinders are external boss/shaft surfaces.
            if wf["type"] == "cylinder":
                if wf.get("orientation", "forward") != "reversed":
                    continue
            else:  # torus
                # A torus adjacent to a reversed cylinder is the bottom fillet
                # of a blind hole — not a pocket wall.
                torus_nbrs = adjacency.get(wf["index"], set())
                if any(
                    fi_by_idx.get(ni, {}).get("type") == "cylinder"
                    and fi_by_idx.get(ni, {}).get("orientation", "forward") == "reversed"
                    for ni in torus_nbrs
                ):
                    continue
            wn = _wall_normal_for_face(wf)
            if wn is None or wn.Magnitude() < 1e-10:
                continue
            # Axis must be roughly parallel to the group normal so the curved
            # surface wraps around the pocket's depth direction.
            axis_dot = abs(wn.X() * gn.X() + wn.Y() * gn.Y() + wn.Z() * gn.Z())
            if axis_dot <= 0.5:
                continue
            if wf["area_mm2"] < max(5.0, pf["area_mm2"] * 0.01):
                continue
            wb = Bnd_Box()
            BRepBndLib.Add_s(wf["face"], wb)
            wxmin, wymin, wzmin, wxmax, wymax, wzmax = wb.Get()
            wall_dims = [wxmax - wxmin, wymax - wymin, wzmax - wzmin]
            wall_depth = (
                abs(wall_dims[0] * gn.X())
                + abs(wall_dims[1] * gn.Y())
                + abs(wall_dims[2] * gn.Z())
            )
            if wall_depth < 0.3:
                continue
            # Curved walls have no single outward normal; exclude them from
            # opposing-pair matching but count them toward the wall minimum.
            perp_walls.append({
                "fi": wf,
                "normal": None,
                "pos": 0.0,
                "depth": wall_depth,
            })

    if len(perp_walls) >= 3:
        from collections import defaultdict

        for pw in perp_walls:
            adj = adjacency.get(pw["fi"]["index"], set())
            parallel_hosts: set[int] = set()
            for ai in adj:
                if ai >= len(face_infos):
                    continue
                af = face_infos[ai]
                if af["type"] != "plane":
                    continue
                apt, an = _face_point_normal(af["face"])
                if an.Magnitude() < 1e-10:
                    continue
                dot = abs(an.X() * gn.X() + an.Y() * gn.Y() + an.Z() * gn.Z())
                if dot > 0.8:
                    parallel_hosts.add(ai)
            pw["hosts"] = frozenset(parallel_hosts)

        host_wall_groups: dict[frozenset, list[dict]] = defaultdict(list)
        for pw in perp_walls:
            if pw["hosts"]:
                host_wall_groups[pw["hosts"]].append(pw)

        for _host_key, group_walls in host_wall_groups.items():
            if len(group_walls) < 3:
                continue

            # Improvement #6: skip only if a host that is already a
            # floor-based pocket's floor is fully *surrounded* by this wall
            # group — meaning every face adjacent to that floor is either a
            # wall in this group or another host face.  A wall group that
            # covers only a portion of the host's boundary describes a
            # sub-pocket sitting ON the floor, not the same pocket.
            _skip_group = False
            _wall_set = {pw["fi"]["index"] for pw in group_walls}
            _host_set = set(_host_key)
            for _h in _host_key:
                if _h not in floor_to_pocket:
                    continue
                _h_adj = adjacency.get(_h, set())
                if _h_adj.issubset(_wall_set | _host_set):
                    _skip_group = True
                    break
            if _skip_group:
                continue

            # Split into connected components so disjoint pockets that share
            # the same host faces are not merged into a single feature.
            # We traverse through any face except the host faces, so walls that
            # are linked by intermediate pocket faces (e.g. corner bridges) stay
            # together, while spatially separate pockets stay apart.
            wall_by_idx = {pw["fi"]["index"]: pw for pw in group_walls}
            wall_idx_set = set(wall_by_idx)
            host_set = set(_host_key)
            comp_visited: set[int] = set()
            components: list[list[dict]] = []
            for idx in wall_idx_set:
                if idx in comp_visited:
                    continue
                stack = [idx]
                comp: list[dict] = []
                trav_visited: set[int] = set()
                while stack:
                    cur = stack.pop()
                    if cur in trav_visited:
                        continue
                    trav_visited.add(cur)
                    if cur in wall_idx_set and cur not in comp_visited:
                        comp_visited.add(cur)
                        comp.append(wall_by_idx[cur])
                    for nbr in adjacency.get(cur, set()):
                        if nbr in host_set:
                            continue
                        if nbr not in trav_visited:
                            stack.append(nbr)
                components.append(comp)

            for comp_walls in components:
                if len(comp_walls) < 3:
                    continue

                orient_groups: dict[tuple, list[dict]] = defaultdict(list)
                for pw in comp_walls:
                    n = pw["normal"]
                    if n is None:
                        continue  # curved walls count toward total but not pairs
                    key = tuple(abs(c) for c in n)
                    orient_groups[key].append(pw)

                pairs: list[tuple[dict, dict, float, tuple]] = []
                for key, walls_in_dir in orient_groups.items():
                    if len(walls_in_dir) < 2:
                        continue
                    walls_in_dir.sort(key=lambda w: w["pos"])
                    w0 = walls_in_dir[0]
                    w1 = walls_in_dir[-1]
                    span = abs(w1["pos"] - w0["pos"])
                    if span > 5:
                        # Verify walls bound a cavity: the low wall (w0) must
                        # face toward the high wall and the high wall toward the
                        # low wall.  Boss outer walls fail this check because
                        # they face away from each other.
                        # REVERSED faces have geometric normals pointing INTO
                        # the solid — negate them to get the pocket-facing dir.
                        sign0 = (
                            -1.0
                            if w0["fi"].get("orientation", "forward") == "reversed"
                            else 1.0
                        )
                        sign1 = (
                            -1.0
                            if w1["fi"].get("orientation", "forward") == "reversed"
                            else 1.0
                        )
                        w0_inward = sign0 * sum(w0["normal"][k] * key[k] for k in range(3))
                        w1_inward = sign1 * sum(w1["normal"][k] * key[k] for k in range(3))
                        if w0_inward <= 0 or w1_inward >= 0:
                            continue
                        # Connectivity check: the two opposing walls must be linked
                        # through a chain of adjacent faces excluding the host faces
                        # (top / bottom). This prevents pairing walls that belong to
                        # separate pockets which happen to share the same host set.
                        if not _are_walls_connected(
                            w0["fi"]["index"], w1["fi"]["index"], adjacency, host_set
                        ):
                            continue
                        pairs.append((w0, w1, span, key))

                if len(pairs) >= 1:
                    pairs.sort(key=lambda p: p[2], reverse=True)
                    p_length = pairs[0][2]
                    if len(pairs) >= 2:
                        p_width = pairs[1][2]
                    else:
                        # Only one opposing pair.  Use component bbox extent
                        # perpendicular to the pair direction and depth direction.
                        pair_key = pairs[0][3]
                        pair_axis = max(range(3), key=lambda i: abs(pair_key[i]))
                        depth_axis = None
                        if abs(gn.X()) > 0.9:
                            depth_axis = 0
                        elif abs(gn.Y()) > 0.9:
                            depth_axis = 1
                        elif abs(gn.Z()) > 0.9:
                            depth_axis = 2
                        p_width = 0.0
                        if depth_axis is not None and depth_axis != pair_axis:
                            _comp_bbox = Bnd_Box()
                            for pw in comp_walls:
                                BRepBndLib.Add_s(pw["fi"]["face"], _comp_bbox)
                            _cx1, _cy1, _cz1, _cx2, _cy2, _cz2 = _comp_bbox.Get()
                            _extents = [_cx2 - _cx1, _cy2 - _cy1, _cz2 - _cz1]
                            _candidates = [
                                _extents[i]
                                for i in range(3)
                                if i != pair_axis and i != depth_axis
                            ]
                            if _candidates:
                                p_width = max(_candidates)
                        if p_width <= 0.0:
                            # Fallback to old open-distance logic
                            pair_indices = {
                                pairs[0][0]["fi"]["index"],
                                pairs[0][1]["fi"]["index"],
                            }
                            open_distances = []
                            for upw in comp_walls:
                                if upw["normal"] is None:
                                    continue
                                if upw["fi"]["index"] in pair_indices:
                                    continue
                                nx, ny, nz = upw["normal"]
                                upt, _ = _face_point_normal(upw["fi"]["face"])
                                face_proj = (
                                    upt.X() * nx + upt.Y() * ny + upt.Z() * nz
                                )
                                bnd = (
                                    pxmax * max(nx, 0) + pxmin * min(nx, 0)
                                    + pymax * max(ny, 0) + pymin * min(ny, 0)
                                    + pzmax * max(nz, 0) + pzmin * min(nz, 0)
                                )
                                dist = bnd - face_proj
                                if dist > 0:
                                    open_distances.append(dist)
                            p_width = max(open_distances) if open_distances else 0.0
                    all_depths = [pw["depth"] for pw in comp_walls]
                    p_depth = sum(all_depths) / len(all_depths)
                    wall_face_indices = [pw["fi"]["index"] for pw in comp_walls]

                    # Improvement #9: through-pocket check
                    dim_along_gn = (abs(gn.X()) * (pxmax - pxmin) +
                                    abs(gn.Y()) * (pymax - pymin) +
                                    abs(gn.Z()) * (pzmax - pzmin))
                    is_through_w = p_depth > 0.95 * dim_along_gn

                    # Improvement #3: volume
                    wall_volume = round(p_length * p_width * p_depth, 3)

                    for idx in wall_face_indices:
                        seen_face_indices.add(idx)

                    # Corner radii: use each host parallel face as the reference
                    # floor so that fillet faces adjacent to those hosts and the
                    # walls are found the same way Pass 1 finds them.
                    all_corner_radii: list[float] = []
                    for hf_idx in _host_key:
                        all_corner_radii.extend(
                            _find_corner_radii(hf_idx, wall_face_indices)
                        )

                    wall_pocket_dims: dict = {
                        "length_mm": round(p_length, 3),
                        "width_mm": round(p_width, 3),
                        "depth_mm": round(p_depth, 3),
                        "volume_mm3": wall_volume,
                    }
                    if is_through_w:
                        wall_pocket_dims["through_pocket"] = True
                    if all_corner_radii:
                        wall_pocket_dims["corner_radius_mm"] = min(all_corner_radii)

                    features.append(FeatureDetail(
                        feature_id=_fid(),
                        feature_type=FeatureType.POCKET,
                        confidence=0.70,
                        source="rule_based",
                        dimensions=wall_pocket_dims,
                        location=_face_center(comp_walls[0]["fi"]["face"]),
                        face_indices=wall_face_indices,
                        orientation=_gp_vec_to_list(gn),
                        key_face_id=_compute_face_persistent_id(comp_walls[0]["fi"]),
                    ))

    # ------------------------------------------------------------------
    # Reference-free pocket detection for angled floors.
    # ------------------------------------------------------------------
    for pf in planar_faces:
        if pf["index"] in seen_face_indices or pf["index"] in _claimed:
            continue
        if pf["area_mm2"] > 0.85 * planar_faces[0]["area_mm2"]:
            continue
        if pf.get("orientation") != "reversed":
            continue

        p_pt, pf_n = _face_point_normal(pf["face"])
        if pf_n.Magnitude() < 1e-10:
            continue

        pfb = Bnd_Box()
        BRepBndLib.Add_s(pf["face"], pfb)
        fx1, fy1, fz1, fx2, fy2, fz2 = pfb.Get()
        fcx = (fx1 + fx2) / 2
        fcy = (fy1 + fy2) / 2
        fcz = (fz1 + fz2) / 2
        if _is_at_boundary(fcx, fcy, fcz, pf_n.X(), pf_n.Y(), pf_n.Z(), bnd_margin):
            continue

        floor_proj = (
            p_pt.X() * pf_n.X() + p_pt.Y() * pf_n.Y() + p_pt.Z() * pf_n.Z()
        )

        # Improvement #1: accept cylinder/torus walls in reference-free too
        adj_idx = adjacency.get(pf["index"], set())
        walls: list[dict] = []
        for wf in face_infos:
            if wf["index"] not in adj_idx:
                continue
            if wf["type"] == "plane":
                wpt, wn = _face_point_normal(wf["face"])
                if wn.Magnitude() < 1e-10:
                    continue
                wall_floor_dot = abs(
                    pf_n.X() * wn.X() + pf_n.Y() * wn.Y() + pf_n.Z() * wn.Z()
                )
                if wall_floor_dot > 0.5:
                    continue
                wall_proj = (
                    wpt.X() * pf_n.X() + wpt.Y() * pf_n.Y() + wpt.Z() * pf_n.Z()
                )
                walls.append({
                    "fi": wf,
                    "normal": (wn.X(), wn.Y(), wn.Z()),
                    "proj": wall_proj,
                    "center": (wpt.X(), wpt.Y(), wpt.Z()),
                })
            elif wf["type"] in ("cylinder", "torus"):
                # Mirror the floor-based path rule: only partial-arc reversed
                # cylinders are valid curved pocket walls.  Full-revolution
                # cylinders and forward (convex) cylinders are not.
                if wf["type"] == "cylinder":
                    if wf.get("orientation", "forward") == "forward":
                        continue  # external convex surface
                    if wf.get("is_closed_u", False):
                        continue  # full-revolution → hole or circular pocket
                wn = _wall_normal_for_face(wf)
                if wn is None or wn.Magnitude() < 1e-10:
                    continue
                axis_dot = abs(
                    pf_n.X() * wn.X() + pf_n.Y() * wn.Y() + pf_n.Z() * wn.Z()
                )
                if axis_dot <= 0.5:
                    continue
                wc = _face_center(wf["face"])
                wall_proj = (
                    wc.x * pf_n.X() + wc.y * pf_n.Y() + wc.z * pf_n.Z()
                )
                # Curved walls don't have a meaningful planar normal for
                # anti-parallel checks, so we skip them in pair matching
                # but still count them as wall evidence.
                walls.append({
                    "fi": wf,
                    "normal": None,  # curved — no planar normal
                    "proj": wall_proj,
                    "center": (wc.x, wc.y, wc.z),
                })

        # Find at least one pair of opposing planar walls on the same side
        best_depth = 0.0
        best_pair: tuple | None = None
        for i in range(len(walls)):
            if walls[i]["normal"] is None:
                continue
            for j in range(i + 1, len(walls)):
                if walls[j]["normal"] is None:
                    continue
                ni = walls[i]["normal"]
                nj = walls[j]["normal"]
                dot_ij = ni[0] * nj[0] + ni[1] * nj[1] + ni[2] * nj[2]
                if dot_ij > -0.7:
                    continue
                # Both walls must face toward the floor center (inward).
                # REVERSED faces have geometric normals pointing INTO the
                # solid — negate them to get the pocket-facing direction.
                ci = walls[i]["center"]
                cj = walls[j]["center"]
                sign_i = (
                    -1.0
                    if walls[i]["fi"].get("orientation", "forward") == "reversed"
                    else 1.0
                )
                sign_j = (
                    -1.0
                    if walls[j]["fi"].get("orientation", "forward") == "reversed"
                    else 1.0
                )
                inward_i = sign_i * (
                    ni[0] * (p_pt.X() - ci[0])
                    + ni[1] * (p_pt.Y() - ci[1])
                    + ni[2] * (p_pt.Z() - ci[2])
                )
                inward_j = sign_j * (
                    nj[0] * (p_pt.X() - cj[0])
                    + nj[1] * (p_pt.Y() - cj[1])
                    + nj[2] * (p_pt.Z() - cj[2])
                )
                if inward_i <= 0 or inward_j <= 0:
                    continue
                di = walls[i]["proj"] - floor_proj
                dj = walls[j]["proj"] - floor_proj
                if abs(di) > 0.1 and abs(dj) > 0.1 and di * dj < 0:
                    continue
                wb_i = Bnd_Box()
                BRepBndLib.Add_s(walls[i]["fi"]["face"], wb_i)
                ix1, iy1, iz1, ix2, iy2, iz2 = wb_i.Get()
                depth_i = (abs((ix2 - ix1) * pf_n.X()) +
                           abs((iy2 - iy1) * pf_n.Y()) +
                           abs((iz2 - iz1) * pf_n.Z()))
                wb_j = Bnd_Box()
                BRepBndLib.Add_s(walls[j]["fi"]["face"], wb_j)
                jx1, jy1, jz1, jx2, jy2, jz2 = wb_j.Get()
                depth_j = (abs((jx2 - jx1) * pf_n.X()) +
                           abs((jy2 - jy1) * pf_n.Y()) +
                           abs((jz2 - jz1) * pf_n.Z()))
                pair_depth = min(depth_i, depth_j)
                if pair_depth > best_depth:
                    best_depth = pair_depth
                    best_pair = (walls[i], walls[j])

        if best_pair is None or best_depth < 0.3:
            continue

        smallest_wall_area = min(
            best_pair[0]["fi"]["area_mm2"],
            best_pair[1]["fi"]["area_mm2"],
        )
        if smallest_wall_area > pf["area_mm2"] * 20:
            continue

        dims_rf = sorted([fx2 - fx1, fy2 - fy1, fz2 - fz1], reverse=True)
        length_rf = dims_rf[0]
        width_rf = dims_rf[1] if len(dims_rf) > 1 else dims_rf[0]

        # Improvement #10: collect wall indices, excluding diagonal corner
        # chamfer faces so they remain unclaimed for the chamfer detector.
        rf_wall_indices = []
        for _w in walls:
            if _w["normal"] is not None:
                _nx, _ny, _nz = _w["normal"]
                _pd3 = pf_n.X()*_nx + pf_n.Y()*_ny + pf_n.Z()*_nz
                _wp3_x = _nx - _pd3 * pf_n.X()
                _wp3_y = _ny - _pd3 * pf_n.Y()
                _wp3_z = _nz - _pd3 * pf_n.Z()
                _wm3 = math.sqrt(_wp3_x**2 + _wp3_y**2 + _wp3_z**2)
                if (_wm3 > 1e-10
                        and max(abs(_wp3_x), abs(_wp3_y), abs(_wp3_z)) / _wm3 < 0.8
                        and _w["fi"]["area_mm2"] < 0.25 * pf["area_mm2"]):
                    continue
            rf_wall_indices.append(_w["fi"]["index"])
        all_rf_indices = [pf["index"]] + rf_wall_indices

        # Improvement #4: corner radii
        rf_corner_radii = _find_corner_radii(pf["index"], rf_wall_indices)

        # Improvement #3: volume
        rf_volume = round(pf["area_mm2"] * best_depth, 3)

        seen_face_indices.add(pf["index"])
        for wi in rf_wall_indices:
            seen_face_indices.add(wi)

        rf_dims: dict = {
            "length_mm": round(length_rf, 3),
            "width_mm": round(width_rf, 3),
            "depth_mm": round(best_depth, 3),
            "volume_mm3": rf_volume,
        }
        if rf_corner_radii:
            rf_dims["corner_radius_mm"] = min(rf_corner_radii)

        features.append(FeatureDetail(
            feature_id=_fid(),
            feature_type=FeatureType.POCKET,
            confidence=0.65,
            source="rule_based",
            dimensions=rf_dims,
            location=_face_center(pf["face"]),
            face_indices=all_rf_indices,
            orientation=_gp_vec_to_list(pf_n),
            key_face_id=_compute_face_persistent_id(pf),
        ))

    # ── Detect REVERSED circular reference faces as shallow circular pockets ──
    # The group reference face (planar_faces[0] and secondary refs) is excluded
    # from the inner pocket loop by design (it's the depth baseline).  When
    # that face is REVERSED and has circular geometry it is itself a machined
    # recess — emit it as a separate circular pocket feature.
    _ref_indices = {grp.get("ref_index") for grp in groups}
    for _rf_idx in _ref_indices:
        if _rf_idx is None:
            continue
        if _rf_idx in seen_face_indices or _rf_idx in _claimed:
            continue
        _rf = fi_by_idx.get(_rf_idx)
        if _rf is None or _rf.get("orientation", "forward") != "reversed":
            continue
        _rfb = Bnd_Box()
        BRepBndLib.Add_s(_rf["face"], _rfb)
        _x1, _y1, _z1, _x2, _y2, _z2 = _rfb.Get()
        _rfb_dims = sorted([_x2 - _x1, _y2 - _y1, _z2 - _z1], reverse=True)
        _rf_l, _rf_w = _rfb_dims[0], _rfb_dims[1]
        if _rf_l < 5.0 or abs(_rf_l - _rf_w) / _rf_l > 0.08:
            continue  # non-square bbox → not circular
        _disc_area = math.pi * (_rf_l / 2) ** 2
        _ar = _rf["area_mm2"] / _disc_area
        if not (0.20 < _ar < 0.90):
            continue  # full disc (≥0.90) or too small
        _rf_pt, _rf_n = _face_point_normal(_rf["face"])
        if _rf_n.Magnitude() < 1e-10:
            continue
        _face_proj_rf = (
            _rf_pt.X() * _rf_n.X()
            + _rf_pt.Y() * _rf_n.Y()
            + _rf_pt.Z() * _rf_n.Z()
        )
        _bnd_p1 = pxmin * _rf_n.X() + pymin * _rf_n.Y() + pzmin * _rf_n.Z()
        _bnd_p2 = pxmax * _rf_n.X() + pymax * _rf_n.Y() + pzmax * _rf_n.Z()
        _bnd_lo_rf = min(_bnd_p1, _bnd_p2)
        _bnd_hi_rf = max(_bnd_p1, _bnd_p2)
        _depth_rf = min(
            abs(_face_proj_rf - _bnd_lo_rf),
            abs(_bnd_hi_rf - _face_proj_rf),
        )
        if _depth_rf < 0.05:
            continue
        _dims_rf: dict = {
            "length_mm": round(_rf_l, 3),
            "width_mm": round(_rf_w, 3),
            "depth_mm": round(_depth_rf, 3),
            "is_circular": True,
            "diameter_mm": round((_rf_l + _rf_w) / 2, 3),
        }
        if _ar < 0.72:
            _dims_rf["is_annular"] = True
        # Find corner radii: use ALL adjacent cylinder/plane faces as the wall
        # set, and allow already-seen faces (the concentric pocket consumed the
        # small r=3mm corner cylinders; they must be examined here too).
        # FORWARD cylinders are filtered inside _find_corner_radii.
        _rf_adj = adjacency.get(_rf_idx, set())
        _rf_wall_idxs = [
            f["index"] for f in face_infos
            if f["index"] in _rf_adj
            and f["type"] in ("cylinder", "plane")
        ]
        _rf_cr = _find_corner_radii(_rf_idx, _rf_wall_idxs, allow_seen=True)
        if _rf_cr:
            _dims_rf["corner_radius_mm"] = min(_rf_cr)
        # Claim adjacent unclaimed FORWARD cylinders (structural OD features at
        # this pocket boundary) so they are not reported as standalone fillets.
        _rf_fwd_cyls = [
            f["index"] for f in face_infos
            if f["index"] in _rf_adj
            and f["type"] == "cylinder"
            and f.get("orientation") == "forward"
            and f["index"] not in seen_face_indices
            and f["index"] not in _claimed
        ]
        seen_face_indices.update(_rf_fwd_cyls)
        seen_face_indices.add(_rf_idx)
        features.append(FeatureDetail(
            feature_id=_fid(),
            feature_type=FeatureType.POCKET,
            confidence=0.65,
            source="rule_based",
            dimensions=_dims_rf,
            location=_face_center(_rf["face"]),
            face_indices=[_rf_idx] + _rf_fwd_cyls,
            orientation=_gp_vec_to_list(_rf_n),
            key_face_id=_compute_face_persistent_id(_rf),
        ))

    return features


# ═══════════════════════════════════════════════════════════════════════════
# Circular Pocket Detection
# ═══════════════════════════════════════════════════════════════════════════

def _detect_circular_pockets(
    face_infos: list[dict],
    adjacency: dict[int, set[int]],
    claimed_faces: set[int],
) -> list[FeatureDetail]:
    """Detect ring grooves (annular channels) machined into flat faces.

    A ring groove is bounded by a planar floor, an outer cylindrical wall
    (perpendicular to the floor, reversed orientation), and an inner wall that
    is either a cylinder (perpendicular, forward orientation — standard groove)
    or a cone (angled inward, forward orientation — undercut groove).

    Standard ring groove topology (direct adjacency):
        floor plane ─── outer reversed cylinder (outer groove wall)
                    ─── inner forward cylinder  (inner groove wall / boss face)

    Undercut ring groove topology (walls connect to floor via fillet tori):
        floor plane ─── reversed torus ─── outer reversed cylinder
                    ─── reversed torus ─── inner forward cone  (undercut)

    The function works floor-first: for each planar face it collects candidate
    outer and inner walls, both directly adjacent and one hop through reversed
    fillet tori.  It then matches the largest outer wall with the smallest
    compatible inner wall (r_outer > r_inner).

    Undercut detection: when the inner wall is a cone (tapers outward toward the
    floor, i.e. the groove is wider at the bottom than at the opening), the
    feature is labelled has_undercut=True.  The inner_diameter_mm reported is
    the floor-level inner edge (R_major_inner_torus + R_minor for the undercut
    case, direct cylinder radius for the straight-wall case).

    Execution order:
      • Must run BEFORE _detect_holes (to claim groove cylinders that would
        otherwise be mis-classified as shallow blind holes).
      • Must run BEFORE _detect_pockets_and_slots (to claim groove cylinder
        faces so they are not re-used as planar pocket walls).
      • For lathe parts: runs AFTER _detect_lathe_bores.

    Dimensions reported:
        outer_diameter_mm — groove outer diameter
        inner_diameter_mm — groove inner diameter (at floor level for undercut)
        groove_width_mm   — radial width (r_outer − r_inner)
        depth_mm          — groove depth (outer wall height)
        is_annular        — always True
        has_undercut      — True when inner wall is conical
    """
    import math

    features: list[FeatureDetail] = []
    fi_by_idx: dict[int, dict] = {f["index"]: f for f in face_infos}

    for floor_fi in face_infos:
        if floor_fi["type"] != "plane":
            continue
        if floor_fi["index"] in claimed_faces:
            continue

        floor_adj: set[int] = adjacency.get(floor_fi["index"], set())

        # ── collect candidate walls ────────────────────────────────────────────
        # outer_walls: radius → face_info  (reversed cylinders = outer groove wall)
        # inner_walls: radius → (face_info, is_cone)
        outer_walls: dict[float, dict] = {}
        inner_walls: dict[float, tuple] = {}

        def _register_cylinder(af: dict) -> None:
            if af["index"] in claimed_faces or af["type"] != "cylinder":
                return
            r = af.get("radius_mm", 0.0)
            if r < 1.0:
                return
            if af.get("orientation") == "reversed":
                outer_walls.setdefault(r, af)
            elif af.get("orientation") == "forward":
                inner_walls.setdefault(r, (af, False))

        for ai in floor_adj:
            af = fi_by_idx.get(ai)
            if af is None:
                continue
            if af["type"] == "cylinder":
                # Direct adjacency: straight-wall groove
                _register_cylinder(af)
            elif af["type"] == "torus" and af.get("orientation") == "reversed":
                # One-hop via fillet torus → groove wall.
                # Use the torus's own R_major as the radius proxy for any adjacent
                # cone (avoids the gp_Cone.Radius() API which is absent in OCP).
                torus_R_maj: float | None = None
                torus_R_min: float = 0.0
                try:
                    t_ada = BRepAdaptor_Surface(af["face"])
                    tor = t_ada.Torus()
                    torus_R_maj = tor.MajorRadius()
                    torus_R_min = tor.MinorRadius()
                except Exception:
                    pass

                for bi in adjacency.get(ai, set()):
                    bf = fi_by_idx.get(bi)
                    if bf is None or bf["index"] == floor_fi["index"]:
                        continue
                    if bf["index"] in claimed_faces:
                        continue
                    if bf["type"] == "cylinder":
                        _register_cylinder(bf)
                    elif (bf["type"] == "cone"
                          and bf.get("orientation") == "forward"
                          and torus_R_maj is not None):
                        # Torus R_major + R_minor = floor-level tangency radius
                        r_proxy = torus_R_maj + torus_R_min
                        if r_proxy >= 1.0:
                            inner_walls.setdefault(r_proxy, (bf, True))

        if not outer_walls or not inner_walls:
            continue

        # ── match: largest outer with smallest compatible inner ───────────────
        r_outer_sorted = sorted(outer_walls.keys(), reverse=True)
        r_inner_sorted = sorted(inner_walls.keys())

        matched_r_out: float | None = None
        matched_r_in:  float | None = None
        for r_out in r_outer_sorted:
            for r_in in r_inner_sorted:
                width = r_out - r_in
                # Groove width must be at least 1 mm and at most 25% of outer
                # radius — wider than that is a step/bore, not a ring groove.
                if 1.0 <= width <= r_out * 0.25:
                    matched_r_out = r_out
                    matched_r_in  = r_in
                    break
            if matched_r_out is not None:
                break

        if matched_r_out is None:
            continue

        outer_fi          = outer_walls[matched_r_out]
        inner_fi, is_cone = inner_walls[matched_r_in]

        # ── axis alignment ────────────────────────────────────────────────────
        outer_ax = outer_fi.get("axis")
        inner_ax = inner_fi.get("axis")
        if outer_ax is not None and inner_ax is not None:
            dot = abs(
                outer_ax[0] * inner_ax[0]
                + outer_ax[1] * inner_ax[1]
                + outer_ax[2] * inner_ax[2]
            )
            if dot < 0.90:
                continue

        # ── depth from outer cylinder v-range ────────────────────────────────
        try:
            ow_ada = BRepAdaptor_Surface(outer_fi["face"])
            depth = abs(ow_ada.LastVParameter() - ow_ada.FirstVParameter())
        except Exception:
            r_ow = outer_fi.get("radius_mm", matched_r_out)
            depth = (outer_fi["area_mm2"] / (2.0 * math.pi * r_ow)
                     if r_ow > 0 else 0.0)

        if depth < 0.3:
            continue       # too shallow to be a real groove

        # For cones the matched_r_in is already the torus tangency radius
        # (R_major + R_minor), which is the correct floor-level inner edge.
        r_inner_floor = matched_r_in
        groove_width = matched_r_out - r_inner_floor

        dims: dict = {
            "outer_diameter_mm": round(matched_r_out * 2, 3),
            "inner_diameter_mm": round(r_inner_floor * 2, 3),
            "groove_width_mm":   round(groove_width, 3),
            "depth_mm":          round(depth, 3),
            "is_annular":        True,
        }
        if is_cone:
            dims["has_undercut"] = True

        face_indices = [floor_fi["index"], outer_fi["index"], inner_fi["index"]]
        claimed_faces.add(floor_fi["index"])
        claimed_faces.add(outer_fi["index"])
        claimed_faces.add(inner_fi["index"])

        features.append(FeatureDetail(
            feature_id=_fid(),
            feature_type=FeatureType.POCKET,
            confidence=0.85,
            source="rule_based",
            dimensions=dims,
            location=_face_center(floor_fi["face"]),
            face_indices=face_indices,
            orientation=_normalize_axis(outer_ax),
            key_face_id=_compute_face_persistent_id(floor_fi),
        ))

    logger.debug("Ring grooves detected: %d", len(features))
    return features


# ═══════════════════════════════════════════════════════════════════════════
# Obround Slot Detection
# ═══════════════════════════════════════════════════════════════════════════

def _detect_obround_slots(
    face_infos: list[dict],
    adjacency: dict[int, set[int]],
    thickness_stats: Optional[ThicknessStats],
    claimed_faces: set[int] | None = None,
) -> list[FeatureDetail]:
    """Detect obround (stadium-shaped) slot cutouts.

    An obround slot is made of two half-cylinder faces (the rounded ends)
    connected by flat side walls.  We pair small cylindrical faces that
    share the same radius, are close together, and penetrate through the
    sheet thickness.
    """
    features: list[FeatureDetail] = []
    _claimed = claimed_faces or set()
    if not thickness_stats:
        return features

    thickness = thickness_stats.min_mm
    if thickness <= 0:
        return features

    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    from OCP.gp import gp_Pnt, gp_Vec

    face_map = {f["index"]: f for f in face_infos}

    # Collect small half-cylinder candidates
    candidates: list[dict] = []
    for fi in face_infos:
        if fi["type"] != "cylinder":
            continue
        if fi["index"] in _claimed:
            continue
        # Obround slots are internal cutouts — must be REVERSED orientation.
        # FORWARD cylinders are outer body profile surfaces, not slots.
        if fi.get("orientation", "forward") != "reversed":
            continue
        radius = fi.get("radius_mm", 0)
        area = fi.get("area_mm2", 0)
        # Half-cylinder of an obround slot: radius = slot_width/2.
        # Support slot widths from 0.6mm to 100mm (radius 0.3–50mm).
        if radius < 0.3 or radius > 50:
            continue
        # Area of a half-cylinder through the sheet:
        #   π * r * thickness  (half the full circumference × depth)
        # Allow some tolerance
        expected_area = math.pi * radius * thickness
        if area > 2.5 * expected_area:
            continue

        bb = Bnd_Box()
        BRepBndLib.Add_s(fi["face"], bb)
        xmin, ymin, zmin, xmax, ymax, zmax = bb.Get()
        dims = sorted([xmax - xmin, ymax - ymin, zmax - zmin], reverse=True)
        # The through-sheet dimension should ≈ thickness
        if dims[2] < 0.3 * thickness or dims[2] > 3 * thickness:
            continue

        # Half-cylinder check: one bbox cross-section dim ≈ radius,
        # not ≈ diameter (full cylinders have both ≈ 2r).
        # For obround ends, bbox is roughly 2r × r × sheet_depth.
        bbox_cross = sorted([dims[0], dims[1]])  # [smaller, larger]
        if bbox_cross[0] > 0 and bbox_cross[1] / bbox_cross[0] < 1.3:
            # Both cross-section dims are similar → full cylinder, skip
            continue

        # Corner fillet check: a corner fillet cylinder is directly adjacent to a
        # large-radius bore/wall cylinder (radius >> this radius). Genuine obround
        # slot ends are adjacent only to planar slot walls/floors.
        fi_index = fi["index"]
        adj_to_large_bore = any(
            face_map.get(adj_idx, {}).get("type") == "cylinder"
            and face_map.get(adj_idx, {}).get("radius_mm", 0) > radius * 5
            for adj_idx in adjacency.get(fi_index, set())
        )
        if adj_to_large_bore:
            continue

        center = _face_center(fi["face"])
        candidates.append({
            "index": fi_index,
            "radius": radius,
            "center": center,
            "dims": dims,
        })

    # Pair candidates into obround slots using 2-hop wall connectivity.
    #
    # For each half-cylinder candidate (the "anchor" end with a clean 180° arc):
    #   1. Find its wall-parallel adjacent plane faces (the slot walls):
    #      plane faces whose normal is perpendicular (|dot| < 0.3) to the
    #      cylinder axis. This excludes top/bottom sheet faces which are
    #      parallel to the axis and adjacent to every face on the part.
    #   2. Find the partner: any REVERSED cylinder face that is adjacent to
    #      ALL of the anchor's wall faces (2 hops through the walls). This
    #      naturally handles asymmetric slots where the far end is a large arc
    #      (e.g. 270°) rather than another half-cylinder — that face would fail
    #      the per-candidate filter but is still topologically the other end of
    #      the same slot cavity.
    from OCP.gp import gp_Vec as _gp_Vec, gp_Pnt as _gp_Pnt

    def _plane_normal_dot_axis(plane_fi: dict, cyl_axis: tuple) -> float:
        """Absolute dot product of the plane face's normal with the cylinder axis."""
        try:
            adaptor = BRepAdaptor_Surface(plane_fi["face"])
            u = (adaptor.FirstUParameter() + adaptor.LastUParameter()) / 2
            v = (adaptor.FirstVParameter() + adaptor.LastVParameter()) / 2
            d1u, d1v = _gp_Vec(), _gp_Vec()
            adaptor.D1(u, v, _gp_Pnt(), d1u, d1v)
            n = d1u.Crossed(d1v)
            if n.Magnitude() < 1e-10:
                return 1.0  # degenerate — treat as parallel (exclude)
            n.Normalize()
            return abs(n.X() * cyl_axis[0] + n.Y() * cyl_axis[1] + n.Z() * cyl_axis[2])
        except Exception:
            return 1.0  # exclude on error

    # used_face_indices tracks face indices (not candidate list positions) so
    # that partners found via 2-hop search are also blocked from re-use.
    used_face_indices: set[int] = set()
    used_candidate_positions: set[int] = set()

    for i, a in enumerate(candidates):
        if i in used_candidate_positions:
            continue
        if a["index"] in used_face_indices:
            continue

        a_adj = adjacency.get(a["index"], set())
        a_axis = face_map[a["index"]].get("axis", (0.0, 0.0, 1.0))

        # Step 1: wall faces of candidate a (plane, perpendicular to cylinder axis)
        a_walls = frozenset(
            ni for ni in a_adj
            if face_map.get(ni, {}).get("type") == "plane"
            and _plane_normal_dot_axis(face_map[ni], a_axis) < 0.3
        )
        if not a_walls:
            continue

        # Step 2: gather all cylinder faces 2 hops away through a's walls
        two_hop_cyls: dict[int, dict] = {}
        for w in a_walls:
            for ni in adjacency.get(w, set()):
                if ni == a["index"] or ni in used_face_indices:
                    continue
                nf = face_map.get(ni, {})
                if (nf.get("type") == "cylinder"
                        and nf.get("orientation") == "reversed"):
                    two_hop_cyls[ni] = nf

        # Step 3: among 2-hop cylinders, pick the closest one that is adjacent
        # to ALL of a's wall faces (confirming it bounds the same slot cavity).
        best_partner_idx: int | None = None
        best_dist = float("inf")
        best_ctr = None

        for ni, nf in two_hop_cyls.items():
            ni_adj = adjacency.get(ni, set())
            if not a_walls.issubset(ni_adj):
                # Partner does not touch all of a's walls — different cavity.
                continue
            ctr_b = _face_center(nf["face"])
            dx = a["center"].x - ctr_b.x
            dy = a["center"].y - ctr_b.y
            dz = a["center"].z - ctr_b.z
            dist = (dx * dx + dy * dy + dz * dz) ** 0.5
            if dist < 2 or dist > 50:
                continue
            if dist < best_dist:
                best_dist = dist
                best_partner_idx = ni
                best_ctr = ctr_b

        if best_partner_idx is None:
            continue

        used_face_indices.add(a["index"])
        used_face_indices.add(best_partner_idx)
        used_candidate_positions.add(i)
        # Also mark partner's candidate position if it is a candidate.
        for k, c in enumerate(candidates):
            if c["index"] == best_partner_idx:
                used_candidate_positions.add(k)
                break

        b_radius = face_map[best_partner_idx].get("radius_mm", a["radius"])
        # Width is the narrower of the two ends (slot entrance).
        slot_width = min(a["radius"], b_radius) * 2
        # Length spans tip-to-tip through both radii.
        slot_length = best_dist + a["radius"] + b_radius
        mid_x = (a["center"].x + best_ctr.x) / 2
        mid_y = (a["center"].y + best_ctr.y) / 2
        mid_z = (a["center"].z + best_ctr.z) / 2
        from .models import Point3D
        features.append(FeatureDetail(
            feature_id=_fid(),
            feature_type=FeatureType.POCKET,
            confidence=0.8,
            source="rule_based",
            dimensions={
                "length_mm": round(slot_length, 3),
                "width_mm": round(slot_width, 3),
                "depth_mm": round(thickness, 3),
            },
            location=Point3D(x=round(mid_x, 3), y=round(mid_y, 3), z=round(mid_z, 3)),
            face_indices=[a["index"], best_partner_idx],
            orientation=_normalize_axis(a_axis),
            key_face_id=_compute_face_persistent_id(face_map[a["index"]]),
        ))

    return features


# ═══════════════════════════════════════════════════════════════════════════
# Fillet Detection
# ═══════════════════════════════════════════════════════════════════════════

def _detect_fillets(
    face_infos: list[dict],
    adjacency: dict[int, set[int]],
    claimed_faces: set[int] | None = None,
    part_type: Optional[PartType] = None,
) -> list[FeatureDetail]:
    """Detect fillets from toroidal and small cylindrical blend faces.

    Improvements over baseline:
    - Cylindrical fillets must bridge two non-cylindrical faces (adjacency check)
    - Uses BRepLProp_SLProps for concavity check when possible
    - Higher confidence when concavity is confirmed
    """
    features: list[FeatureDetail] = []
    _claimed = claimed_faces or set()

    for fi in face_infos:
        if fi["index"] in _claimed:
            continue

        if fi["type"] == "torus":
            minor_r = fi.get("minor_radius_mm", 0)
            if minor_r > 0:
                # Skip torus faces adjacent to already-claimed faces for
                # sheet-metal parts (bend corner transitions are part of
                # the bend, not standalone fillets).  For CNC/other parts
                # fillets legitimately border holes, pockets, etc.
                if part_type is None or part_type == PartType.SHEET_METAL:
                    adj_idx = adjacency.get(fi["index"], set())
                    if adj_idx & _claimed:
                        continue
                features.append(FeatureDetail(
                    feature_id=_fid(),
                    feature_type=FeatureType.FILLET,
                    confidence=0.85,
                    source="rule_based",
                    dimensions={"radius_mm": round(minor_r, 3)},
                    location=_face_center(fi["face"]),
                    face_indices=[fi["index"]],
                    key_face_id=_compute_face_persistent_id(fi),
                ))

        elif fi["type"] == "cylinder":
            # Small cylindrical faces bridging two faces → blend/fillet
            radius = fi.get("radius_mm", 0)
            area = fi.get("area_mm2", 0)
            # Reject modelling artefacts (edge blends < 0.2mm)
            if radius < 0.2:
                continue
            # Reject slivers — very small arc faces (< 30°) are modelling
            # artefacts, not meaningful blend faces.
            if not fi.get("is_closed_u", False):
                _ur = fi.get("u_range")
                if _ur is not None and abs(_ur[1] - _ur[0]) < math.pi / 6:
                    continue
            if 0 < radius <= 25 and area < math.pi * radius * 50:
                # Adjacency check: a fillet must bridge two non-cylindrical faces
                adj_idx = adjacency.get(fi["index"], set())
                non_cyl_adj = [
                    f for f in face_infos
                    if f["index"] in adj_idx and f["type"] != "cylinder"
                ]
                if len(non_cyl_adj) < 2:
                    continue  # Not a fillet — doesn't bridge two faces

                # Concavity check using BRepLProp_SLProps
                confidence = 0.60  # base confidence
                try:
                    adaptor = BRepAdaptor_Surface(fi["face"])
                    u_mid = (adaptor.FirstUParameter() + adaptor.LastUParameter()) / 2
                    v_mid = (adaptor.FirstVParameter() + adaptor.LastVParameter()) / 2
                    sl_props = BRepLProp_SLProps(adaptor, u_mid, v_mid, 2, 1e-6)
                    if sl_props.IsCurvatureDefined():
                        mean_curv = sl_props.MeanCurvature()
                        # Concave surface (negative mean curvature for inner blend)
                        # boosts confidence
                        if mean_curv < 0:
                            confidence = 0.75
                        else:
                            confidence = 0.65  # convex = round/edge break
                except Exception:
                    confidence = 0.60

                features.append(FeatureDetail(
                    feature_id=_fid(),
                    feature_type=FeatureType.FILLET,
                    confidence=confidence,
                    source="rule_based",
                    dimensions={"radius_mm": round(radius, 3)},
                    location=_face_center(fi["face"]),
                    face_indices=[fi["index"]],
                    key_face_id=_compute_face_persistent_id(fi),
                ))

    return features


# ═══════════════════════════════════════════════════════════════════════════
# Chamfer Detection
# ═══════════════════════════════════════════════════════════════════════════

def _detect_chamfers(
    face_infos: list[dict],
    adjacency: dict[int, set[int]],
    claimed_faces: set[int] | None = None,
) -> list[FeatureDetail]:
    """Detect chamfers: small planar faces at ~45° between two larger faces.

    Improvements:
    - Checks all adjacent planes (no arbitrary [:2] limit)
    - Doesn't break after first match — finds best match
    - Supports plane-to-cylinder chamfers
    - Respects claimed_faces
    """
    features: list[FeatureDetail] = []
    _claimed = claimed_faces or set()

    for fi in face_infos:
        if fi["type"] != "plane":
            continue
        if fi["index"] in _claimed:
            continue
        # Skip only extremely large faces (cheap pre-screen before normal
        # computation).  The adj_larger guard below is the structural filter;
        # the old 500mm² cap incorrectly excluded chamfers on large bores
        # (e.g. Ø100mm bore with 5mm chamfer ≈ 2200mm²).
        if fi["area_mm2"] > 50_000:
            continue

        adj_idx = adjacency.get(fi["index"], set())
        adj_larger = [
            f for f in face_infos
            if f["index"] in adj_idx
            and f["area_mm2"] > fi["area_mm2"]
            and f["type"] in ("plane", "cylinder")
        ]
        if len(adj_larger) < 2:
            continue

        # Check angle between this face and adjacent faces
        from OCP.gp import gp_Pnt, gp_Vec
        adaptor = BRepAdaptor_Surface(fi["face"])
        u_mid = (adaptor.FirstUParameter() + adaptor.LastUParameter()) / 2
        v_mid = (adaptor.FirstVParameter() + adaptor.LastVParameter()) / 2
        pt = gp_Pnt()
        d1u = gp_Vec()
        d1v = gp_Vec()
        adaptor.D1(u_mid, v_mid, pt, d1u, d1v)
        n1 = d1u.Crossed(d1v)
        if n1.Magnitude() < 1e-10:
            continue
        n1.Normalize()

        best_match = None
        for adj_f in adj_larger:
            if adj_f["type"] == "plane":
                adj_adaptor = BRepAdaptor_Surface(adj_f["face"])
                au = (adj_adaptor.FirstUParameter() + adj_adaptor.LastUParameter()) / 2
                av = (adj_adaptor.FirstVParameter() + adj_adaptor.LastVParameter()) / 2
                apt = gp_Pnt()
                ad1u = gp_Vec()
                ad1v = gp_Vec()
                adj_adaptor.D1(au, av, apt, ad1u, ad1v)
                n2 = ad1u.Crossed(ad1v)
                if n2.Magnitude() < 1e-10:
                    continue
                n2.Normalize()

                angle_rad = math.acos(max(-1.0, min(1.0, abs(n1.Dot(n2)))))
                angle_deg = math.degrees(angle_rad)

                if 30 < angle_deg < 60:
                    best_match = angle_deg
                    break
            elif adj_f["type"] == "cylinder":
                # Plane-to-cylinder chamfer: check if the chamfer face
                # connects a plane to a cylinder at an angle
                # The cylinder axis is perpendicular to the cylinder normal
                # at the surface, so we check the angle less strictly
                adj_adaptor = BRepAdaptor_Surface(adj_f["face"])
                au = (adj_adaptor.FirstUParameter() + adj_adaptor.LastUParameter()) / 2
                av = (adj_adaptor.FirstVParameter() + adj_adaptor.LastVParameter()) / 2
                apt = gp_Pnt()
                ad1u = gp_Vec()
                ad1v = gp_Vec()
                adj_adaptor.D1(au, av, apt, ad1u, ad1v)
                n2 = ad1u.Crossed(ad1v)
                if n2.Magnitude() < 1e-10:
                    continue
                n2.Normalize()

                angle_rad = math.acos(max(-1.0, min(1.0, abs(n1.Dot(n2)))))
                angle_deg = math.degrees(angle_rad)

                if 20 < angle_deg < 70:
                    best_match = angle_deg
                    break

        if best_match is not None:
            from OCP.Bnd import Bnd_Box
            from OCP.BRepBndLib import BRepBndLib
            fb = Bnd_Box()
            BRepBndLib.Add_s(fi["face"], fb)
            xmin, ymin, zmin, xmax, ymax, zmax = fb.Get()
            dims = sorted([xmax - xmin, ymax - ymin, zmax - zmin])
            chamfer_width = dims[1] if len(dims) > 1 else dims[0]

            # Reject very small chamfers — these are typically fillet/pocket
            # edge-break artefacts, not real chamfers. Threshold is 0.9mm
            # (not 1.0) to avoid floating-point rejection of genuine 1mm chamfers.
            if chamfer_width < 0.9:
                continue
            # Reject pocket-wall bridge faces: long strips adjacent to cylinders
            # (e.g. a vertical face connecting a top plane to corner radii).
            if chamfer_width > 0:
                largest_dim = dims[-1]
                has_cyl_neighbor = any(
                    f["type"] == "cylinder"
                    for f in adj_larger
                )
                if has_cyl_neighbor and largest_dim > 3 * chamfer_width:
                    continue


            features.append(FeatureDetail(
                feature_id=_fid(),
                feature_type=FeatureType.CHAMFER,
                confidence=0.8,
                source="rule_based",
                dimensions={
                    "width_mm": round(chamfer_width, 3),
                    "angle_deg": round(best_match, 1),
                },
                location=_face_center(fi["face"]),
                face_indices=[fi["index"]],
                key_face_id=_compute_face_persistent_id(fi),
            ))

    # ── Conical chamfer detection ──
    # A cone face with semi_angle ~30-60° adjacent to both a plane and a
    # cylinder (or two planes) is a conical chamfer (common on bosses,
    # edges of turned parts, etc.).
    for fi in face_infos:
        if fi["type"] != "cone":
            continue
        if fi["index"] in _claimed:
            continue
        # Already detected as planar chamfer's face?  Skip.
        if any(fi["index"] in f.face_indices for f in features):
            continue

        semi = fi.get("semi_angle_deg", 0)
        if not (20 < abs(semi) < 70):
            continue

        # Small surface area guard (avoid large draft/taper faces)
        if fi["area_mm2"] > 500:
            continue

        adj_idx = adjacency.get(fi["index"], set())
        adj_faces = [f for f in face_infos if f["index"] in adj_idx]
        adj_types = {f["type"] for f in adj_faces}

        # Must touch at least one plane and one other structural face
        if "plane" not in adj_types:
            continue
        if not adj_types.intersection({"cylinder", "plane"} - {"plane"}) and len(
            [f for f in adj_faces if f["type"] == "plane"]
        ) < 2:
            # Need either a cylinder neighbour or at least 2 plane neighbours
            continue

        from OCP.Bnd import Bnd_Box
        from OCP.BRepBndLib import BRepBndLib
        fb = Bnd_Box()
        BRepBndLib.Add_s(fi["face"], fb)
        xmin, ymin, zmin, xmax, ymax, zmax = fb.Get()
        dims = sorted([xmax - xmin, ymax - ymin, zmax - zmin])
        chamfer_width = dims[1] if len(dims) > 1 else dims[0]

        features.append(FeatureDetail(
            feature_id=_fid(),
            feature_type=FeatureType.CHAMFER,
            confidence=0.75,
            source="rule_based",
            dimensions={
                "width_mm": round(chamfer_width, 3),
                "angle_deg": round(abs(semi), 1),
            },
            location=_face_center(fi["face"]),
            face_indices=[fi["index"]],
            key_face_id=_compute_face_persistent_id(fi),
        ))

    return features

def _detect_bends(
    face_infos: list[dict],
    adjacency: dict[int, set[int]],
    thickness_stats: Optional[ThicknessStats],
    claimed_faces: set[int] | None = None,
) -> list[FeatureDetail]:
    """Detect bends: cylindrical face between two angled planar faces."""
    features: list[FeatureDetail] = []
    _claimed = claimed_faces or set()

    # Only skip bend detection if thickness is clearly too large for sheet metal
    if thickness_stats and thickness_stats.min_mm > 25:
        return features

    thickness = thickness_stats.mean_mm if thickness_stats else None

    for fi in face_infos:
        if fi["type"] != "cylinder":
            continue

        if fi["index"] in _claimed:
            continue

        radius = fi.get("radius_mm", 0)
        if radius < 0.1:
            continue

        # Bend radius should be proportional to sheet thickness
        # Typical range: 0.5× to 5× thickness
        if thickness and (radius > thickness * 5 or radius < thickness * 0.2):
            continue

        adj_idx = adjacency.get(fi["index"], set())
        adj_planes = [
            f for f in face_infos
            if f["index"] in adj_idx and f["type"] == "plane"
        ]

        if len(adj_planes) < 2:
            continue

        # Compute bend angle between the two largest adjacent planar faces
        adj_planes.sort(key=lambda f: f["area_mm2"], reverse=True)
        f1, f2 = adj_planes[0], adj_planes[1]

        from OCP.gp import gp_Pnt, gp_Vec

        def get_normal(face):
            a = BRepAdaptor_Surface(face)
            um = (a.FirstUParameter() + a.LastUParameter()) / 2
            vm = (a.FirstVParameter() + a.LastVParameter()) / 2
            p = gp_Pnt()
            du = gp_Vec()
            dv = gp_Vec()
            a.D1(um, vm, p, du, dv)
            n = du.Crossed(dv)
            if n.Magnitude() > 1e-10:
                n.Normalize()
            return n

        n1 = get_normal(f1["face"])
        n2 = get_normal(f2["face"])
        dot = n1.Dot(n2)
        dot = max(-1.0, min(1.0, dot))
        angle_between = math.degrees(math.acos(abs(dot)))

        if angle_between < 10:
            continue  # Faces are nearly parallel — not a bend

        bend_angle = 180 - angle_between

        # Estimate bend length from cylinder axis length
        from OCP.Bnd import Bnd_Box
        from OCP.BRepBndLib import BRepBndLib
        fb = Bnd_Box()
        BRepBndLib.Add_s(fi["face"], fb)
        xmin, ymin, zmin, xmax, ymax, zmax = fb.Get()
        dims = sorted([xmax - xmin, ymax - ymin, zmax - zmin], reverse=True)
        bend_length = dims[0]

        features.append(FeatureDetail(
            feature_id=_fid(),
            feature_type=FeatureType.BEND,
            confidence=0.9,
            source="rule_based",
            dimensions={
                "bend_angle_deg": round(bend_angle, 1),
                "bend_radius_mm": round(radius, 3),
                "bend_length_mm": round(bend_length, 3),
                "cylinder_face_indices": [fi["index"]],
            },
            location=_face_center(fi["face"]),
            face_indices=[fi["index"], f1["index"], f2["index"]],
        ))

    # ── Merge inner/outer bend surfaces of the same physical bend ──
    # A sheet-metal bend produces two cylindrical faces (inner and outer
    # radius) separated by the sheet thickness.  We merge them by checking:
    #   1) Shared adjacent planar faces (original criterion — works for
    #      thin parts where both cylinders touch the same plane), OR
    #   2) Axis alignment + centre proximity (robust for thick parts
    #      where the inner/outer cylinders adjoin different planar faces).
    # Keep the one with the smaller radius (inner / forming radius).
    _merge_thickness = thickness if thickness else 5.0

    # Pre-compute cylinder axis per bend from the first cylinder face
    def _bend_axis(feat: FeatureDetail) -> tuple:
        cyl_idx = feat.dimensions.get("cylinder_face_indices", [feat.face_indices[0]])[0]
        for fi in face_infos:
            if fi["index"] == cyl_idx:
                return fi.get("axis", (0, 0, 1))
        return (0, 0, 1)

    merged_bends: list[FeatureDetail] = []
    merged_flags = [False] * len(features)
    for i, a in enumerate(features):
        if merged_flags[i]:
            continue
        a_planes = {idx for idx in a.face_indices[1:]}  # planar face indices
        a_axis = _bend_axis(a)
        a_loc = a.location
        best = a
        all_faces = set(a.face_indices)
        all_cyl_faces = list(a.dimensions.get("cylinder_face_indices", [a.face_indices[0]]))
        for j in range(i + 1, len(features)):
            if merged_flags[j]:
                continue
            b = features[j]
            b_planes = {idx for idx in b.face_indices[1:]}

            # Criterion 1: shared planar face (original)
            shared_plane = bool(a_planes & b_planes)

            # Criterion 2: same axis direction + centres within
            # ~2× thickness (inner/outer offset ≈ thickness)
            spatial_match = False
            if not shared_plane and a_loc and b.location:
                b_axis = _bend_axis(b)
                if _axes_aligned(a_axis, b_axis, tol=0.95):
                    dx = a_loc.x - b.location.x
                    dy = a_loc.y - b.location.y
                    dz = a_loc.z - b.location.z
                    dist = (dx**2 + dy**2 + dz**2) ** 0.5
                    # Also check bend length similarity (same physical bend)
                    len_a = a.dimensions.get("bend_length_mm", 0)
                    len_b = b.dimensions.get("bend_length_mm", 0)
                    len_close = (abs(len_a - len_b) < max(len_a, len_b) * 0.15 + 1.0)
                    if dist < _merge_thickness * 2.5 and len_close:
                        spatial_match = True

            if shared_plane or spatial_match:
                merged_flags[j] = True
                all_faces.update(b.face_indices)
                all_cyl_faces.extend(b.dimensions.get("cylinder_face_indices", [b.face_indices[0]]))
                # Keep the smaller radius (inner / forming radius)
                if b.dimensions.get("bend_radius_mm", 999) < best.dimensions.get("bend_radius_mm", 999):
                    best = b
        # Attach all faces from both inner and outer surfaces
        best.face_indices = list(all_faces)
        best.dimensions["cylinder_face_indices"] = all_cyl_faces
        merged_bends.append(best)
    features = merged_bends

    return features


# ═══════════════════════════════════════════════════════════════════════════
# Thread Detection
# ═══════════════════════════════════════════════════════════════════════════

def _detect_threads(
    face_infos: list[dict],
    adjacency: dict[int, set[int]],
    claimed_faces: set[int] | None = None,
) -> list[FeatureDetail]:
    """Detect threads: BSpline faces on cylindrical features with helical edges.

    Improvements:
    - Uses GeomAbs_BSplineCurve enum instead of magic number 7
    - Requires adjacent cylindrical face for coaxiality confirmation
    - Higher confidence when adjacent cylinder is found
    """
    features: list[FeatureDetail] = []
    _claimed = claimed_faces or set()

    for fi in face_infos:
        if fi["type"] != "bspline":
            continue
        if fi["index"] in _claimed:
            continue

        face = fi["face"]
        # Check for helical edges (BSpline curves)
        edge_exp = TopExp_Explorer(face, TopAbs_EDGE)
        has_helix = False
        while edge_exp.More():
            edge = TopoDS.Edge_s(edge_exp.Current())
            try:
                adaptor = BRepAdaptor_Curve(edge)
                if adaptor.GetType() == GeomAbs_BSplineCurve:
                    has_helix = True
                    break
            except Exception:
                pass
            edge_exp.Next()

        if has_helix:
            # Coaxiality check: threads should be adjacent to a cylinder
            adj_idx = adjacency.get(fi["index"], set())
            adj_cyls = [
                f for f in face_infos
                if f["index"] in adj_idx and f["type"] == "cylinder"
            ]
            confidence = 0.75 if adj_cyls else 0.50

            # Extract thread diameter and axis from adjacent cylinder if available
            dimensions: dict = {}
            if adj_cyls:
                best_cyl = max(adj_cyls, key=lambda f: f.get("area_mm2", 0))
                dimensions["diameter_mm"] = round(best_cyl.get("radius_mm", 0) * 2, 3)
                cyl_axis = best_cyl.get("axis", (0, 0, 1))
                dimensions["axis"] = [round(cyl_axis[0], 6), round(cyl_axis[1], 6), round(cyl_axis[2], 6)]

            features.append(FeatureDetail(
                feature_id=_fid(),
                feature_type=FeatureType.THREAD,
                confidence=confidence,
                source="rule_based",
                dimensions=dimensions,
                location=_face_center(fi["face"]),
                face_indices=[fi["index"]],
            ))

    return features


# ═══════════════════════════════════════════════════════════════════════════
# Step Feature Detection
# ═══════════════════════════════════════════════════════════════════════════

def _detect_steps(
    face_infos: list[dict],
    adjacency: dict[int, set[int]],
    shape: TopoDS_Shape,
    claimed_faces: set[int] | None = None,
) -> list[FeatureDetail]:
    """Detect step features — height transitions across the part surface.

    A step is a planar face that:
    - is parallel to the reference (largest) face,
    - has a depth offset from the reference,
    - is relatively large compared to the reference (area ratio > 0.15),
    - is NOT fully enclosed by perpendicular walls on all sides (that would
      be a pocket).

    Steps are distinguished from pockets by spanning a significant portion
    of the part width/length (i.e. open on at least one side).
    """
    from OCP.gp import gp_Pnt, gp_Vec
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    features: list[FeatureDetail] = []
    _claimed = claimed_faces or set()

    planar_faces = [f for f in face_infos if f["type"] == "plane"]
    if len(planar_faces) < 2:
        return features

    planar_faces.sort(key=lambda f: f["area_mm2"], reverse=True)

    def _fpn(face):
        a = BRepAdaptor_Surface(face)
        u = (a.FirstUParameter() + a.LastUParameter()) / 2
        v = (a.FirstVParameter() + a.LastVParameter()) / 2
        p, du, dv = gp_Pnt(), gp_Vec(), gp_Vec()
        a.D1(u, v, p, du, dv)
        n = du.Crossed(dv)
        if n.Magnitude() > 1e-10:
            n.Normalize()
        return p, n

    # Get overall part bounding box for reference dimensions
    part_bb = Bnd_Box()
    BRepBndLib.Add_s(shape, part_bb)
    pxmin, pymin, pzmin, pxmax, pymax, pzmax = part_bb.Get()
    part_dims = sorted([pxmax - pxmin, pymax - pymin, pzmax - pzmin], reverse=True)
    part_footprint = part_dims[0] * part_dims[1] if len(part_dims) >= 2 else 1

    # Collect one reference face per unique normal orientation.
    # Only large BOUNDARY faces qualify as references — this avoids interior
    # faces (pocket floors, step faces) generating spurious step directions.
    bnd_margin_s = max(0.5, min(5.0, max(pxmax-pxmin, pymax-pymin, pzmax-pzmin) * 0.005))
    max_face_area_s = planar_faces[0]["area_mm2"] if planar_faces else 1.0
    ref_faces: list[dict] = []
    used_ref_normals: list = []
    for _pf in planar_faces:
        if _pf["area_mm2"] < max_face_area_s * 0.08:
            break  # sorted descending; nothing larger will follow
        _ppt, _pn = _fpn(_pf["face"])
        if _pn.Magnitude() < 1e-10:
            continue
        # Restrict to outer boundary faces only.
        _pfb = Bnd_Box()
        BRepBndLib.Add_s(_pf["face"], _pfb)
        _fx1, _fy1, _fz1, _fx2, _fy2, _fz2 = _pfb.Get()
        _fcx = (_fx1 + _fx2) / 2
        _fcy = (_fy1 + _fy2) / 2
        _fcz = (_fz1 + _fz2) / 2
        _at_bnd = (
            (abs(_pn.X()) > 0.3 and (abs(_fcx - pxmin) < bnd_margin_s or abs(_fcx - pxmax) < bnd_margin_s)) or
            (abs(_pn.Y()) > 0.3 and (abs(_fcy - pymin) < bnd_margin_s or abs(_fcy - pymax) < bnd_margin_s)) or
            (abs(_pn.Z()) > 0.3 and (abs(_fcz - pzmin) < bnd_margin_s or abs(_fcz - pzmax) < bnd_margin_s))
        )
        if not _at_bnd:
            continue
        _is_new = True
        for _un in used_ref_normals:
            if abs(_pn.X()*_un.X() + _pn.Y()*_un.Y() + _pn.Z()*_un.Z()) > 0.3:
                _is_new = False
                break
        if _is_new:
            ref_faces.append(_pf)
            used_ref_normals.append(_pn)

    # Ensure every principal axis has at least one boundary reference face so that
    # step features accessed from small end faces (below the area threshold) are
    # still detectable.  For each axis not yet covered, find the largest boundary
    # face aligned with it and add it unconditionally.
    for _av in ((1, 0, 0), (0, 1, 0), (0, 0, 1)):
        if any(abs(_un.X()*_av[0] + _un.Y()*_av[1] + _un.Z()*_av[2]) > 0.7
               for _un in used_ref_normals):
            continue
        _best_rf, _best_ra = None, 0.0
        for _pf in planar_faces:
            _ppt2, _pn2 = _fpn(_pf["face"])
            if abs(_pn2.X()*_av[0] + _pn2.Y()*_av[1] + _pn2.Z()*_av[2]) < 0.7:
                continue
            _pfb2 = Bnd_Box()
            BRepBndLib.Add_s(_pf["face"], _pfb2)
            _fx2, _fy2, _fz2, _fx2b, _fy2b, _fz2b = _pfb2.Get()
            _fcx2, _fcy2, _fcz2 = (_fx2+_fx2b)/2, (_fy2+_fy2b)/2, (_fz2+_fz2b)/2
            _at_bnd2 = (
                (abs(_pn2.X()) > 0.3 and (abs(_fcx2 - pxmin) < bnd_margin_s or abs(_fcx2 - pxmax) < bnd_margin_s)) or
                (abs(_pn2.Y()) > 0.3 and (abs(_fcy2 - pymin) < bnd_margin_s or abs(_fcy2 - pymax) < bnd_margin_s)) or
                (abs(_pn2.Z()) > 0.3 and (abs(_fcz2 - pzmin) < bnd_margin_s or abs(_fcz2 - pzmax) < bnd_margin_s))
            )
            if _at_bnd2 and _pf["area_mm2"] > _best_ra:
                _best_ra = _pf["area_mm2"]
                _best_rf = _pf
        if _best_rf is not None:
            ref_faces.append(_best_rf)
            _, _pn2 = _fpn(_best_rf["face"])
            used_ref_normals.append(_pn2)

    detected_step_indices: set[int] = set()

    for ref_face in ref_faces:
        ref_pt, ref_n = _fpn(ref_face["face"])
        if ref_n.Magnitude() < 1e-10:
            continue

        ref_proj = ref_pt.X() * ref_n.X() + ref_pt.Y() * ref_n.Y() + ref_pt.Z() * ref_n.Z()

        for pf in planar_faces:
            if pf["index"] == ref_face["index"]:
                continue
            if pf["index"] in _claimed:
                continue
            if pf["index"] in detected_step_indices:
                continue

            p_pt, pf_n = _fpn(pf["face"])
            if pf_n.Magnitude() < 1e-10:
                continue

            # Must be parallel to this reference orientation
            dot_ref = abs(
                pf_n.X() * ref_n.X() + pf_n.Y() * ref_n.Y() + pf_n.Z() * ref_n.Z()
            )
            if dot_ref < 0.9:
                continue

            # Must have depth offset
            face_proj = p_pt.X() * ref_n.X() + p_pt.Y() * ref_n.Y() + p_pt.Z() * ref_n.Z()
            raw_step_depth = abs(ref_proj - face_proj)
            if raw_step_depth < 0.1:
                continue

            # Step depth = distance from the nearer boundary in the reference
            # direction.  Using min(raw, dim-raw) correctly handles both cases:
            # steps near the reference face (raw < dim/2) and steps near the far
            # face (raw > dim/2, so dim-raw is smaller).  This also fixes end-face
            # references on long parts where the far-end step would otherwise have
            # an inflated raw depth.
            _dim_along = (abs(ref_n.X()) * (pxmax - pxmin) +
                          abs(ref_n.Y()) * (pymax - pymin) +
                          abs(ref_n.Z()) * (pzmax - pzmin))
            depth = min(raw_step_depth, _dim_along - raw_step_depth) if _dim_along > 0 else raw_step_depth

            # Area ratio check: steps are large sub-regions (> 2% of reference)
            area_ratio = pf["area_mm2"] / ref_face["area_mm2"]
            if area_ratio < 0.02:
                continue

            # ── Directional wall check ──
            # A step sits between two levels: it must have adjacent walls
            # (roughly perpendicular faces) on BOTH sides along the step
            # face's normal — one wall centre above and one below.
            # Faces that only have walls in one direction (e.g. the bottom
            # of the part, or a blind-hole cap) are not steps.
            adj_idx = adjacency.get(pf["index"], set())
            face_proj_val = (
                p_pt.X() * pf_n.X() + p_pt.Y() * pf_n.Y() + p_pt.Z() * pf_n.Z()
            )
            has_above = False
            has_below = False
            for wf in face_infos:
                if wf["index"] not in adj_idx:
                    continue
                if wf["type"] != "plane":
                    continue  # only planar walls define step levels; holes/fillets do not
                wpt, wn = _fpn(wf["face"])
                if wn.Magnitude() < 1e-10:
                    continue
                wall_dot = abs(
                    pf_n.X() * wn.X() + pf_n.Y() * wn.Y() + pf_n.Z() * wn.Z()
                )
                if wall_dot > 0.3:
                    continue  # not a perpendicular wall

                wall_proj = (
                    wpt.X() * pf_n.X() + wpt.Y() * pf_n.Y() + wpt.Z() * pf_n.Z()
                )
                if wall_proj > face_proj_val + 0.05:
                    has_above = True
                elif wall_proj < face_proj_val - 0.05:
                    has_below = True

            # Must have walls on both sides of the face
            if not (has_above and has_below):
                continue

            # Depth-ratio guard: reject shallow indents whose reported depth is
            # dominated by the max() formula rather than the real machining offset.
            # A genuine step has raw_step_depth in the same ballpark as depth
            # (ratio <= ~2). A pocket floor that is 3mm from one boundary but
            # 58mm from the other produces depth=58mm but raw=3mm (ratio ~19).
            # Threshold of 5 rejects those while keeping all realistic steps.
            if depth > 5 * raw_step_depth:
                continue

            # Bounding box
            fb = Bnd_Box()
            BRepBndLib.Add_s(pf["face"], fb)
            xmin, ymin, zmin, xmax, ymax, zmax = fb.Get()
            dims = sorted([xmax - xmin, ymax - ymin, zmax - zmin], reverse=True)
            length = dims[0]
            width = dims[1] if len(dims) > 1 else dims[0]

            detected_step_indices.add(pf["index"])
            features.append(FeatureDetail(
                feature_id=_fid(),
                feature_type=FeatureType.STEP,
                confidence=0.70,
                source="rule_based",
                dimensions={
                    "length_mm": round(length, 3),
                    "width_mm": round(width, 3),
                    "depth_mm": round(depth, 3),
                },
                location=_face_center(pf["face"]),
                face_indices=[pf["index"]],
                orientation=_gp_vec_to_list(ref_n),
                key_face_id=_compute_face_persistent_id(pf),
            ))

    return features


# ═══════════════════════════════════════════════════════════════════════════
# Boss / Rib Detection
# ═══════════════════════════════════════════════════════════════════════════

def _detect_bosses_and_ribs(
    face_infos: list[dict],
    adjacency: dict[int, set[int]],
    claimed_faces: set[int] | None = None,
) -> list[FeatureDetail]:
    """Detect bosses (cylindrical protrusions) and ribs (thin linear protrusions).

    Improvements:
    - Uses face orientation to confirm outer cylinders (bosses) vs inner (holes)
    - Respects claimed_faces to avoid re-detecting already-claimed geometry
    - Rib must be adjacent to a larger base surface
    """
    features: list[FeatureDetail] = []
    _claimed = claimed_faces or set()

    # ── Aggregate split cylinders ──────────────────────────────────────
    # OCP often splits a full cylinder into 2 × 180° faces.  Group
    # adjacent forward-orientation cylinders that share the same radius
    # and axis so the angular-span check succeeds.
    _cyl_forward = [
        f for f in face_infos
        if f["type"] == "cylinder"
        and f.get("orientation", "forward") == "forward"
        and f["index"] not in _claimed
        and f.get("radius_mm", 0) >= 1
        and f.get("area_mm2", 0) >= 10
    ]

    def _axis_key(ax):
        """Canonical axis direction (pick the half-space for dedup)."""
        a = tuple(round(v, 4) for v in ax)
        if a < tuple(-v for v in a):
            a = tuple(-v for v in a)
        return a

    boss_groups: list[list[dict]] = []   # each group = list of face dicts
    used_in_group: set[int] = set()

    for fi in _cyl_forward:
        if fi["index"] in used_in_group:
            continue
        r = fi.get("radius_mm", 0)
        ax = fi.get("axis", (0, 0, 1))
        ak = _axis_key(ax)
        group = [fi]
        used_in_group.add(fi["index"])
        # BFS: find directly adjacent cylinders with same radius & axis.
        queue = [fi["index"]]
        while queue:
            cur = queue.pop(0)
            for nb in adjacency.get(cur, set()):
                if nb in used_in_group:
                    continue
                nbf = next((f for f in _cyl_forward if f["index"] == nb), None)
                if nbf is None:
                    continue
                if abs(nbf.get("radius_mm", 0) - r) > 0.05:
                    continue
                if _axis_key(nbf.get("axis", (0, 0, 1))) != ak:
                    continue
                group.append(nbf)
                used_in_group.add(nb)
                queue.append(nb)
        boss_groups.append(group)

    for group in boss_groups:
        total_span = sum(
            abs(f.get("u_range", (0, 0))[1] - f.get("u_range", (0, 0))[0])
            for f in group
        )
        if total_span < math.pi * 1.5:   # < 270° combined → not a boss
            continue

        fi = group[0]  # representative face for centre / axis
        radius = fi.get("radius_mm", 0)
        total_area = sum(f.get("area_mm2", 0) for f in group)
        all_indices = [f["index"] for f in group]

        # Collect adjacent planes from ALL faces in the group
        combined_adj: set[int] = set()
        for f in group:
            combined_adj |= adjacency.get(f["index"], set())
        adj_planes = [
            f for f in face_infos
            if f["index"] in combined_adj and f["type"] == "plane"
        ]
        # Also search through transition faces from every member
        for f in group:
            adj_planes.extend(
                _follow_through_transitions(
                    f["index"], adjacency, face_infos, target_type="plane"
                )
            )
        all_planes = {p["index"]: p for p in adj_planes}.values()

        # Boss: cylindrical face(s) with a cap sitting on a plane
        cross_section = math.pi * radius * radius
        caps = [f for f in all_planes if f["area_mm2"] < cross_section * 1.5]
        base = [f for f in all_planes if f["area_mm2"] > cross_section * 1.2]

        if caps and base:
            circumference = 2 * math.pi * radius
            height = total_area / circumference if circumference > 0 else 0
            try:
                from OCP.gp import gp_Pnt, gp_Vec
                cap_a = BRepAdaptor_Surface(caps[0]["face"])
                cu = (cap_a.FirstUParameter() + cap_a.LastUParameter()) / 2
                cv = (cap_a.FirstVParameter() + cap_a.LastVParameter()) / 2
                cap_pt = gp_Pnt(); _du = gp_Vec(); _dv = gp_Vec()
                cap_a.D1(cu, cv, cap_pt, _du, _dv)

                base_a = BRepAdaptor_Surface(base[0]["face"])
                bu = (base_a.FirstUParameter() + base_a.LastUParameter()) / 2
                bv = (base_a.FirstVParameter() + base_a.LastVParameter()) / 2
                base_pt = gp_Pnt()
                base_a.D1(bu, bv, base_pt, _du, _dv)

                ax = fi.get("axis", (0, 0, 1))
                proj_h = abs(
                    (cap_pt.X() - base_pt.X()) * ax[0]
                    + (cap_pt.Y() - base_pt.Y()) * ax[1]
                    + (cap_pt.Z() - base_pt.Z()) * ax[2]
                )
                if proj_h > 0:
                    height = proj_h
            except Exception:
                pass
            # Determine axis direction from base toward cap (away from body)
            ax = fi.get("axis", (0, 0, 1))
            dot = (
                (cap_pt.X() - base_pt.X()) * ax[0]
                + (cap_pt.Y() - base_pt.Y()) * ax[1]
                + (cap_pt.Z() - base_pt.Z()) * ax[2]
            )
            if dot < 0:
                ax = (-ax[0], -ax[1], -ax[2])
            features.append(FeatureDetail(
                feature_id=_fid(),
                feature_type=FeatureType.BOSS,
                confidence=0.70,
                source="rule_based",
                dimensions={
                    "diameter_mm": round(radius * 2, 3),
                    "height_mm": round(height, 3),
                },
                location=_face_center(fi["face"]),
                face_indices=all_indices,
                orientation=_normalize_axis(ax),
                key_face_id=_compute_face_persistent_id(base[0]),
            ))

    # Rib detection: thin planar faces perpendicular to main body
    planar = [f for f in face_infos if f["type"] == "plane"]
    for fi in planar:
        if fi["index"] in _claimed:
            continue

        # Skip faces adjacent to pocket/slot bottoms — these are pocket
        # walls, not structural ribs.
        adj_idx = adjacency.get(fi["index"], set())
        if adj_idx & _claimed:
            continue

        from OCP.Bnd import Bnd_Box
        from OCP.BRepBndLib import BRepBndLib
        fb = Bnd_Box()
        BRepBndLib.Add_s(fi["face"], fb)
        xmin, ymin, zmin, xmax, ymax, zmax = fb.Get()
        dims = sorted([xmax - xmin, ymax - ymin, zmax - zmin], reverse=True)
        if len(dims) >= 2 and dims[0] > 0 and dims[1] > 0:
            aspect = dims[0] / dims[1]
            if aspect > 5 and fi["area_mm2"] < 200 and dims[1] >= 2.0:
                # Adjacency check: rib must be adjacent to a larger base face
                adj_idx = adjacency.get(fi["index"], set())
                has_base = any(
                    f["area_mm2"] > fi["area_mm2"] * 3
                    for f in face_infos
                    if f["index"] in adj_idx
                )
                if not has_base:
                    continue

                features.append(FeatureDetail(
                    feature_id=_fid(),
                    feature_type=FeatureType.RIB,
                    confidence=0.60,
                    source="rule_based",
                    dimensions={
                        "length_mm": round(dims[0], 3),
                        "height_mm": round(dims[1], 3),
                    },
                    location=_face_center(fi["face"]),
                    face_indices=[fi["index"]],
                    key_face_id=_compute_face_persistent_id(fi),
                ))

    return features


# ═══════════════════════════════════════════════════════════════════════════
# Draft Angle Detection
# ═══════════════════════════════════════════════════════════════════════════

def _detect_tapered_bores(
    face_infos: list[dict],
    adjacency: dict[int, set[int]],
    claimed_faces: set[int],
) -> list[FeatureDetail]:
    """Detect tapered bores: REVERSED cone faces with a bore-range draft angle.

    A tapered bore is a conical inner surface (REVERSED orientation) with
    semi_angle in [BORE_SA_MIN, BORE_SA_MAX].  This range separates:
    - Near-cylindrical (< 0.3°): functionally cylindrical, handled by _detect_holes
    - True tapered bores (0.3°–20°): this detector
    - Countersink angles (25°–55°): handled by _detect_holes adj-cone path
    - Wide bevels (> 55°): handled by _detect_chamfers

    Blind variant — at least one planar face reachable (directly or through
    a torus blend) whose area does not exceed the bore cross-section by more
    than 30 % (area <= pi * r_wide^2 * 1.3).  The floor plane is included in
    face_indices and claimed so later detectors do not re-use it.

    Through variant — no such planar cap exists at the narrow end.  The bore
    is open at both ends; adjacent planes (the surrounding part face) are
    larger than the bore cross-section and are NOT claimed.

    Dimensions emitted
    ------------------
    opening_diameter_mm  : diameter at the wider (mouth) end
    draft_angle_deg      : cone semi-angle (wall taper)
    depth_mm             : axial extent of the conical wall face
    axis                 : unit vector along cone axis (into the bore)
    is_through           : True when open at both ends
    bottom_diameter_mm   : (blind only) diameter at the floor end
    """
    # Semi-angle range that defines a machined tapered bore.
    # Large-area cones (> 1000 mm²) extend to 60° — these are structural
    # conical bowl/cup surfaces, not countersinks.  Countersinks are small
    # (typically < 300 mm²) and are handled by _detect_holes.
    _BORE_SA_MIN_DEG = 0.3
    _BORE_SA_MAX_DEG = 20.0
    _BORE_SA_MAX_LARGE = 60.0
    _BORE_LARGE_AREA = 1000.0

    features: list[FeatureDetail] = []

    for fi in face_infos:
        if fi["index"] in claimed_faces:
            continue
        if fi["type"] != "cone":
            continue
        if fi.get("orientation") != "reversed":
            continue

        semi_angle_deg = abs(fi.get("semi_angle_deg", 0))
        sa_max = _BORE_SA_MAX_LARGE if fi.get("area_mm2", 0) > _BORE_LARGE_AREA else _BORE_SA_MAX_DEG
        if not (_BORE_SA_MIN_DEG <= semi_angle_deg <= sa_max):
            continue

        # Must span at least 270° of revolution to be a proper bore
        is_closed = fi.get("is_closed_u", False)
        u_range = fi.get("u_range")
        if not is_closed:
            if u_range is None:
                continue
            u_span = abs(u_range[1] - u_range[0])
            if u_span < math.pi * 1.5:
                continue

        # Compute opening/bottom diameters and axial depth from the cone adaptor
        try:
            ada = BRepAdaptor_Surface(fi["face"])
            cone_geom = ada.Cone()
            ref_r = cone_geom.RefRadius()
            tan_sa = math.tan(abs(cone_geom.SemiAngle()))
            v_min = ada.FirstVParameter()
            v_max = ada.LastVParameter()
            r_at_vmin = ref_r + v_min * tan_sa
            r_at_vmax = ref_r + v_max * tan_sa
            r_wide = max(r_at_vmin, r_at_vmax)
            r_narrow = min(r_at_vmin, r_at_vmax)
            depth = abs(v_max - v_min)
        except Exception:
            continue

        if r_wide < 1.0:
            continue

        # --- Floor search: blind vs through ---
        # Search direct adjacency only (max_hops=1) for planar caps.  Using
        # max_hops=2 can reach pocket floors that sit two hops away through a
        # large transition torus — e.g. a groove floor below a tapered bore —
        # which incorrectly classifies the bore as blind and claims the groove
        # floor, preventing pocket detectors from finding it.
        # Minimum cap area: 10% of the bore's narrow-end cross-section.  Tiny
        # planes (D-bore slot floors, edge artefacts) adjacent to the bore cone
        # are never real bore caps and must not be claimed.
        cap_area_limit = math.pi * r_wide * r_wide * 1.3
        _min_cap_area = math.pi * r_narrow * r_narrow * 0.10
        candidate_planes = _follow_through_transitions(
            fi["index"], adjacency, face_infos, target_type="plane", max_hops=1
        )
        caps = [
            p for p in candidate_planes
            if _min_cap_area <= p["area_mm2"] <= cap_area_limit
        ]
        is_through = len(caps) == 0

        dims: dict = {
            "opening_diameter_mm": round(r_wide * 2, 3),
            "draft_angle_deg": round(semi_angle_deg, 2),
            "depth_mm": round(depth, 3),
            "axis": [
                round(fi["axis"][0], 6),
                round(fi["axis"][1], 6),
                round(fi["axis"][2], 6),
            ],
            "is_through": is_through,
        }
        if not is_through:
            dims["bottom_diameter_mm"] = round(r_narrow * 2, 3)

        face_indices = [fi["index"]] + [p["index"] for p in caps]
        claimed_faces.add(fi["index"])
        for p in caps:
            claimed_faces.add(p["index"])

        features.append(FeatureDetail(
            feature_id=_fid(),
            feature_type=FeatureType.TAPERED_BORE,
            confidence=0.80,
            source="rule_based",
            dimensions=dims,
            location=_face_center(fi["face"]),
            face_indices=face_indices,
            orientation=_normalize_axis(fi.get("axis")),
            key_face_id=_compute_face_persistent_id(fi),
        ))

    return features


def _detect_tapered_ods(
    face_infos: list[dict],
    adjacency: dict[int, set[int]],
    claimed_faces: set[int],
) -> list[FeatureDetail]:
    """Detect tapered ODs: FORWARD cone faces forming the outer taper of a turned part.

    A tapered OD is a conical outer surface (FORWARD orientation) with
    semi_angle in [0.3°, 20°].  Appears on turned/mill-turn parts such as
    Morse-taper shanks, conical cups, taper bores seen from the outside.

    Must run before _detect_draft_angles so that FORWARD cone faces on turned
    parts are claimed here and not double-counted as draft angles.

    Dimensions emitted
    ------------------
    major_diameter_mm  : diameter at the wider end
    minor_diameter_mm  : diameter at the narrower end
    taper_angle_deg    : cone semi-angle (half-included angle)
    length_mm          : axial extent of the conical face
    axis               : unit vector along cone axis
    """
    # Large-area cones (> 1000 mm²) extend to 60° — conical bowl/cup OD
    # surfaces.  Small cones at this angle are chamfers or countersinks.
    _TAPER_SA_MIN_DEG = 0.3
    _TAPER_SA_MAX_DEG = 20.0
    _TAPER_SA_MAX_LARGE = 60.0
    _TAPER_LARGE_AREA = 1000.0

    features: list[FeatureDetail] = []

    for fi in face_infos:
        if fi["index"] in claimed_faces:
            continue
        if fi["type"] != "cone":
            continue
        if fi.get("orientation") != "forward":
            continue

        semi_angle_deg = abs(fi.get("semi_angle_deg", 0))
        sa_max = _TAPER_SA_MAX_LARGE if fi.get("area_mm2", 0) > _TAPER_LARGE_AREA else _TAPER_SA_MAX_DEG
        if not (_TAPER_SA_MIN_DEG <= semi_angle_deg <= sa_max):
            continue

        # Must span at least 270° of revolution to be a proper OD surface
        is_closed = fi.get("is_closed_u", False)
        u_range = fi.get("u_range")
        if not is_closed:
            if u_range is None:
                continue
            u_span = abs(u_range[1] - u_range[0])
            if u_span < math.pi * 1.5:
                continue

        try:
            ada = BRepAdaptor_Surface(fi["face"])
            cone_geom = ada.Cone()
            ref_r = cone_geom.RefRadius()
            tan_sa = math.tan(abs(cone_geom.SemiAngle()))
            v_min = ada.FirstVParameter()
            v_max = ada.LastVParameter()
            r_at_vmin = ref_r + v_min * tan_sa
            r_at_vmax = ref_r + v_max * tan_sa
            r_wide = max(r_at_vmin, r_at_vmax)
            r_narrow = min(r_at_vmin, r_at_vmax)
            length = abs(v_max - v_min)
        except Exception:
            continue

        if r_wide < 1.0:
            continue

        axis = fi.get("axis", [0.0, 0.0, 1.0])
        dims: dict = {
            "major_diameter_mm": round(r_wide * 2, 3),
            "minor_diameter_mm": round(r_narrow * 2, 3),
            "taper_angle_deg": round(semi_angle_deg, 2),
            "length_mm": round(length, 3),
            "axis": [round(axis[0], 6), round(axis[1], 6), round(axis[2], 6)],
        }

        claimed_faces.add(fi["index"])
        features.append(FeatureDetail(
            feature_id=_fid(),
            feature_type=FeatureType.TAPERED_OD,
            confidence=0.82,
            source="rule_based",
            dimensions=dims,
            location=_face_center(fi["face"]),
            face_indices=[fi["index"]],
            orientation=_normalize_axis(axis),
            key_face_id=_compute_face_persistent_id(fi),
        ))

    return features


def _detect_draft_angles(
    face_infos: list[dict],
    adjacency: dict[int, set[int]],
    claimed_faces: set[int] | None = None,
) -> list[FeatureDetail]:
    """Detect faces with small taper angles (0.5°-10°) indicating draft for molding.

    Improvements:
    - Respects claimed_faces (avoids re-detecting countersink cones)
    - Requires adjacency to a planar wall or pocket face
    """
    features: list[FeatureDetail] = []
    _claimed = claimed_faces or set()

    for fi in face_infos:
        if fi["type"] != "cone":
            continue
        if fi["index"] in _claimed:
            continue

        semi_angle = fi.get("semi_angle_deg", 0)
        if 0.5 < abs(semi_angle) < 10:
            # Context check: draft face should be adjacent to a planar face
            # (directly or through transition faces)
            adj_idx = adjacency.get(fi["index"], set())
            has_adj_plane = any(
                f["type"] == "plane" for f in face_infos if f["index"] in adj_idx
            )
            if not has_adj_plane:
                indirect_planes = _follow_through_transitions(
                    fi["index"], adjacency, face_infos, target_type="plane"
                )
                has_adj_plane = len(indirect_planes) > 0
            if not has_adj_plane:
                continue

            features.append(FeatureDetail(
                feature_id=_fid(),
                feature_type=FeatureType.DRAFT,
                confidence=0.7,
                source="rule_based",
                dimensions={"draft_angle_deg": round(abs(semi_angle), 2)},
                location=_face_center(fi["face"]),
                face_indices=[fi["index"]],
                orientation=_normalize_axis(fi.get("axis")),
                key_face_id=_compute_face_persistent_id(fi),
            ))

    return features


# ═══════════════════════════════════════════════════════════════════════════
# Sheet-Metal Specific Feature Detection
# ═══════════════════════════════════════════════════════════════════════════

def _detect_hems(
    face_infos: list[dict],
    adjacency: dict[int, set[int]],
    thickness_stats: Optional[ThicknessStats],
    claimed_faces: set[int] | None = None,
) -> list[FeatureDetail]:
    """Detect hems: edge folded 180° back onto itself.

    Improvements:
    - Respects claimed_faces to avoid overlap with bend detection
    """
    features: list[FeatureDetail] = []
    _claimed = claimed_faces or set()
    if not thickness_stats or not thickness_stats.is_uniform:
        return features

    thickness = thickness_stats.mean_mm

    for fi in face_infos:
        if fi["type"] != "cylinder":
            continue
        if fi["index"] in _claimed:
            continue

        radius = fi.get("radius_mm", 0)
        if radius > thickness * 1.5:
            continue  # Hem radius should be ≤ thickness

        adj_idx = adjacency.get(fi["index"], set())
        adj_planes = [
            f for f in face_infos
            if f["index"] in adj_idx and f["type"] == "plane"
        ]

        if len(adj_planes) < 2:
            continue

        # Check if adjacent planes are nearly parallel (180° fold)
        from OCP.gp import gp_Pnt, gp_Vec

        def get_normal(face):
            a = BRepAdaptor_Surface(face)
            um = (a.FirstUParameter() + a.LastUParameter()) / 2
            vm = (a.FirstVParameter() + a.LastVParameter()) / 2
            p = gp_Pnt()
            du = gp_Vec()
            dv = gp_Vec()
            a.D1(um, vm, p, du, dv)
            n = du.Crossed(dv)
            if n.Magnitude() > 1e-10:
                n.Normalize()
            return n

        n1 = get_normal(adj_planes[0]["face"])
        n2 = get_normal(adj_planes[1]["face"])
        dot = n1.Dot(n2)

        # For 180° bend, planes should be anti-parallel (dot ≈ -1.0)
        if dot < -0.85:
            features.append(FeatureDetail(
                feature_id=_fid(),
                feature_type=FeatureType.HEM,
                confidence=0.8,
                source="rule_based",
                dimensions={
                    "bend_radius_mm": round(radius, 3),
                },
                location=_face_center(fi["face"]),
                face_indices=[fi["index"]],
            ))

    return features


# ═══════════════════════════════════════════════════════════════════════════
# Lance Detection (Sheet Metal)
# ═══════════════════════════════════════════════════════════════════════════

def _detect_lances(
    face_infos: list[dict],
    adjacency: dict[int, set[int]],
    thickness_stats: Optional[ThicknessStats],
) -> list[FeatureDetail]:
    """Detect lances: narrow elongated openings with a displaced tab.

    A lance is a partial cut where the material is sliced on three sides
    and bent on the fourth, creating a tab.  In B-Rep the *side walls* of
    the lance opening are narrow planar faces **perpendicular** to the
    main sheet surface.  Opposing side-wall pairs with matching position
    and dimensions are grouped into a single lance feature.
    """
    features: list[FeatureDetail] = []

    if not thickness_stats:
        return features

    thickness = thickness_stats.min_mm
    if thickness <= 0:
        return features

    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    from OCP.gp import gp_Pnt, gp_Vec

    # --- helpers ---
    def _face_point_normal(fi):
        a = BRepAdaptor_Surface(fi["face"])
        u = (a.FirstUParameter() + a.LastUParameter()) / 2
        v = (a.FirstVParameter() + a.LastVParameter()) / 2
        pt = gp_Pnt()
        du = gp_Vec()
        dv = gp_Vec()
        a.D1(u, v, pt, du, dv)
        n = du.Crossed(dv)
        if n.Magnitude() > 1e-10:
            n.Normalize()
        return pt, n

    # --- Find top-face normal ---
    planar_faces = [f for f in face_infos if f["type"] == "plane"]
    if len(planar_faces) < 2:
        return features

    top_face = max(planar_faces, key=lambda f: f["area_mm2"])
    _, top_n = _face_point_normal(top_face)

    # --- Collect candidate side walls ---
    # Side walls are small planar faces PERPENDICULAR to the top face normal
    # with high aspect ratio (length of lance / cut depth).
    candidates = []
    for pf in planar_faces:
        if pf["index"] == top_face["index"]:
            continue
        if pf["area_mm2"] > 500:
            continue

        _, pf_n = _face_point_normal(pf)
        dot = abs(pf_n.X() * top_n.X() + pf_n.Y() * top_n.Y() + pf_n.Z() * top_n.Z())
        if dot > 0.3:  # not perpendicular
            continue

        fb = Bnd_Box()
        BRepBndLib.Add_s(pf["face"], fb)
        xmin, ymin, zmin, xmax, ymax, zmax = fb.Get()
        dims = sorted([xmax - xmin, ymax - ymin, zmax - zmin], reverse=True)
        length = dims[0]  # lance length
        cut_depth = dims[1]  # depth of cut through sheet

        if cut_depth < 0.1 or length < 2:
            continue

        # Reject very long faces — lances are typically < 30 mm
        if length > max(30, 2 * thickness):
            continue

        aspect = length / cut_depth
        if aspect < 3:
            continue

        # Cut depth ≈ fraction of sheet thickness (0.1× to 2×)
        if not (0.1 * thickness <= cut_depth <= 2 * thickness):
            continue

        # Reject edge walls: require the face to be adjacent to the main
        # sheet surface (top face or any large parallel face).
        neighbours = adjacency.get(pf["index"], set())
        adjacent_to_main = False
        for ni in neighbours:
            nf = face_infos[ni] if ni < len(face_infos) else None
            if nf and nf["type"] == "plane" and nf["area_mm2"] > 1000:
                _, nn = _face_point_normal(nf)
                ndot = abs(nn.X() * top_n.X() + nn.Y() * top_n.Y() + nn.Z() * top_n.Z())
                if ndot > 0.7:  # parallel to top face
                    adjacent_to_main = True
                    break
        if not adjacent_to_main:
            continue

        center = _face_center(pf["face"])
        candidates.append({
            "index": pf["index"],
            "length": length,
            "cut_depth": cut_depth,
            "aspect": aspect,
            "center": center,
            "normal": (pf_n.X(), pf_n.Y(), pf_n.Z()),
        })

    # --- Pair opposing side walls ---
    # Two side walls belong to the same lance if they have opposite normals,
    # similar dimensions, and are close together (within a few mm).
    paired_lances: list[dict] = []
    used = set()
    for i, a in enumerate(candidates):
        if i in used:
            continue
        best_j = None
        best_dist = float("inf")
        for j, b in enumerate(candidates):
            if j <= i or j in used:
                continue
            # Opposite normals
            ndot = (a["normal"][0] * b["normal"][0]
                    + a["normal"][1] * b["normal"][1]
                    + a["normal"][2] * b["normal"][2])
            if ndot > -0.7:
                continue
            # Similar length and cut depth
            if abs(a["length"] - b["length"]) > 1 or abs(a["cut_depth"] - b["cut_depth"]) > 0.5:
                continue
            # Close together spatially
            dx = a["center"].x - b["center"].x
            dy = a["center"].y - b["center"].y
            dz = a["center"].z - b["center"].z
            dist = (dx * dx + dy * dy + dz * dz) ** 0.5
            if dist < best_dist and dist < 50:  # within 50 mm
                best_dist = dist
                best_j = j

        used.add(i)
        face_indices = [a["index"]]
        lance_width = a["cut_depth"]  # default: single-wall width = cut depth
        if best_j is not None:
            used.add(best_j)
            face_indices.append(candidates[best_j]["index"])
            # Width = distance between the paired opposing walls
            lance_width = best_dist
        else:
            # Unpaired single-wall lance — skip to reduce false positives
            continue

        paired_lances.append({
            "length": a["length"],
            "cut_depth": a["cut_depth"],
            "lance_width": lance_width,
            "center": a["center"],
            "face_indices": face_indices,
        })

    # --- Group co-located lances ---
    # Lances at the same (X, Y) position but different Z are the same
    # physical lance on opposite faces of the sheet channel.  Merge them.
    grouped: list[dict] = []
    merged = [False] * len(paired_lances)
    for i, a in enumerate(paired_lances):
        if merged[i]:
            continue
        group_faces = list(a["face_indices"])
        for j in range(i + 1, len(paired_lances)):
            if merged[j]:
                continue
            b = paired_lances[j]
            # Same XY within tolerance, may differ in Z
            if (abs(a["center"].x - b["center"].x) < 2
                    and abs(a["center"].y - b["center"].y) < 2
                    and abs(a["length"] - b["length"]) < 1):
                group_faces.extend(b["face_indices"])
                merged[j] = True
        grouped.append({**a, "face_indices": group_faces})

    for g in grouped:
        features.append(FeatureDetail(
            feature_id=_fid(),
            feature_type=FeatureType.LANCE,
            confidence=0.8,
            source="rule_based",
            dimensions={
                "length_mm": round(g["length"], 3),
                "width_mm": round(g["lance_width"], 3),
                "depth_mm": round(g["cut_depth"], 3),
            },
            location=g["center"],
            face_indices=g["face_indices"],
        ))

    return features


# ═══════════════════════════════════════════════════════════════════════════
# Emboss / Coin Detection (Sheet Metal)
# ═══════════════════════════════════════════════════════════════════════════

def _detect_embosses(
    face_infos: list[dict],
    adjacency: dict[int, set[int]],
    thickness_stats: Optional[ThicknessStats],
    claimed_faces: set[int] | None = None,
) -> list[FeatureDetail]:
    """Detect embosses: shallow circular or rectangular deformations.

    In B-Rep these appear as a small planar face offset from the main
    surface by less than the sheet thickness, surrounded by cylindrical
    or planar wall faces.  The depth-to-diameter (or depth-to-width)
    ratio is low (< 0.3).
    """
    features: list[FeatureDetail] = []

    if not thickness_stats:
        return features

    thickness = thickness_stats.min_mm
    if thickness <= 0:
        return features

    _claimed = claimed_faces or set()

    # Cylindrical faces that are shallow (depth < thickness) with a cap
    for fi in face_infos:
        if fi["index"] in _claimed:
            continue

        if fi["type"] != "cylinder":
            continue

        radius = fi.get("radius_mm", 0)
        if radius < 0.5:
            continue

        diameter = radius * 2
        circumference = 2 * math.pi * radius
        depth = fi["area_mm2"] / circumference if circumference > 0 else 0

        # Emboss: shallow depth relative to diameter and close to sheet thickness
        ratio = depth / diameter if diameter > 0 else 999
        if ratio >= 0.3:
            continue  # Too deep for an emboss

        if depth > thickness * 2:
            continue  # Too deep

        # Check for a cap (adjacent planar face smaller than the circle area
        # whose normal is roughly parallel to the cylinder axis).
        sa = BRepAdaptor_Surface(fi["face"])
        cyl_ax = sa.Cylinder().Axis().Direction()
        adj_idx = adjacency.get(fi["index"], set())
        caps = []
        for f in face_infos:
            if f["index"] not in adj_idx or f["type"] != "plane":
                continue
            if f["area_mm2"] >= math.pi * radius * radius * 1.5:
                continue
            # Cap normal must be roughly parallel to cylinder axis
            cap_sa = BRepAdaptor_Surface(f["face"])
            cap_pln = cap_sa.Plane()
            cap_n = cap_pln.Axis().Direction()
            dot = abs(cap_n.X() * cyl_ax.X() + cap_n.Y() * cyl_ax.Y() + cap_n.Z() * cyl_ax.Z())
            if dot < 0.7:
                continue  # Not a true cap — likely a wall face (fillet/round)
            caps.append(f)

        if caps:
            features.append(FeatureDetail(
                feature_id=_fid(),
                feature_type=FeatureType.EMBOSS,
                confidence=0.75,
                source="rule_based",
                dimensions={
                    "diameter_mm": round(diameter, 3),
                    "depth_mm": round(depth, 3),
                },
                location=_face_center(fi["face"]),
                face_indices=[fi["index"]],
            ))

    return features


# ═══════════════════════════════════════════════════════════════════════════
# Flange Detection (Sheet Metal)
# ═══════════════════════════════════════════════════════════════════════════

def _detect_flanges(
    face_infos: list[dict],
    adjacency: dict[int, set[int]],
    thickness_stats: Optional[ThicknessStats],
    claimed_faces: set[int] | None = None,
    bend_cyl_groups: list[set[int]] | None = None,
) -> list[FeatureDetail]:
    """Detect flanges: planar faces perpendicular to main body connected via bend.

    A flange is a flat extension that is bent up/down from the main sheet.
    It shows up as a planar face adjacent to a cylindrical bend face,
    oriented roughly perpendicular to the main (largest) planar face.

    ``bend_cyl_groups`` is a list of sets, one per detected bend, each
    containing the cylinder face indices for that bend.  A valid flange
    must be adjacent to cylinders from exactly ONE bend group (faces
    spanning multiple bends are end-webs, not flanges).
    """
    features: list[FeatureDetail] = []

    if not thickness_stats:
        return features

    from OCP.gp import gp_Pnt, gp_Vec
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    planar_faces = [f for f in face_infos if f["type"] == "plane"]
    if len(planar_faces) < 2:
        return features

    # Main face = largest planar face
    main_face = max(planar_faces, key=lambda f: f["area_mm2"])

    def get_normal(face):
        a = BRepAdaptor_Surface(face)
        um = (a.FirstUParameter() + a.LastUParameter()) / 2
        vm = (a.FirstVParameter() + a.LastVParameter()) / 2
        p = gp_Pnt()
        du = gp_Vec()
        dv = gp_Vec()
        a.D1(um, vm, p, du, dv)
        n = du.Crossed(dv)
        if n.Magnitude() > 1e-10:
            n.Normalize()
        return n

    main_normal = get_normal(main_face["face"])
    _claimed = claimed_faces or set()

    for pf in planar_faces:
        if pf["index"] == main_face["index"]:
            continue
        if pf["index"] in _claimed:
            continue

        # Flange should be roughly perpendicular to main face
        pf_normal = get_normal(pf["face"])
        dot = abs(main_normal.Dot(pf_normal))
        if dot > 0.3:
            continue  # Not perpendicular enough

        # Must be adjacent to a cylindrical face that was detected as a
        # bend.  The adjacent bend cylinders must all belong to the SAME
        # physical bend — faces spanning cylinders from multiple bends
        # are end-webs, not flanges.
        adj_idx = adjacency.get(pf["index"], set())
        _bend_groups = bend_cyl_groups or []
        # Which bend groups does this face touch?
        touched_groups = set()
        for g_idx, group in enumerate(_bend_groups):
            if adj_idx & group:
                touched_groups.add(g_idx)
        if len(touched_groups) != 1:
            continue  # no bend adjacency, or spans multiple bends

        # Skip faces claimed by other detectors UNLESS they are adjacent
        # to bend cylinders.  The bend-adjacency check above is strong
        # enough to confirm flanges; earlier detectors (e.g. slot) may
        # have incorrectly claimed the same face.
        if pf["index"] in _claimed and not touched_groups:
            continue

        # Compute dimensions
        fb = Bnd_Box()
        BRepBndLib.Add_s(pf["face"], fb)
        xmin, ymin, zmin, xmax, ymax, zmax = fb.Get()
        dims = sorted([xmax - xmin, ymax - ymin, zmax - zmin], reverse=True)
        flange_length = dims[0]
        flange_height = dims[1] if len(dims) > 1 else 0

        if flange_length < 5 or flange_height < 2:
            continue

        # Flange height should be reasonable for sheet metal forming.
        # Typical flanges are 3–50mm; reject if disproportionately large
        # relative to sheet thickness (> 15× thickness is unlikely a flange).
        thickness = thickness_stats.min_mm if thickness_stats else 0
        if thickness > 0 and flange_height > 15 * thickness:
            continue

        features.append(FeatureDetail(
            feature_id=_fid(),
            feature_type=FeatureType.FLANGE,
            confidence=0.75,
            source="rule_based",
            dimensions={
                "length_mm": round(flange_length, 3),
                "height_mm": round(flange_height, 3),
            },
            location=_face_center(pf["face"]),
            face_indices=[pf["index"]],
        ))

    # ── Deduplicate opposite faces of the same physical flange ──
    # Each sheet-metal flange has two surfaces (inner + outer).  They
    # are anti-parallel, ~thickness apart, and share the same bounding-
    # box dimensions.  Keep only one per physical flange.
    thickness = thickness_stats.mean_mm if thickness_stats else 0
    merged: list[FeatureDetail] = []
    used = [False] * len(features)
    for i, a in enumerate(features):
        if used[i]:
            continue
        a_n = get_normal(face_infos[a.face_indices[0]]["face"])
        for j in range(i + 1, len(features)):
            if used[j]:
                continue
            b = features[j]
            # Same dimensions (length & height)?
            if (a.dimensions.get("length_mm") != b.dimensions.get("length_mm") or
                    a.dimensions.get("height_mm") != b.dimensions.get("height_mm")):
                continue
            # Anti-parallel normals?
            b_n = get_normal(face_infos[b.face_indices[0]]["face"])
            dot = a_n.X() * b_n.X() + a_n.Y() * b_n.Y() + a_n.Z() * b_n.Z()
            if dot > -0.7:
                continue  # not anti-parallel
            # Centers ~thickness apart along normal?
            a_loc = a.location
            b_loc = b.location
            if a_loc and b_loc:
                dx = a_loc.x - b_loc.x
                dy = a_loc.y - b_loc.y
                dz = a_loc.z - b_loc.z
                dist = (dx**2 + dy**2 + dz**2) ** 0.5
                if thickness > 0 and dist > thickness * 2:
                    continue
            # Merge: keep a, skip b
            used[j] = True
            a.face_indices.extend(b.face_indices)
            break
        merged.append(a)

    return merged


# ═══════════════════════════════════════════════════════════════════════════
# Perforation Pattern Detection (Sheet Metal)
# ═══════════════════════════════════════════════════════════════════════════

def _detect_perforation_pattern(
    face_infos: list[dict],
    adjacency: dict[int, set[int]],
    claimed_faces: set[int] | None = None,
) -> list[FeatureDetail]:
    """Detect perforation patterns: regular arrays of identical small holes.

    If ≥ 6 cylindrical faces have the same radius and their centers form
    a regular grid or linear pattern, classify as a perforation pattern.
    """
    features: list[FeatureDetail] = []

    from collections import defaultdict
    import itertools

    _claimed = claimed_faces or set()

    # Group cylindrical faces by radius (rounded to 0.1mm)
    radius_groups: dict[float, list[dict]] = defaultdict(list)
    for fi in face_infos:
        if fi["index"] in _claimed:
            continue
        if fi["type"] == "cylinder":
            r = round(fi.get("radius_mm", 0), 1)
            if 0.5 <= r <= 20:
                radius_groups[r].append(fi)

    for radius, group in radius_groups.items():
        if len(group) < 6:
            continue

        # Get centers
        centers = []
        indices = []
        for fi in group:
            c = _face_center(fi["face"])
            if c:
                centers.append(c)
                indices.append(fi["index"])

        if len(centers) < 6:
            continue

        # Check for regularity: compute nearest-neighbour distances
        dists = []
        for i, c1 in enumerate(centers):
            min_d = float("inf")
            for j, c2 in enumerate(centers):
                if i == j:
                    continue
                d = math.sqrt((c1.x - c2.x) ** 2 + (c1.y - c2.y) ** 2 + (c1.z - c2.z) ** 2)
                min_d = min(min_d, d)
            dists.append(min_d)

        if not dists:
            continue

        mean_d = sum(dists) / len(dists)
        std_d = (sum((d - mean_d) ** 2 for d in dists) / len(dists)) ** 0.5

        # Regular pattern: low coefficient of variation on NN distances
        cv = std_d / mean_d if mean_d > 0 else 999
        if cv < 0.3:
            avg_center = Point3D(
                x=round(sum(c.x for c in centers) / len(centers), 3),
                y=round(sum(c.y for c in centers) / len(centers), 3),
                z=round(sum(c.z for c in centers) / len(centers), 3),
            )
            features.append(FeatureDetail(
                feature_id=_fid(),
                feature_type=FeatureType.PERFORATION_PATTERN,
                confidence=0.8,
                source="rule_based",
                dimensions={
                    "hole_diameter_mm": round(radius * 2, 3),
                    "hole_count": len(centers),
                    "pitch_mm": round(mean_d, 3),
                },
                location=avg_center,
                face_indices=indices,
            ))

    return features


# ═══════════════════════════════════════════════════════════════════════════
# Undercut Detection (Casting / Injection Molding)
# ═══════════════════════════════════════════════════════════════════════════

def _detect_undercuts(
    face_infos: list[dict],
    adjacency: dict[int, set[int]],
    claimed_faces: set[int],
) -> list[FeatureDetail]:
    """Detect undercuts: concave cylindrical pockets whose axis is
    perpendicular to the primary pull direction (assumed Z-axis).

    An undercut prevents straight die/mold extraction and requires
    side actions or slides.  In B-Rep it appears as a cylindrical
    face with axis in the XY plane (perpendicular to Z) that opens
    into the part body (REVERSED orientation = inner surface).
    """
    features: list[FeatureDetail] = []

    # Derive the mold pull direction from the dominant axis of full-revolution
    # cylinders (the spindle axis vote used by _detect_lathe_bores).  This
    # makes the detector orientation-agnostic: parts not modelled with Z-up
    # still get correct undercut detection.  Fall back to Z if no cylinders.
    _pull_dir: tuple[float, float, float] = (0.0, 0.0, 1.0)
    _pull_votes: list[tuple[float, float, float]] = []
    for _fi in face_infos:
        if _fi["type"] != "cylinder":
            continue
        if not _fi.get("is_closed_u", False):
            _ur = _fi.get("u_range")
            if _ur is None or abs(_ur[1] - _ur[0]) < math.pi * 1.5:
                continue
        _ax = _fi.get("axis")
        if _ax:
            _pull_votes.append(_ax)
    if _pull_votes:
        _ref = _pull_votes[0]
        _sx, _sy, _sz = 0.0, 0.0, 0.0
        for _v in _pull_votes:
            _s = 1.0 if (_v[0]*_ref[0] + _v[1]*_ref[1] + _v[2]*_ref[2]) >= 0 else -1.0
            _sx += _s * _v[0]; _sy += _s * _v[1]; _sz += _s * _v[2]
        _mag = math.sqrt(_sx**2 + _sy**2 + _sz**2)
        if _mag > 1e-6:
            _pull_dir = (_sx/_mag, _sy/_mag, _sz/_mag)

    for fi in face_infos:
        if fi["index"] in claimed_faces:
            continue
        if fi["type"] != "cylinder":
            continue
        # Must be inner (concave) surface
        if fi.get("orientation") != "reversed":
            continue
        # Skip partial-arc cylinders (outer curved surfaces, not real undercuts).
        # A genuine undercut bore spans at least 270° around its axis.
        if not fi.get("is_closed_u", False):
            _ur = fi.get("u_range")
            if _ur is None or abs(_ur[1] - _ur[0]) < math.pi * 1.5:
                continue
        axis = fi.get("axis")
        if not axis:
            continue
        # Axis must be roughly perpendicular to the mold pull direction.
        # |axis · pull_dir| < 0.3 means within ~73° of the parting plane.
        _pull_dot = abs(axis[0]*_pull_dir[0] + axis[1]*_pull_dir[1] + axis[2]*_pull_dir[2])
        if _pull_dot > 0.3:
            continue
        radius = fi.get("radius_mm", 0)
        if radius <= 0 or radius > 50:
            continue

        center = _face_center(fi["face"])
        features.append(FeatureDetail(
            feature_id=_fid(),
            feature_type=FeatureType.UNDERCUT,
            confidence=0.55,
            source="rule_based",
            dimensions={
                "diameter_mm": round(radius * 2, 3),
                "axis": list(axis),
            },
            location=center,
            face_indices=[fi["index"]],
        ))
        claimed_faces.add(fi["index"])

    return features


# ═══════════════════════════════════════════════════════════════════════════
# Groove Detection (Turned / Machined Parts)
# ═══════════════════════════════════════════════════════════════════════════

def _detect_grooves(
    face_infos: list[dict],
    adjacency: dict[int, set[int]],
    claimed_faces: set[int],
) -> list[FeatureDetail]:
    """Detect grooves (O-ring grooves, snap-ring grooves, relief grooves).

    A groove on a turned part is a narrow annular recess: a small
    cylindrical face (REVERSED = inner cut) flanked on both sides
    by larger cylindrical faces of a bigger radius with aligned axes.
    """
    features: list[FeatureDetail] = []
    for fi in face_infos:
        if fi["index"] in claimed_faces:
            continue
        if fi["type"] != "cylinder":
            continue
        if fi.get("orientation") != "reversed":
            continue
        axis = fi.get("axis")
        if not axis:
            continue
        radius = fi.get("radius_mm", 0)
        if radius <= 0:
            continue
        # Check neighbours: need at least 2 cylindrical neighbours
        # with larger radius and aligned axis
        neighbours = adjacency.get(fi["index"], set())
        flanking = []
        for ni in neighbours:
            if ni >= len(face_infos):
                continue
            nf = face_infos[ni]
            if nf["type"] != "cylinder":
                continue
            n_axis = nf.get("axis")
            n_radius = nf.get("radius_mm", 0)
            if not n_axis or n_radius <= 0:
                continue
            if n_radius <= radius:
                continue
            if _axes_aligned(axis, n_axis, tol=0.95):
                flanking.append(nf)

        if len(flanking) < 2:
            continue

        groove_depth = min(nf.get("radius_mm", 0) for nf in flanking) - radius
        if groove_depth < 0.1:
            continue

        # Reject false positives where flanking cylinders are far larger than
        # the groove (cross-hole / pocket-wall adjacency artefacts have ratios
        # well above 20).  Legitimate grooves — including small O-ring grooves
        # on large-OD shafts (e.g. r=3mm groove on Ø60mm OD → ratio≈10) —
        # have ratios ≤ ~15, so a 20× limit gives comfortable headroom.
        max_flank_r = max(nf.get("radius_mm", 0) for nf in flanking)
        if radius > 0 and max_flank_r / radius > 20.0:
            continue
        # Depth guard: very large absolute depths (≥ 50mm) indicate the
        # "groove" spans unrelated features (bore-to-OD pseudo-adjacency on
        # disc parts produced 145–217mm artifacts).  50mm covers all real
        # machined grooves including deep hydraulic relief grooves.
        if groove_depth > 50:
            continue

        center = _face_center(fi["face"])
        features.append(FeatureDetail(
            feature_id=_fid(),
            feature_type=FeatureType.GROOVE,
            confidence=0.65,
            source="rule_based",
            dimensions={
                "groove_diameter_mm": round(radius * 2, 3),
                "groove_depth_mm": round(groove_depth, 3),
            },
            location=center,
            face_indices=[fi["index"]],
            orientation=_normalize_axis(axis),
            key_face_id=_compute_face_persistent_id(fi),
        ))
        claimed_faces.add(fi["index"])

    return features


# ═══════════════════════════════════════════════════════════════════════════
# Deep Draw Detection (Sheet Metal)
# ═══════════════════════════════════════════════════════════════════════════

def _detect_deep_draw(
    face_infos: list[dict],
    adjacency: dict[int, set[int]],
    thickness_stats: Optional[ThicknessStats],
    claimed_faces: set[int],
) -> list[FeatureDetail]:
    """Detect deep-drawn features on sheet metal.

    A deep draw is a cup/dome formed by pressing sheet metal into a die.
    In B-Rep it appears as a group of non-planar faces (cylinder + torus
    blend at the bottom) that are FORWARD orientation (outer surface)
    and connected, with a height significantly larger than the sheet
    thickness.
    """
    features: list[FeatureDetail] = []
    if not thickness_stats or thickness_stats.min_mm <= 0:
        return features

    thickness = thickness_stats.min_mm

    # Derive sheet normal from the largest planar face (the main sheet
    # surface).  This replaces the hardcoded Z-axis assumption so deep-draw
    # detection works regardless of part orientation in the STEP file.
    _sheet_normal: tuple[float, float, float] = (0.0, 0.0, 1.0)
    _max_plane_area = 0.0
    for _fi in face_infos:
        if _fi["type"] == "plane" and _fi["area_mm2"] > _max_plane_area:
            try:
                _, _pn = _face_point_normal(_fi["face"])
                _pmag = _pn.Magnitude()
                if _pmag > 1e-6:
                    _max_plane_area = _fi["area_mm2"]
                    _sheet_normal = (_pn.X()/_pmag, _pn.Y()/_pmag, _pn.Z()/_pmag)
            except Exception:
                pass

    for fi in face_infos:
        if fi["index"] in claimed_faces:
            continue
        if fi["type"] != "cylinder":
            continue
        if fi.get("orientation") != "forward":
            continue
        if fi.get("is_closed_u") or fi.get("is_closed_v"):
            # Full cylinder — more likely a hole, not a draw wall
            continue
        radius = fi.get("radius_mm", 0)
        if radius <= 0 or radius > 200:
            continue
        axis = fi.get("axis")
        if not axis:
            continue
        # Draw axis must align with the sheet normal (the cylinder wall wraps
        # around the draw direction, so its axis runs perpendicular to the sheet).
        _draw_dot = abs(axis[0]*_sheet_normal[0] + axis[1]*_sheet_normal[1] + axis[2]*_sheet_normal[2])
        if _draw_dot < 0.7:
            continue

        # Estimate draw height from face extent
        adaptor = BRepAdaptor_Surface(fi["face"])
        u_range = adaptor.LastUParameter() - adaptor.FirstUParameter()
        v_range = adaptor.LastVParameter() - adaptor.FirstVParameter()
        # For a cylinder, height is along V
        draw_height = v_range
        if draw_height < 2 * thickness:
            continue  # Too shallow — not a deep draw
        if draw_height > 20 * thickness:
            continue  # Too tall — structural tube, not a draw

        center = _face_center(fi["face"])
        features.append(FeatureDetail(
            feature_id=_fid(),
            feature_type=FeatureType.DEEP_DRAW,
            confidence=0.55,
            source="rule_based",
            dimensions={
                "diameter_mm": round(radius * 2, 3),
                "depth_mm": round(draw_height, 3),
            },
            location=center,
            face_indices=[fi["index"]],
        ))
        claimed_faces.add(fi["index"])

    return features


# ═══════════════════════════════════════════════════════════════════════════
# Bead Detection (Sheet Metal Stiffener)
# ═══════════════════════════════════════════════════════════════════════════

def _detect_beads(
    face_infos: list[dict],
    adjacency: dict[int, set[int]],
    thickness_stats: Optional[ThicknessStats],
    claimed_faces: set[int],
) -> list[FeatureDetail]:
    """Detect beads (stiffening ribs on sheet metal).

    A bead is a narrow linear embossment in the sheet surface used for
    structural rigidity.  In B-Rep it appears as a sequence of narrow
    cylindrical faces (FORWARD = raised) with matching axes, flanked
    by the main planar sheet surface.  Width is typically 2-10x sheet
    thickness and height is 0.5-3x thickness.
    """
    features: list[FeatureDetail] = []
    if not thickness_stats or thickness_stats.min_mm <= 0:
        return features

    thickness = thickness_stats.min_mm

    for fi in face_infos:
        if fi["index"] in claimed_faces:
            continue
        if fi["type"] != "cylinder":
            continue
        if fi.get("orientation") != "forward":
            continue
        # Full closed cylinders are tubes/pipes, not beads
        if fi.get("is_closed_u") or fi.get("is_closed_v"):
            continue
        radius = fi.get("radius_mm", 0)
        if radius <= 0:
            continue
        # Bead radius ≈ 0.5–5× sheet thickness
        if not (0.5 * thickness <= radius <= 5 * thickness):
            continue
        # Must be adjacent to a large planar face (the sheet surface)
        neighbours = adjacency.get(fi["index"], set())
        adj_planar = False
        for ni in neighbours:
            if ni >= len(face_infos):
                continue
            nf = face_infos[ni]
            if nf["type"] == "plane" and nf["area_mm2"] > 100:
                adj_planar = True
                break
        if not adj_planar:
            continue

        # Check elongation — beads are long and narrow
        adaptor = BRepAdaptor_Surface(fi["face"])
        u_range = adaptor.LastUParameter() - adaptor.FirstUParameter()
        v_range = adaptor.LastVParameter() - adaptor.FirstVParameter()
        length = max(u_range, v_range)
        width = min(u_range, v_range) * radius  # arc width
        if length < 5 or width > 10 * thickness:
            continue
        # Beads are localised stiffeners, not long structural tubes
        if length > 300:
            continue
        # Length-to-diameter ratio: beads are short relative to their
        # cross-section.  Tubes/structural members have L/D >> 5.
        if radius > 0 and length / (2 * radius) > 10:
            continue

        center = _face_center(fi["face"])
        features.append(FeatureDetail(
            feature_id=_fid(),
            feature_type=FeatureType.BEAD,
            confidence=0.55,
            source="rule_based",
            dimensions={
                "length_mm": round(length, 3),
                "width_mm": round(width, 3),
                "bead_radius_mm": round(radius, 3),
            },
            location=center,
            face_indices=[fi["index"]],
        ))
        claimed_faces.add(fi["index"])

    return features


# ═══════════════════════════════════════════════════════════════════════════
# Lathe OD / Bore-ID Step Detection
# ═══════════════════════════════════════════════════════════════════════════

def _detect_lathe_od_steps(
    face_infos: list[dict],
    adjacency: dict[int, set[int]],
    claimed_faces: set[int],
) -> list[FeatureDetail]:
    """Detect OD steps and bore-ID steps on turned/mill-turn parts.

    An OD step is a pair of co-axial FORWARD cylinders at different diameters
    connected by a FORWARD planar shoulder face perpendicular to their shared
    axis.  A bore-ID step is the same geometry with REVERSED orientation.

    Dimensions emitted
    ------------------
    diameter_mm      — larger cylinder diameter
    step_diameter_mm — smaller cylinder diameter
    height_mm        — axial width of the shoulder face
    axis             — cylinder axis unit vector
    """
    from OCP.gp import gp_Pnt, gp_Vec
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    features: list[FeatureDetail] = []
    _claimed = claimed_faces  # mutated in-place

    # Build index → face_info map for O(1) lookup
    fi_by_idx: dict[int, dict] = {fi["index"]: fi for fi in face_infos}

    # Proportional minimum OD radius: 5% of the largest forward cylinder
    # on this part, with a 1mm absolute floor.  This replaces the fixed
    # 10mm threshold so miniature lathe parts (e.g. Ø6mm shafts) still
    # get their OD steps detected.
    _max_od_r = max(
        (f.get("radius_mm", 0) for f in face_infos
         if f["type"] == "cylinder" and f.get("orientation", "forward") == "forward"),
        default=10.0,
    )
    _min_od_r = max(1.0, _max_od_r * 0.05)

    # Only process FORWARD (OD) cylinders.  REVERSED bore cylinders are left for
    # _detect_lathe_bores (spindle-aligned turned bores) and _detect_holes (cross
    # drills / remaining holes).  The shoulder between different bore diameters
    # (a REVERSED annular plane) is picked up by _detect_steps.
    cyls: list[dict] = []
    for fi in face_infos:
        if fi["index"] in _claimed:
            continue
        if fi["type"] != "cylinder":
            continue
        if fi.get("orientation", "forward") != "forward":
            continue
        radius = fi.get("radius_mm", 0)
        if radius < _min_od_r:
            continue
        is_closed = fi.get("is_closed_u", False)
        if not is_closed:
            u_range = fi.get("u_range")
            if u_range is None:
                continue
            # Large OD cylinders (≥100mm radius) may be partial arcs because
            # milled flats cut into the OD.  Relax to 90° — at this scale any
            # arc is unambiguously an OD surface, not a drilled hole.
            min_arc = math.pi * 1.5 if radius < 100.0 else math.pi * 0.5
            if abs(u_range[1] - u_range[0]) < min_arc:
                continue
        cyls.append(fi)

    used: set[int] = set()

    for fi1 in cyls:
        if fi1["index"] in used:
            continue

        r1 = fi1.get("radius_mm", 0)
        axis1 = fi1.get("axis", (0.0, 0.0, 1.0))
        adj1 = adjacency.get(fi1["index"], set())

        # Collect shoulder candidates: direct plane neighbours of fi1, plus any
        # plane reachable through exactly one cone or torus transition face.
        # This handles OD steps where a chamfer or fillet separates the OD
        # cylinder from the flat annular shoulder (e.g. broken-edge chamfer).
        # Each entry: (shoulder_face_info, set_of_intermediate_face_indices)
        _shoulder_cands: list[tuple[dict, set[int]]] = []
        for _si in adj1:
            _sf_c = fi_by_idx.get(_si)
            if _sf_c is None or _sf_c["index"] in _claimed:
                continue
            if _sf_c["type"] == "plane":
                _shoulder_cands.append((_sf_c, set()))
            elif _sf_c["type"] in ("cone", "torus"):
                for _ssi in adjacency.get(_si, set()):
                    _ssf = fi_by_idx.get(_ssi)
                    if (
                        _ssf
                        and _ssf["type"] == "plane"
                        and _ssf["index"] not in _claimed
                        and _ssf["index"] != fi1["index"]
                    ):
                        _shoulder_cands.append((_ssf, {_si}))

        for sf, _via in _shoulder_cands:
            if sf["index"] in _claimed:
                continue

            # Shoulder normal must align with the cylinder axis.
            # Orientation (FORWARD/REVERSED) is intentionally not checked — STEP
            # exports from different CAD kernels flip annular shoulder normals
            # inconsistently; the dot-product guard below is the real filter.
            try:
                sf_ada = BRepAdaptor_Surface(sf["face"])
                um = (sf_ada.FirstUParameter() + sf_ada.LastUParameter()) / 2
                vm = (sf_ada.FirstVParameter() + sf_ada.LastVParameter()) / 2
                p = gp_Pnt()
                du = gp_Vec()
                dv = gp_Vec()
                sf_ada.D1(um, vm, p, du, dv)
                n = du.Crossed(dv)
                if n.Magnitude() < 1e-10:
                    continue
                n.Normalize()
                sn = (n.X(), n.Y(), n.Z())
            except Exception:
                continue

            dot_sn = abs(sn[0] * axis1[0] + sn[1] * axis1[1] + sn[2] * axis1[2])
            if dot_sn < 0.85:
                continue

            # Look for the second OD cylinder adjacent to the shoulder.
            # Expand 1 hop through any cone or torus adjacent to the shoulder to
            # handle the symmetric case where a chamfer sits on fi2's side too.
            adj_shoulder = adjacency.get(sf["index"], set())
            _adj_exp = set(adj_shoulder)
            for _asi in list(adj_shoulder):
                _asf = fi_by_idx.get(_asi)
                if _asf and _asf["type"] in ("cone", "torus"):
                    _adj_exp.update(adjacency.get(_asi, set()))

            for fi2 in cyls:
                if fi2["index"] == fi1["index"]:
                    continue
                if fi2["index"] in used:
                    continue
                if fi2["index"] not in _adj_exp:
                    continue

                r2 = fi2.get("radius_mm", 0)
                if abs(r1 - r2) < 2.0:
                    continue  # negligible diameter difference

                axis2 = fi2.get("axis", (0.0, 0.0, 1.0))
                if abs(axis1[0]*axis2[0] + axis1[1]*axis2[1] + axis1[2]*axis2[2]) < 0.95:
                    continue  # axes not aligned

                # Axial extent of the shoulder face
                try:
                    sfb = Bnd_Box()
                    BRepBndLib.Add_s(sf["face"], sfb)
                    sx1, sy1, sz1, sx2, sy2, sz2 = sfb.Get()
                    extents = [sx2 - sx1, sy2 - sy1, sz2 - sz1]
                    ax_idx = max(range(3), key=lambda k: abs(axis1[k]))
                    axial_h = max(extents[ax_idx], 0.5)
                except Exception:
                    axial_h = 1.0

                r_large = max(r1, r2)
                r_small = min(r1, r2)
                dims = {
                    "diameter_mm": round(r_large * 2, 3),
                    "step_diameter_mm": round(r_small * 2, 3),
                    "height_mm": round(axial_h, 3),
                    "axis": [round(axis1[0], 6), round(axis1[1], 6), round(axis1[2], 6)],
                }
                face_indices = [fi1["index"], sf["index"], fi2["index"]]
                for idx in face_indices:
                    _claimed.add(idx)
                used.add(fi1["index"])
                used.add(fi2["index"])

                features.append(FeatureDetail(
                    feature_id=_fid(),
                    feature_type=FeatureType.LATHE_OD,
                    confidence=0.82,
                    source="rule_based",
                    dimensions=dims,
                    location=_face_center(sf["face"]),
                    face_indices=face_indices,
                    orientation=_normalize_axis(axis1),
                    key_face_id=_compute_face_persistent_id(fi1),
                ))
                break  # one step per fi1–shoulder pair

            if fi1["index"] in used:
                break  # fi1 claimed; move to next shoulder candidate

    return features


def _detect_lathe_bores(
    face_infos: list[dict],
    adjacency: dict[int, set[int]],
    claimed_faces: set[int],
) -> list[FeatureDetail]:
    """Detect turned bore-ID features on lathe / mill-turn parts.

    Targets full-revolution REVERSED cylinders whose axis aligns with the
    part spindle axis (derived as the dominant axis of all full-revolution
    cylinders).  These are boring-bar / internal-turning operations, distinct
    from drilled cross holes which _detect_holes handles as milling features.

    Emits THROUGH_HOLE (open-ended bore) or BLIND_HOLE (bore with flat floor).
    Multi-cylinder assemblies (counterbores, countersinks) are left to
    _detect_holes so their stacked geometry is resolved correctly.
    """
    from OCP.gp import gp_Pnt, gp_Vec

    features: list[FeatureDetail] = []

    # ── Derive spindle axis from the dominant axis of full-revolution cylinders ──
    axis_votes: dict[str, int] = {"x": 0, "y": 0, "z": 0}
    for fi in face_infos:
        if fi["type"] != "cylinder":
            continue
        is_closed = fi.get("is_closed_u", False)
        if not is_closed:
            ur = fi.get("u_range")
            if ur is None or abs(ur[1] - ur[0]) < math.pi * 1.5:
                continue
        ax, ay, az = abs(fi.get("axis", (0.0, 0.0, 1.0))[0]), abs(fi.get("axis", (0.0, 0.0, 1.0))[1]), abs(fi.get("axis", (0.0, 0.0, 1.0))[2])
        if ax >= ay and ax >= az:
            axis_votes["x"] += 1
        elif ay >= ax and ay >= az:
            axis_votes["y"] += 1
        else:
            axis_votes["z"] += 1

    dominant = max(axis_votes, key=lambda k: axis_votes[k])
    if axis_votes[dominant] == 0:
        return []
    if dominant == "x":
        spindle_axis: tuple[float, float, float] = (1.0, 0.0, 0.0)
    elif dominant == "y":
        spindle_axis = (0.0, 1.0, 0.0)
    else:
        spindle_axis = (0.0, 0.0, 1.0)

    AXIS_DOT_MIN = 0.85  # bore must align strongly with spindle

    # ── Claim full-revolution, spindle-aligned REVERSED cylinders as bores ──
    for fi in face_infos:
        if fi["index"] in claimed_faces:
            continue
        if fi["type"] != "cylinder":
            continue
        if fi.get("orientation", "forward") != "reversed":
            continue

        # Accept arcs ≥ 90°.  The spindle axis is derived from near-full-revolution
        # cylinders (≥ 270°), but individual bore faces can appear as 180° half-
        # cylinders when a seam plane splits the bore (e.g. disc parts).
        is_closed = fi.get("is_closed_u", False)
        if not is_closed:
            ur = fi.get("u_range")
            if ur is None or abs(ur[1] - ur[0]) < math.pi * 0.5:
                continue

        # Must align with spindle axis
        cyl_axis = fi.get("axis", (0.0, 0.0, 1.0))
        dot = abs(
            cyl_axis[0] * spindle_axis[0]
            + cyl_axis[1] * spindle_axis[1]
            + cyl_axis[2] * spindle_axis[2]
        )
        if dot < AXIS_DOT_MIN:
            continue

        radius = fi.get("radius_mm", 0.0)
        if radius < 0.1:
            continue

        # Multi-bore guard: skip if this bore is part of any coaxial multi-diameter
        # stack (counterbore / step bore).  Both the inner AND outer cylinders of
        # the assembly must be left for _detect_holes.  Area limit uses the max
        # radius so both inner and outer cylinders trigger the guard correctly.
        adj_idx = adjacency.get(fi["index"], set())
        _is_cbore = False
        for _ai in adj_idx:
            _af = next((f for f in face_infos if f["index"] == _ai), None)
            if _af is None or _af["type"] != "plane":
                continue
            for _ai2 in adjacency.get(_ai, set()):
                _af2 = next((f for f in face_infos if f["index"] == _ai2), None)
                if (
                    _af2
                    and _af2["index"] != fi["index"]
                    and _af2["type"] == "cylinder"
                    and _af2.get("orientation") == "reversed"
                    and abs(_af2.get("radius_mm", 0) - radius) > 0.5
                ):
                    r_max = max(radius, _af2.get("radius_mm", 0))
                    if _af.get("area_mm2", 0) <= math.pi * r_max * r_max:
                        _is_cbore = True
                        break
            if _is_cbore:
                break
        if _is_cbore:
            continue  # leave for _detect_holes

        # Drill-point cone guard: a reversed cone adjacent to this cylinder with
        # no plane on its far side is a drill-point tip — the hole was drilled
        # (milling op), not turned.  Leave these for _detect_holes (DRILLED_HOLE).
        _has_drill_cone = False
        for _ai in adj_idx:
            _af = next((f for f in face_infos if f["index"] == _ai), None)
            if _af is None or _af["type"] != "cone":
                continue
            if _af.get("orientation") != "reversed":
                continue
            cone_far_adj = adjacency.get(_af["index"], set()) - {fi["index"]}
            if not any(
                f2["type"] == "plane"
                for f2 in face_infos
                if f2["index"] in cone_far_adj
            ):
                _has_drill_cone = True
                break
        if _has_drill_cone:
            continue  # leave for _detect_holes

        circumference = 2.0 * math.pi * radius
        u_range = fi.get("u_range")
        arc_len = radius * abs(u_range[1] - u_range[0]) if u_range else circumference
        cyl_height = fi["area_mm2"] / arc_len if arc_len > 0 else 0.0

        # Circumferential-wall guard: C-shape pocket walls and thin disc-face ring
        # cylinders have h/r << 1 (e.g. Ø337mm × 3.8mm → h/r=0.022).
        # Full-revolution cylinders (is_closed_u=True) are unambiguously bores and
        # skip the guard entirely.  For large-radius partial arcs (radius ≥ 50mm)
        # use a relaxed 5% threshold so shallow face bores like Ø248mm × 8mm
        # (h/r≈0.068) are not rejected while thin ring walls (h/r≈0.022) still are.
        if not is_closed:
            _min_h_ratio = 0.30 if radius < 50.0 else 0.05
            if cyl_height < radius * _min_h_ratio:
                continue

        # Seam-split claiming: STEP exports often split a single bore into two
        # complementary arcs (e.g. two 180° halves).  Claim the complementary arc
        # now so it is not emitted as a separate BLIND_HOLE / THROUGH_HOLE.
        if not is_closed and u_range is not None:
            _u_span_fi = abs(u_range[1] - u_range[0])
            if _u_span_fi < math.pi * 1.5:
                _cf_adj_lb = adjacency.get(fi["index"], set())
                _bore_cross_lb = math.pi * radius * radius
                _h_fi_lb = fi["area_mm2"] / arc_len if arc_len > 0 else 0.0
                for _pf_lb in face_infos:
                    if _pf_lb["index"] in claimed_faces or _pf_lb["index"] == fi["index"]:
                        continue
                    if _pf_lb["type"] != "cylinder" or _pf_lb.get("orientation") != "reversed":
                        continue
                    if abs(_pf_lb.get("radius_mm", 0) - radius) > radius * 0.01 + 0.1:
                        continue
                    if not _axes_aligned(cyl_axis, _pf_lb.get("axis", (0.0, 0.0, 1.0))):
                        continue
                    _pf_lb_ur = _pf_lb.get("u_range")
                    if _pf_lb_ur is None:
                        continue
                    _span_lb = abs(_pf_lb_ur[1] - _pf_lb_ur[0])
                    if abs((_u_span_fi + _span_lb) - 2 * math.pi) > 0.35:
                        continue
                    _arc_lb = radius * _span_lb
                    _h_lb = _pf_lb["area_mm2"] / _arc_lb if _arc_lb > 0 else 0.0
                    if abs(_h_lb - _h_fi_lb) > max(_h_fi_lb * 0.15, 0.5):
                        continue
                    _pf_lb_adj = adjacency.get(_pf_lb["index"], set())
                    _shared_lb = {
                        i for i in (_cf_adj_lb & _pf_lb_adj)
                        if next((f["area_mm2"] for f in face_infos if f["index"] == i), 0)
                        < _bore_cross_lb * 10
                    }
                    if not _shared_lb:
                        continue
                    claimed_faces.add(_pf_lb["index"])
                    break

        # Look for a flat bottom cap (blind bore floor).
        # Cap must be ≥ 35% of a full disc — annular ring pocket floors
        # adjacent to large OD cylinders have area << π×r² and are false caps.
        adj_idx = adjacency.get(fi["index"], set())
        _min_lb_cap = math.pi * radius * radius * 0.35
        cap_faces = [
            f for f in face_infos
            if f["index"] in adj_idx
            and f["type"] == "plane"
            and _min_lb_cap <= f["area_mm2"] < math.pi * radius * radius * 1.3
        ]

        # Ring-floor guard: a large-radius reversed cylinder with no valid disc
        # cap but with a small adjacent plane (annular ring floor) is the outer
        # wall of an annular pocket, not a through bore.  Leave it for the pocket
        # detector.  We only trigger this when no cap was found, so blind bores
        # with a proper disc floor are unaffected.
        # Lower bound uses _min_lb_cap * 0.5 instead of the hardcoded 100mm²
        # so the guard fires correctly even for small bores (radius < ~9mm)
        # where _min_lb_cap itself is less than 100.
        if not cap_faces and any(
            _min_lb_cap * 0.5 < f["area_mm2"] < _min_lb_cap
            for f in face_infos
            if f["index"] in adj_idx and f["type"] == "plane"
        ):
            continue

        claimed_faces.add(fi["index"])
        face_indices = [fi["index"]]

        if cap_faces:
            # Blind bore — measure depth between entry plane and cap plane
            cap = cap_faces[0]
            claimed_faces.add(cap["index"])
            face_indices.append(cap["index"])

            all_planes: list[dict] = list(cap_faces)
            seen_plane_ids = {c["index"] for c in cap_faces}
            for p in _follow_through_transitions(
                fi["index"], adjacency, face_infos, target_type="plane"
            ):
                if p["index"] not in seen_plane_ids:
                    all_planes.append(p)
                    seen_plane_ids.add(p["index"])

            depth = cyl_height
            if len(all_planes) >= 2:
                projs: list[float] = []
                for pf in all_planes:
                    try:
                        pa = BRepAdaptor_Surface(pf["face"])
                        um = (pa.FirstUParameter() + pa.LastUParameter()) / 2
                        vm = (pa.FirstVParameter() + pa.LastVParameter()) / 2
                        pp = gp_Pnt()
                        du = gp_Vec()
                        dv = gp_Vec()
                        pa.D1(um, vm, pp, du, dv)
                        projs.append(
                            pp.X() * cyl_axis[0]
                            + pp.Y() * cyl_axis[1]
                            + pp.Z() * cyl_axis[2]
                        )
                    except Exception:
                        pass
                if len(projs) >= 2:
                    depth = max(projs) - min(projs)

            features.append(FeatureDetail(
                feature_id=_fid(),
                feature_type=FeatureType.BLIND_HOLE,
                confidence=0.88,
                source="rule_based",
                dimensions={
                    "diameter_mm": round(radius * 2, 3),
                    "depth_mm": round(abs(depth), 3),
                    "axis": [round(cyl_axis[0], 6), round(cyl_axis[1], 6), round(cyl_axis[2], 6)],
                    "bore_type": "lathe_blind",
                },
                perimeter_mm=round(circumference, 3),
                location=_face_center(fi["face"]),
                face_indices=face_indices,
                orientation=_normalize_axis(cyl_axis),
                key_face_id=_compute_face_persistent_id(fi),
            ))
        else:
            # Through bore — open on both ends
            features.append(FeatureDetail(
                feature_id=_fid(),
                feature_type=FeatureType.THROUGH_HOLE,
                confidence=0.90,
                source="rule_based",
                dimensions={
                    "diameter_mm": round(radius * 2, 3),
                    "depth_mm": round(cyl_height, 3),
                    "axis": [round(cyl_axis[0], 6), round(cyl_axis[1], 6), round(cyl_axis[2], 6)],
                    "bore_type": "lathe_through",
                },
                perimeter_mm=round(circumference, 3),
                location=_face_center(fi["face"]),
                face_indices=face_indices,
                orientation=_normalize_axis(cyl_axis),
                key_face_id=_compute_face_persistent_id(fi),
            ))

    return features


# ═══════════════════════════════════════════════════════════════════════════
# Main Recognition Entry Point
# ═══════════════════════════════════════════════════════════════════════════

def recognize_features_rule_based(
    shape: TopoDS_Shape,
    face_infos: list[dict],
    bbox_height: float,
    thickness_stats: Optional[ThicknessStats] = None,
    part_type: Optional[PartType] = None,
) -> list[FeatureDetail]:
    """
    Run all rule-based feature detectors.

    Args:
        shape: The component's TopoDS_Shape
        face_infos: Classified face info list from geometry_analyzer
        bbox_height: Bounding box height for through-hole estimation
        thickness_stats: Wall thickness data for sheet metal features
        part_type: Pre-classified part type; when set, sheet-metal-only
                   detectors are skipped for non-sheet-metal parts.

    Returns:
        List of detected FeatureDetail objects
    """
    is_sheet_metal = part_type is None or part_type == PartType.SHEET_METAL
    is_lathe = part_type in {PartType.CNC_LATHE, PartType.CNC_LATHE_MILLING}
    adjacency = _build_face_adjacency(shape, face_infos)

    features: list[FeatureDetail] = []

    # Track faces claimed by high-priority detectors so that later
    # detectors don't re-classify the same geometry as a different
    # feature type (e.g. a through-hole cylinder also matching as
    # an emboss or fillet).
    claimed_faces: set[int] = set()

    bend_cyl_faces: set[int] = set()
    bend_all_faces: set[int] = set()
    bend_cyl_groups: list[set[int]] = []

    if is_lathe:
        # ── Lathe / Mill-turn: run turning detectors first ──
        # This ensures OD and bore-ID cylinders are claimed before generic
        # detectors (holes, circular pockets) can misclassify them.

        # 1. OD / bore-ID steps (paired co-axial cylinders with annular shoulder)
        #    Runs first so primary OD steps claim their cylinders before chamfer/taper
        #    detectors consume adjacent faces.
        od_step_feats = _detect_lathe_od_steps(face_infos, adjacency, claimed_faces)
        features.extend(od_step_feats)

        # 2. Lathe bores (full-revolution, spindle-aligned REVERSED cylinders)
        #    Claims main bore-ID surfaces as THROUGH_HOLE / BLIND_HOLE before any
        #    milling-domain detector can misclassify them.
        bore_feats = _detect_lathe_bores(face_infos, adjacency, claimed_faces)
        features.extend(bore_feats)

        # 3. Tapered ODs (FORWARD cones: chamfers, taper shanks)
        tod_feats = _detect_tapered_ods(face_infos, adjacency, claimed_faces)
        features.extend(tod_feats)

        # 4. Tapered bores (REVERSED cones: bore entry chamfers, morse tapers)
        tb_feats = _detect_tapered_bores(face_infos, adjacency, claimed_faces)
        features.extend(tb_feats)

        # 5. Grooves (OD snap/O-ring grooves: REVERSED cylinders flanked by larger OD)
        groove_feats = _detect_grooves(face_infos, adjacency, claimed_faces)
        features.extend(groove_feats)

        # 6. Circular pockets (remaining shallow REVERSED cylinders — lathe face recesses).
        #    Runs after bores so deep bore cylinders are already claimed.
        circ_feats = _detect_circular_pockets(face_infos, adjacency, claimed_faces)
        features.extend(circ_feats)

    else:
        # ── Non-lathe (milling, sheet metal, unknown) ──

        # Circular pockets before holes: shallow REVERSED cylinders (depth/diameter < 0.5)
        # are claimed here so the hole detector doesn't re-classify them as blind holes,
        # and so the planar-floor pocket detector doesn't relabel their disc caps as
        # rectangular pockets.
        circ_feats = _detect_circular_pockets(face_infos, adjacency, claimed_faces)
        features.extend(circ_feats)
        # claimed_faces updated inside _detect_circular_pockets

        # Sheet-metal detectors (hems, bends, lances) removed — CNC-only scope.
        # The FeatureType vocabulary is locked to 19 CNC features + UNKNOWN;
        # sheet-metal parts route to the sheet-metal pipeline, not this engine.

    # ── Planar features (all part types) ──

    # Planar/slot pockets — runs before steps so open rabbet-style recesses
    # are captured as pockets rather than being grabbed first by the step detector.
    slot_feats = _detect_pockets_and_slots(face_infos, adjacency, shape, claimed_faces)
    features.extend(slot_feats)
    for f in slot_feats:
        claimed_faces.update(f.face_indices)

    # Steps — runs after pockets so pocket floors are already claimed.
    step_feats = _detect_steps(face_infos, adjacency, shape, claimed_faces)
    features.extend(step_feats)
    for f in step_feats:
        claimed_faces.update(f.face_indices)

    boss_rib_feats = _detect_bosses_and_ribs(face_infos, adjacency, claimed_faces)
    features.extend(boss_rib_feats)
    for f in boss_rib_feats:
        claimed_faces.update(f.face_indices)

    # Obround slots — corner fillets filtered inside by large-bore adjacency check.
    obround_feats = _detect_obround_slots(face_infos, adjacency, thickness_stats)
    features.extend(obround_feats)
    for f in obround_feats:
        claimed_faces.update(f.face_indices)

    # ── Holes (all part types) ──
    # Runs after pockets, steps, bosses, and obround slots so those detectors
    # claim their faces first:
    #   • Lathe parts: cross-drilled or partial-arc holes are captured after
    #     _detect_lathe_bores has claimed main turned bores.
    #   • Milling / sheet-metal: holes detected after _detect_circular_pockets
    #     has claimed shallow recesses.
    hole_feats = _detect_holes(face_infos, adjacency, bbox_height, claimed_faces)
    features.extend(hole_feats)
    for f in hole_feats:
        claimed_faces.update(f.face_indices)

    # --- Detectors that don't cause false positives ---
    # Exclude bend panel faces from chamfer detection.
    features.extend(_detect_chamfers(face_infos, adjacency, claimed_faces | bend_all_faces))
    # Thread detection removed — BSpline helix detector produces false positives
    # on large OD surfaces and is not reliable enough for production use.

    features.extend(_detect_draft_angles(face_infos, adjacency, claimed_faces))

    # --- Lower-priority detectors (skip claimed faces) ---
    # Sheet-metal detectors (flanges, embosses, perforation patterns, deep draws,
    # beads) removed — out of scope for the CNC-only feature vocabulary.

    features.extend(_detect_fillets(face_infos, adjacency, claimed_faces, part_type))

    # --- New detectors ---
    features.extend(_detect_undercuts(face_infos, adjacency, claimed_faces))
    # Grooves already run in the lathe branch above; skip the second call.
    if not is_lathe:
        features.extend(_detect_grooves(face_infos, adjacency, claimed_faces))

    # --- Volume-based validation ---
    # Reject features whose implied volume exceeds a reasonable fraction
    # of the total part volume (catches e.g. a large outer cylinder
    # misclassified as a blind hole).
    total_vol = 0.0
    try:
        vol_props = GProp_GProps()
        BRepGProp.VolumeProperties_s(shape, vol_props)
        total_vol = abs(vol_props.Mass())
    except Exception:
        pass
    if total_vol > 0:
        before = len(features)
        features = [f for f in features if _feature_volume_check(f, total_vol)]
        rejected = before - len(features)
        if rejected:
            logger.info("Volume check rejected %d features", rejected)

    logger.info("Rule-based engine detected %d features", len(features))

    # Strip internal metadata from dimensions before returning
    for f in features:
        f.dimensions.pop("cylinder_face_indices", None)

    return features
