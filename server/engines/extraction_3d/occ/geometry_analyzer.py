"""Geometry measurement: volume, surface area, bounding box, face analysis,
wall thickness, and perimeter extraction for laser cutting cost."""

from __future__ import annotations

import logging
import math
from typing import Optional

from OCP.Bnd import Bnd_Box
from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepClass3d import BRepClass3d_SolidClassifier
from OCP.BRepGProp import BRepGProp
from OCP.BRepTools import BRepTools
from OCP.GCPnts import GCPnts_AbscissaPoint
from OCP.GeomAbs import (
    GeomAbs_BSplineSurface,
    GeomAbs_BezierSurface,
    GeomAbs_Cone,
    GeomAbs_Cylinder,
    GeomAbs_Plane,
    GeomAbs_Sphere,
    GeomAbs_Torus,
)
from OCP.BRepAlgoAPI import BRepAlgoAPI_Section
from OCP.gp import gp_Ax3, gp_Dir, gp_Pln, gp_Pnt, gp_Vec
from OCP.GProp import GProp_GProps
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_FORWARD, TopAbs_REVERSED, TopAbs_WIRE
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS, TopoDS_Shape

from .models import (
    BoundingBox,
    CutoutPerimeter,
    FaceTypeCounts,
    PerimeterData,
    Point3D,
    ThicknessStats,
)

logger = logging.getLogger(__name__)


# ── Volume & Surface Area ────────────────────────────────────────────────────


def compute_volume(shape: TopoDS_Shape) -> float:
    """Compute volume in mm³. Returns 0.0 for open shells."""
    props = GProp_GProps()
    try:
        BRepGProp.VolumeProperties_s(shape, props)
        vol = props.Mass()
        return max(vol, 0.0)
    except Exception:
        logger.warning("Volume computation failed; returning 0.0")
        return 0.0


def compute_surface_area(shape: TopoDS_Shape) -> float:
    """Compute total surface area in mm²."""
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(shape, props)
    return max(props.Mass(), 0.0)


# ── Bounding Box ─────────────────────────────────────────────────────────────


def compute_bounding_box(shape: TopoDS_Shape) -> BoundingBox:
    """Compute axis-aligned bounding box.

    OCC's Bnd_Box returns sentinel values (~1e100) for empty shapes. We detect
    that and return a zero bbox instead so downstream code can branch on
    length==0 rather than wrestling with infinities.
    """
    bbox = Bnd_Box()
    BRepBndLib.Add_s(shape, bbox)
    if bbox.IsVoid():
        logger.warning("compute_bounding_box: input shape is void/empty")
        return BoundingBox(
            x_min=0.0, y_min=0.0, z_min=0.0,
            x_max=0.0, y_max=0.0, z_max=0.0,
            length=0.0, width=0.0, height=0.0,
        )
    x_min, y_min, z_min, x_max, y_max, z_max = bbox.Get()
    length = x_max - x_min
    width  = y_max - y_min
    height = z_max - z_min
    # OCC sentinel for an empty box is ±1e100. If we get implausibly huge
    # numbers, treat as empty rather than feed garbage downstream.
    if max(abs(x_min), abs(x_max), abs(y_min), abs(y_max), abs(z_min), abs(z_max)) > 1e9:
        logger.warning(
            "compute_bounding_box: implausible bbox values (likely uninitialized): "
            "x=[%.3g,%.3g] y=[%.3g,%.3g] z=[%.3g,%.3g]",
            x_min, x_max, y_min, y_max, z_min, z_max,
        )
        return BoundingBox(
            x_min=0.0, y_min=0.0, z_min=0.0,
            x_max=0.0, y_max=0.0, z_max=0.0,
            length=0.0, width=0.0, height=0.0,
        )
    return BoundingBox(
        x_min=x_min,
        y_min=y_min,
        z_min=z_min,
        x_max=x_max,
        y_max=y_max,
        z_max=z_max,
        length=length,
        width=width,
        height=height,
    )


# ── Center of Mass ───────────────────────────────────────────────────────────


def compute_center_of_mass(shape: TopoDS_Shape) -> Point3D:
    """Compute center of mass (centroid of volume)."""
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    com = props.CentreOfMass()
    return Point3D(x=com.X(), y=com.Y(), z=com.Z())


# ── Face Enumeration & Classification ────────────────────────────────────────


_SURFACE_TYPE_MAP = {
    GeomAbs_Plane: "plane",
    GeomAbs_Cylinder: "cylinder",
    GeomAbs_Cone: "cone",
    GeomAbs_Sphere: "sphere",
    GeomAbs_Torus: "torus",
    GeomAbs_BSplineSurface: "bspline",
    GeomAbs_BezierSurface: "bspline",
}


def classify_faces(shape: TopoDS_Shape) -> tuple[FaceTypeCounts, list[dict]]:
    """
    Enumerate all faces and classify by surface type.

    Returns:
        (FaceTypeCounts summary, list of per-face info dicts)
    """
    counts = {
        "plane": 0, "cylinder": 0, "cone": 0,
        "sphere": 0, "torus": 0, "bspline": 0, "other": 0,
    }
    face_infos: list[dict] = []

    explorer = TopExp_Explorer(shape, TopAbs_FACE)
    face_idx = 0
    while explorer.More():
        face = TopoDS.Face_s(explorer.Current())
        adaptor = BRepAdaptor_Surface(face)
        stype = adaptor.GetType()
        type_name = _SURFACE_TYPE_MAP.get(stype, "other")
        counts[type_name] += 1

        # Face area
        props = GProp_GProps()
        BRepGProp.SurfaceProperties_s(face, props)
        area = props.Mass()

        info: dict = {
            "index": face_idx,
            "type": type_name,
            "area_mm2": area,
            "face": face,
            "orientation": "reversed" if face.Orientation() == TopAbs_REVERSED else "forward",
        }

        # U/V closedness and parameter ranges
        try:
            info["is_closed_u"] = adaptor.IsUClosed()
            info["is_closed_v"] = adaptor.IsVClosed()
            info["u_range"] = (adaptor.FirstUParameter(), adaptor.LastUParameter())
            info["v_range"] = (adaptor.FirstVParameter(), adaptor.LastVParameter())
        except Exception:
            info["is_closed_u"] = False
            info["is_closed_v"] = False

        # Edge count
        edge_count = 0
        edge_exp = TopExp_Explorer(face, TopAbs_EDGE)
        while edge_exp.More():
            edge_count += 1
            edge_exp.Next()
        info["edge_count"] = edge_count

        # Extract geometry details for specific face types
        if stype == GeomAbs_Cylinder:
            cyl = adaptor.Cylinder()
            info["radius_mm"] = cyl.Radius()
            info["axis"] = (
                cyl.Axis().Direction().X(),
                cyl.Axis().Direction().Y(),
                cyl.Axis().Direction().Z(),
            )
            info["axis_origin"] = (
                cyl.Axis().Location().X(),
                cyl.Axis().Location().Y(),
                cyl.Axis().Location().Z(),
            )
        elif stype == GeomAbs_Cone:
            cone = adaptor.Cone()
            info["semi_angle_deg"] = math.degrees(cone.SemiAngle())
            info["axis"] = (
                cone.Axis().Direction().X(),
                cone.Axis().Direction().Y(),
                cone.Axis().Direction().Z(),
            )
            info["axis_origin"] = (
                cone.Axis().Location().X(),
                cone.Axis().Location().Y(),
                cone.Axis().Location().Z(),
            )
            info["radius_mm"] = cone.RefRadius()
        elif stype == GeomAbs_Torus:
            torus = adaptor.Torus()
            info["major_radius_mm"] = torus.MajorRadius()
            info["minor_radius_mm"] = torus.MinorRadius()
            info["axis"] = (
                torus.Axis().Direction().X(),
                torus.Axis().Direction().Y(),
                torus.Axis().Direction().Z(),
            )
        elif stype == GeomAbs_Sphere:
            sphere = adaptor.Sphere()
            info["radius_mm"] = sphere.Radius()

        face_infos.append(info)
        face_idx += 1
        explorer.Next()

    total = sum(counts.values())
    return FaceTypeCounts(**counts, total=total), face_infos


# ── Wall Thickness Measurement ───────────────────────────────────────────────


def measure_wall_thickness(
    shape: TopoDS_Shape,
    face_infos: list[dict],
    num_samples: int = 5,
) -> Optional[ThicknessStats]:
    """
    Estimate wall thickness by ray-casting inward from planar faces.

    Samples points on the largest planar faces, shoots rays along the
    inward normal, and measures the distance to the opposing surface.
    """
    planar_faces = [f for f in face_infos if f["type"] == "plane"]
    if len(planar_faces) < 2:
        return None

    # Sort by area descending and pick top faces to sample from
    planar_faces.sort(key=lambda f: f["area_mm2"], reverse=True)
    sample_faces = planar_faces[: min(4, len(planar_faces))]

    thicknesses: list[float] = []

    for finfo in sample_faces:
        face = finfo["face"]
        adaptor = BRepAdaptor_Surface(face)
        u_min, u_max, v_min, v_max = (
            adaptor.FirstUParameter(),
            adaptor.LastUParameter(),
            adaptor.FirstVParameter(),
            adaptor.LastVParameter(),
        )

        for i in range(num_samples):
            for j in range(num_samples):
                u = u_min + (u_max - u_min) * (i + 0.5) / num_samples
                v = v_min + (v_max - v_min) * (j + 0.5) / num_samples

                pt = gp_Pnt()
                normal = gp_Vec()
                adaptor.D1(u, v, pt, gp_Vec(), normal)

                # Get proper face normal
                surf_normal = gp_Vec()
                try:
                    d1u = gp_Vec()
                    d1v = gp_Vec()
                    adaptor.D1(u, v, pt, d1u, d1v)
                    surf_normal = d1u.Crossed(d1v)
                    if surf_normal.Magnitude() > 1e-10:
                        surf_normal.Normalize()
                    else:
                        continue
                except Exception:
                    continue

                # Account for face orientation
                from OCP.TopAbs import TopAbs_REVERSED
                if face.Orientation() == TopAbs_REVERSED:
                    inward = surf_normal
                else:
                    inward = gp_Vec(-surf_normal.X(), -surf_normal.Y(), -surf_normal.Z())

                # Use solid classifier to find the opposite wall distance
                classifier = BRepClass3d_SolidClassifier(shape)
                # Move point slightly inward
                test_pt = gp_Pnt(
                    pt.X() + inward.X() * 0.01,
                    pt.Y() + inward.Y() * 0.01,
                    pt.Z() + inward.Z() * 0.01,
                )
                # Simple thickness estimate: project to all other planar faces
                # and find the closest opposing face
                # Find closest opposing face by projecting sample point
                # along the inward normal, measuring the min distance
                best_dist = None
                for other in planar_faces:
                    if other["index"] == finfo["index"]:
                        continue
                    other_adaptor = BRepAdaptor_Surface(other["face"])
                    # Check if faces are roughly opposing (normals roughly anti-parallel)
                    other_d1u = gp_Vec()
                    other_d1v = gp_Vec()
                    other_normal = gp_Vec()
                    other_mid = gp_Pnt()
                    try:
                        other_adaptor.D1(
                            (other_adaptor.FirstUParameter() + other_adaptor.LastUParameter()) / 2,
                            (other_adaptor.FirstVParameter() + other_adaptor.LastVParameter()) / 2,
                            other_mid,
                            other_d1u,
                            other_d1v,
                        )
                        other_normal = other_d1u.Crossed(other_d1v)
                        if other_normal.Magnitude() > 1e-10:
                            other_normal.Normalize()
                        else:
                            continue
                    except Exception:
                        continue

                    dot = surf_normal.Dot(other_normal)
                    if dot > -0.8:  # Not roughly anti-parallel
                        continue

                    # Project sample point onto the other face's plane
                    # using the face normal direction for proper thickness
                    vec_to_other = gp_Vec(
                        other_mid.X() - pt.X(),
                        other_mid.Y() - pt.Y(),
                        other_mid.Z() - pt.Z(),
                    )
                    # Distance along the normal = |vec . normal|
                    dist = abs(vec_to_other.Dot(surf_normal))
                    if dist > 0.01 and (best_dist is None or dist < best_dist):
                        best_dist = dist

                if best_dist is not None:
                    thicknesses.append(best_dist)

    if not thicknesses:
        return None

    mean_t = sum(thicknesses) / len(thicknesses)
    min_t = min(thicknesses)
    max_t = max(thicknesses)
    variance = sum((t - mean_t) ** 2 for t in thicknesses) / len(thicknesses)
    std_dev = math.sqrt(variance)
    is_uniform = std_dev < 0.05 * mean_t if mean_t > 0 else False

    return ThicknessStats(
        min_mm=round(min_t, 3),
        max_mm=round(max_t, 3),
        mean_mm=round(mean_t, 3),
        std_dev_mm=round(std_dev, 4),
        is_uniform=is_uniform,
    )


# ── Perimeter Extraction ─────────────────────────────────────────────────────


def _wire_length(wire) -> float:
    """Compute total length of a wire using BRepGProp.LinearProperties."""
    props = GProp_GProps()
    BRepGProp.LinearProperties_s(wire, props)
    return props.Mass()


def _wire_is_circular(wire) -> tuple[bool, Optional[float]]:
    """Check if a wire is a single circle and return diameter if so."""
    edges = []
    explorer = TopExp_Explorer(wire, TopAbs_EDGE)
    while explorer.More():
        edges.append(TopoDS.Edge_s(explorer.Current()))
        explorer.Next()

    if len(edges) > 2:
        return False, None

    # Check if all edges are circular arcs on the same circle
    for edge in edges:
        try:
            adaptor = BRepAdaptor_Curve(edge)
            if adaptor.GetType() != 6:  # GeomAbs_Circle
                return False, None
        except Exception:
            return False, None

    if edges:
        adaptor = BRepAdaptor_Curve(edges[0])
        try:
            circle = adaptor.Circle()
            diameter = circle.Radius() * 2.0
            return True, diameter
        except Exception:
            return False, None

    return False, None


def extract_perimeters(
    shape: TopoDS_Shape,
    face_infos: list[dict],
    bbox: BoundingBox,
) -> Optional[PerimeterData]:
    """
    Extract outer profile and cutout perimeters for laser cutting cost.

    Identifies the top/bottom faces (largest planar faces along the thinnest
    axis) and measures their wire perimeters.
    """
    # Find the thinnest axis — sheet metal primary plane is perpendicular to it
    dims = [
        (bbox.length, "x"),
        (bbox.width, "y"),
        (bbox.height, "z"),
    ]
    dims.sort(key=lambda d: d[0])
    thin_axis = dims[0][1]
    thin_dim = dims[0][0]

    # Find planar faces whose normals are along the thin axis
    # These are the top/bottom faces of the sheet
    top_face = None
    top_area = 0.0

    for finfo in face_infos:
        if finfo["type"] != "plane":
            continue
        face = finfo["face"]
        adaptor = BRepAdaptor_Surface(face)

        # Get face normal at center
        u_mid = (adaptor.FirstUParameter() + adaptor.LastUParameter()) / 2
        v_mid = (adaptor.FirstVParameter() + adaptor.LastVParameter()) / 2

        pt = gp_Pnt()
        d1u = gp_Vec()
        d1v = gp_Vec()
        try:
            adaptor.D1(u_mid, v_mid, pt, d1u, d1v)
            normal = d1u.Crossed(d1v)
            if normal.Magnitude() < 1e-10:
                continue
            normal.Normalize()
        except Exception:
            continue

        # Check if normal is along the thin axis
        nx, ny, nz = abs(normal.X()), abs(normal.Y()), abs(normal.Z())
        if thin_axis == "z" and nz > 0.9:
            is_top_bottom = True
        elif thin_axis == "y" and ny > 0.9:
            is_top_bottom = True
        elif thin_axis == "x" and nx > 0.9:
            is_top_bottom = True
        else:
            is_top_bottom = False

        if is_top_bottom and finfo["area_mm2"] > top_area:
            top_area = finfo["area_mm2"]
            top_face = face

    if top_face is None:
        return None

    # Extract outer wire
    outer_wire = BRepTools.OuterWire_s(top_face)
    outer_perimeter = _wire_length(outer_wire)

    # Extract inner wires (cutouts)
    cutout_perimeters: list[CutoutPerimeter] = []
    wire_explorer = TopExp_Explorer(top_face, TopAbs_WIRE)
    wire_idx = 0
    while wire_explorer.More():
        wire = TopoDS.Wire_s(wire_explorer.Current())
        if not wire.IsEqual(outer_wire):
            length = _wire_length(wire)
            is_circ, diameter = _wire_is_circular(wire)
            cutout_perimeters.append(
                CutoutPerimeter(
                    wire_index=wire_idx,
                    perimeter_mm=round(length, 3),
                    is_circular=is_circ,
                    diameter_mm=round(diameter, 3) if diameter else None,
                )
            )
        wire_idx += 1
        wire_explorer.Next()

    total_cutout = sum(c.perimeter_mm for c in cutout_perimeters)
    total_cut_length = outer_perimeter + total_cutout

    return PerimeterData(
        outer_perimeter_mm=round(outer_perimeter, 3),
        cutout_perimeters=cutout_perimeters,
        total_cut_length_mm=round(total_cut_length, 3),
    )


# ── Edge Length Utility ──────────────────────────────────────────────────────


def compute_edge_length(edge) -> float:
    """Compute exact arc length of a single edge."""
    adaptor = BRepAdaptor_Curve(edge)
    return GCPnts_AbscissaPoint.Length_s(
        adaptor, adaptor.FirstParameter(), adaptor.LastParameter()
    )


# ── Cross-Section Topology Check ────────────────────────────────────────────


def check_closed_cross_section(
    shape: TopoDS_Shape,
    bbox: BoundingBox,
    num_planes: int = 6,
    min_closed: int = 3,
) -> bool:
    """Determine whether the shape has a closed (hollow) cross-section.

    A tube or pipe (any profile — round, square, oval, custom) has cross-sections
    with at least two distinct closed loops: an outer boundary and an inner void.
    An open sheet-metal section (C-channel, L-bracket, hat-section) has only a
    single closed loop per cross-section slice.

    Algorithm:
      1. Identify the longest bounding-box axis (the extrusion direction).
      2. Cut the shape at ``num_planes`` evenly-spaced positions along that axis
         using BRepAlgoAPI_Section, avoiding the 5% near each end cap.
      3. For each section, build an adjacency graph from edge endpoints using
         BRepAdaptor_Curve (avoids the immutable-float output-parameter issue
         with BRep_Tool.Curve_s) and count connected components via BFS.
      4. Return True if at least ``min_closed`` sections contain ≥ 2 connected
         loops (indicating an enclosed hollow profile).

    Only runs for elongated shapes (aspect ratio ≥ 2.5 and longest dim ≥ 10 mm)
    to avoid false negatives on compact solid blocks.
    """
    from OCP.BRepAdaptor import BRepAdaptor_Curve

    try:
        dims = sorted(
            [
                (bbox.length, (1.0, 0.0, 0.0), bbox.x_min, bbox.x_max),
                (bbox.width,  (0.0, 1.0, 0.0), bbox.y_min, bbox.y_max),
                (bbox.height, (0.0, 0.0, 1.0), bbox.z_min, bbox.z_max),
            ],
            key=lambda d: d[0],
            reverse=True,
        )
        longest_size, long_axis, lo, hi = dims[0]
        second_size = dims[1][0]

        # Only meaningful for genuinely elongated shapes
        if longest_size < 10.0 or longest_size / max(second_size, 1.0) < 2.5:
            return False

        cx_mid = (bbox.x_min + bbox.x_max) / 2
        cy_mid = (bbox.y_min + bbox.y_max) / 2
        cz_mid = (bbox.z_min + bbox.z_max) / 2
        long_dir = gp_Dir(*long_axis)

        # Evenly space planes in the inner 90% of the length to avoid
        # cutting through end-cap faces which may be open or degenerate.
        inner_lo = lo + 0.05 * (hi - lo)
        inner_hi = hi - 0.05 * (hi - lo)
        step = (inner_hi - inner_lo) / (num_planes + 1)
        fractions = [inner_lo + step * i for i in range(1, num_planes + 1)]

        closed_count = 0
        evaluated_count = 0

        for t in fractions:
            px = t   if long_axis[0] else cx_mid
            py = t   if long_axis[1] else cy_mid
            pz = t   if long_axis[2] else cz_mid

            pln = gp_Pln(gp_Ax3(gp_Pnt(px, py, pz), long_dir))
            sec = BRepAlgoAPI_Section(shape, pln, False)
            sec.ComputePCurveOn1(False)
            sec.Approximation(True)
            sec.Build()

            if not sec.IsDone():
                continue

            # Build adjacency graph from edge endpoints.
            # Use BRepAdaptor_Curve to obtain correct parameter bounds
            # (BRep_Tool.Curve_s float out-params don't work in Python).
            adjacency: dict[tuple[int, int, int], set[tuple[int, int, int]]] = {}
            edge_count = 0
            tol = 0.1  # mm grid for vertex identity

            exp = TopExp_Explorer(sec.Shape(), TopAbs_EDGE)
            while exp.More():
                edge = TopoDS.Edge_s(exp.Current())
                try:
                    bc = BRepAdaptor_Curve(edge)
                    p0, p1 = gp_Pnt(), gp_Pnt()
                    bc.D0(bc.FirstParameter(), p0)
                    bc.D0(bc.LastParameter(), p1)
                    k0 = (round(p0.X() / tol), round(p0.Y() / tol), round(p0.Z() / tol))
                    k1 = (round(p1.X() / tol), round(p1.Y() / tol), round(p1.Z() / tol))
                    adjacency.setdefault(k0, set()).add(k1)
                    adjacency.setdefault(k1, set()).add(k0)
                    edge_count += 1
                except Exception:
                    pass
                exp.Next()

            if edge_count == 0:
                continue

            # Count connected components via BFS — each component is a
            # distinct loop in the cross-section.
            # A genuine tube has ≥ 2 *substantial* loops (outer + inner void),
            # each with many vertices.  Small fragments from holes or slots
            # intersecting the cut plane are ignored (few vertices).
            # Allow up to 2 degree-1 vertices per component to tolerate weld
            # seam gaps in real tube models.
            visited: set[tuple[int, int, int]] = set()
            substantial_closed_loops = 0
            min_verts_for_loop = 7  # skip small hole/slot fragments

            for start_node in adjacency:
                if start_node in visited:
                    continue
                # BFS to collect this component
                component: list[tuple[int, int, int]] = []
                queue = [start_node]
                while queue:
                    node = queue.pop()
                    if node in visited:
                        continue
                    visited.add(node)
                    component.append(node)
                    for nb in adjacency.get(node, set()):
                        if nb not in visited:
                            queue.append(nb)

                if len(component) < min_verts_for_loop:
                    continue  # small fragment — not a real loop

                # Allow at most 2 open ends (one seam gap) per loop
                deg1 = sum(1 for v in component if len(adjacency[v]) == 1)
                if deg1 <= 2:
                    substantial_closed_loops += 1

            evaluated_count += 1
            # ≥ 2 substantial loops means outer boundary + inner void
            if substantial_closed_loops >= 2:
                closed_count += 1

        # At least min_closed planes must show a hollow cross-section.
        return evaluated_count >= min_closed and closed_count >= min_closed

    except Exception:
        logger.debug("Cross-section topology check failed", exc_info=True)
        return False


# ── Rotational Symmetry Detection ────────────────────────────────────────────


def _check_od_rotational_symmetry(face_infos: list[dict]) -> dict:
    """Detect rotational symmetry from OD/ID face geometry only.

    Uses FORWARD cylinders/cones (OD surfaces) and large REVERSED cylinders
    (principal bore IDs) instead of slicing the full shape.  This gives a
    correct best_count for disc/flange parts that have milled pockets or
    other asymmetric features that would break the cross-section approach.

    Returns the same dict format as check_rotational_symmetry.
    """
    result = {
        "x_matches": 0, "y_matches": 0, "z_matches": 0,
        "best_axis": None, "best_count": 0,
    }

    OD_MIN_RADIUS_MM = 10.0    # ignore tiny cylinders (bolt holes etc.)
    BORE_MIN_RADIUS_MM = 20.0  # only large bores count as principal bore IDs

    axis_counts: dict[str, int] = {"x": 0, "y": 0, "z": 0}

    for fi in face_infos:
        ftype = fi.get("type")
        orientation = fi.get("orientation", "forward")

        # Must span nearly a full revolution (closed or ≥ 270°)
        is_closed = fi.get("is_closed_u", False)
        if not is_closed:
            u_range = fi.get("u_range")
            if u_range is None:
                continue
            if abs(u_range[1] - u_range[0]) < math.pi * 1.5:
                continue

        # Accept FORWARD cylinders/cones (OD) and large REVERSED cylinders (bore ID)
        if ftype == "cylinder" and orientation == "forward":
            if fi.get("radius_mm", 0) < OD_MIN_RADIUS_MM:
                continue
        elif ftype == "cone" and orientation == "forward":
            pass
        elif ftype == "cylinder" and orientation == "reversed":
            if fi.get("radius_mm", 0) < BORE_MIN_RADIUS_MM:
                continue
        else:
            continue

        # Classify by which principal axis the face is aligned with
        axis = fi.get("axis", (0.0, 0.0, 1.0))
        ax, ay, az = abs(axis[0]), abs(axis[1]), abs(axis[2])
        if ax >= ay and ax >= az:
            axis_counts["x"] += 1
        elif ay >= ax and ay >= az:
            axis_counts["y"] += 1
        else:
            axis_counts["z"] += 1

    # Map face count per axis to a best_count value on the 0–8 scale
    best_axis: Optional[str] = None
    best_count = 0
    for ax_name, count in axis_counts.items():
        if count >= 3:
            mapped = 8
        elif count == 2:
            mapped = 5
        elif count == 1:
            mapped = 3
        else:
            mapped = 0
        result[f"{ax_name}_matches"] = mapped
        if mapped > best_count:
            best_count = mapped
            best_axis = ax_name

    result["best_axis"] = best_axis
    result["best_count"] = best_count
    return result


def check_rotational_symmetry(
    shape: TopoDS_Shape,
    bbox: BoundingBox,
    num_planes: int = 8,
    tolerance: float = 0.05,
    face_infos: Optional[list[dict]] = None,
) -> dict:
    """Detect rotational symmetry by comparing cross-section areas.

    When ``face_infos`` is supplied, delegates to
    ``_check_od_rotational_symmetry`` which examines only OD/bore-ID
    cylindrical faces and is immune to milled pockets breaking symmetry.

    For each principal axis (X, Y, Z), slice the shape with ``num_planes``
    planes that all contain the axis and pass through the bounding-box center,
    evenly rotated from 0° to 180° (exclusive).  Planes at θ and θ+180° are
    geometrically identical, so only the half-rotation is needed.

    For each slice, section edges are collected, wires are built, faces are
    created, and total face area is computed.  The largest cluster of areas
    within ``tolerance`` (relative) is counted.

    Returns:
        dict with keys ``x_matches``, ``y_matches``, ``z_matches``,
        ``best_axis`` (str or None), ``best_count`` (int).
    """
    if face_infos is not None:
        return _check_od_rotational_symmetry(face_infos)

    result = {
        "x_matches": 0, "y_matches": 0, "z_matches": 0,
        "best_axis": None, "best_count": 0,
    }

    try:
        cx = (bbox.x_min + bbox.x_max) / 2
        cy = (bbox.y_min + bbox.y_max) / 2
        cz = (bbox.z_min + bbox.z_max) / 2
        center = gp_Pnt(cx, cy, cz)

        # Axis definitions: (axis direction, two perpendicular basis vectors)
        axes = {
            "x": (gp_Dir(1, 0, 0), gp_Dir(0, 1, 0), gp_Dir(0, 0, 1)),
            "y": (gp_Dir(0, 1, 0), gp_Dir(1, 0, 0), gp_Dir(0, 0, 1)),
            "z": (gp_Dir(0, 0, 1), gp_Dir(1, 0, 0), gp_Dir(0, 1, 0)),
        }

        angle_step = math.pi / num_planes  # 22.5° for 8 planes

        for axis_name, (axis_dir, perp1, perp2) in axes.items():
            areas: list[float] = []

            for i in range(num_planes):
                theta = i * angle_step
                # Normal perpendicular to the axis, rotated by theta
                cos_t = math.cos(theta)
                sin_t = math.sin(theta)
                nx = cos_t * perp1.X() + sin_t * perp2.X()
                ny = cos_t * perp1.Y() + sin_t * perp2.Y()
                nz = cos_t * perp1.Z() + sin_t * perp2.Z()

                normal = gp_Dir(nx, ny, nz)
                pln = gp_Pln(gp_Ax3(center, normal))

                sec = BRepAlgoAPI_Section(shape, pln, False)
                sec.ComputePCurveOn1(False)
                sec.Approximation(True)
                sec.Build()
                if not sec.IsDone():
                    areas.append(-1.0)
                    continue

                section_shape = sec.Shape()

                # Collect all edges from the section
                total_area = _section_area(section_shape)
                areas.append(total_area)

            # Count largest cluster of matching areas
            match_count = _largest_area_cluster(areas, tolerance)
            result[f"{axis_name}_matches"] = match_count

        # Determine best axis
        best_axis = None
        best_count = 0
        for ax in ("x", "y", "z"):
            c = result[f"{ax}_matches"]
            if c > best_count:
                best_count = c
                best_axis = ax
        result["best_axis"] = best_axis
        result["best_count"] = best_count

    except Exception:
        logger.debug("Rotational symmetry check failed", exc_info=True)

    return result


def _section_area(section_shape: TopoDS_Shape) -> float:
    """Compute total edge length of section edges as a proxy for cross-section size.

    Using total wire length rather than enclosed face area because building
    closed wires and planar faces from arbitrary section edges is fragile
    with OCC.  Total edge length is a reliable rotational-symmetry indicator:
    if the profile is the same at every angle, the total perimeter will match.
    """
    try:
        total_length = 0.0
        explorer = TopExp_Explorer(section_shape, TopAbs_EDGE)
        while explorer.More():
            edge = TopoDS.Edge_s(explorer.Current())
            props = GProp_GProps()
            BRepGProp.LinearProperties_s(edge, props)
            total_length += abs(props.Mass())
            explorer.Next()
        return total_length
    except Exception:
        return 0.0


def _largest_area_cluster(areas: list[float], tolerance: float) -> int:
    """Find the largest group of areas that are within ``tolerance`` of each other."""
    valid = [a for a in areas if a > 0]
    if not valid:
        return 0

    best = 1
    for i, ref in enumerate(valid):
        count = 0
        for a in valid:
            if abs(a - ref) / max(ref, 1e-9) <= tolerance:
                count += 1
        best = max(best, count)

    return best


# ── Full Geometry Analysis ───────────────────────────────────────────────────


def analyze_geometry(shape: TopoDS_Shape) -> dict:
    """
    Run complete geometry analysis on a shape.

    Returns dict with all geometry results suitable for building
    ComponentAnalysis models.
    """
    volume = compute_volume(shape)
    surface_area = compute_surface_area(shape)
    bbox = compute_bounding_box(shape)
    center_of_mass = compute_center_of_mass(shape)
    face_counts, face_infos = classify_faces(shape)
    thickness = measure_wall_thickness(shape, face_infos)
    perimeters = extract_perimeters(shape, face_infos, bbox)

    has_closed_xs = check_closed_cross_section(shape, bbox)
    rotational_sym = check_rotational_symmetry(shape, bbox, face_infos=face_infos)

    return {
        "volume_mm3": round(volume, 3),
        "surface_area_mm2": round(surface_area, 3),
        "bounding_box": bbox,
        "center_of_mass": center_of_mass,
        "face_type_counts": face_counts,
        "face_infos": face_infos,  # Pass through for feature recognition
        "thickness_stats": thickness,
        "perimeter_data": perimeters,
        "has_closed_cross_section": has_closed_xs,
        "rotational_symmetry": rotational_sym,
    }
