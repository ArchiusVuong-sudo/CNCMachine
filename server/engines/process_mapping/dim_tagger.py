"""
dim_tagger.py â€” Tag VLM-extracted dimensions / GD&T / threads to AFR features.

The drawing extraction returns dimension rows, GD&T callouts and thread specs
without any link to specific 3D features. The AFR (feature recognizer) returns
features with diameters, dimensions and face_ids but no awareness of what the
drawing's tolerance frame says about them.

This module bridges the two: every VLM dimension is matched to either a
specific feature (by diameter / linear value), to the part bbox, or marked
unmatched. Each tagged dimension carries an `implications` block the routing
engine reads to add finishing passes, inspection time, or grinding ops.

Public API
----------
    tag_component_dimensions(component, vlm_extraction) -> list[dict]
    tag_all_components(components, vlm_extraction) -> dict
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger("cncserver.engines.process_mapping.dim_tagger")


# ---------------------------------------------------------------------------
# Tolerance classification
# ---------------------------------------------------------------------------

# Bands in mm. A dim with bilateral tolerance Â±x falls into the first band
# where x <= upper_bound; reading top-down picks the tightest match first.
_TOL_BANDS_MM: list[tuple[str, float, bool, bool]] = [
    # (class,        upper_bound_mm, needs_finishing, needs_inspection)
    ("ground",       0.005,          True,  True),
    ("tight",        0.025,          True,  True),
    ("standard",     0.10,           False, False),
    ("rough",        0.50,           False, False),
    ("loose",        9999.0,         False, False),
]


def _classify_tolerance(plus: float | None, minus: float | None) -> tuple[str, bool, bool]:
    """Return (tolerance_class, needs_finishing, needs_inspection)."""
    if plus is None and minus is None:
        return ("standard", False, False)
    p = abs(float(plus))  if plus  is not None else 0.0
    m = abs(float(minus)) if minus is not None else 0.0
    band = max(p, m)
    if band <= 0.0:
        return ("standard", False, False)
    for cls, upper, fin, insp in _TOL_BANDS_MM:
        if band <= upper:
            return (cls, fin, insp)
    return ("loose", False, False)


def _gdt_implications(callout: dict) -> tuple[str, bool, bool]:
    """Map a GD&T callout to (tolerance_class, needs_finishing, needs_inspection)."""
    tol_raw = callout.get("tolerance") or callout.get("value") or ""
    if isinstance(tol_raw, (int, float)):
        tol_val = float(tol_raw)
    else:
        # parse e.g. "0.025", "Ã˜0.05", "0.005 A"
        m = re.search(r"(\d+\.?\d*)", str(tol_raw))
        tol_val = float(m.group(1)) if m else 0.0

    sym = (callout.get("symbol") or callout.get("type") or "").lower()
    # Position / runout / concentricity â†’ require inspection
    needs_inspection = bool(sym) or tol_val > 0
    needs_finishing  = tol_val > 0 and tol_val <= 0.05

    if tol_val and tol_val <= 0.005:
        return ("ground", True, True)
    if tol_val and tol_val <= 0.025:
        return ("tight", needs_finishing, True)
    if tol_val and tol_val <= 0.10:
        return ("standard", needs_finishing, needs_inspection)
    return ("loose", False, needs_inspection)


# ---------------------------------------------------------------------------
# Dimension parsing
# ---------------------------------------------------------------------------

def _to_float(v) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        # strip leading symbols like Ã˜, R, M
        s = str(v).strip().lstrip("Ã˜RMM")
        m = re.match(r"-?\d+\.?\d*", s)
        return float(m.group(0)) if m else None


def _vlm_dim_value_mm(dim: dict, default_unit: str = "mm") -> float | None:
    """Extract a numeric value in mm from a VLM dim dict."""
    val = _to_float(dim.get("value") or dim.get("nominal") or dim.get("size"))
    if val is None:
        return None
    unit = (dim.get("unit") or default_unit or "mm").lower()
    if "in" in unit:
        return val * 25.4
    return val


def _vlm_dim_kind(dim: dict) -> str:
    """Bucket the VLM dim into 'diameter' | 'linear' | 'unknown'."""
    raw_kind = (dim.get("dimension_type") or dim.get("kind") or "").lower()
    if "dia" in raw_kind or "hole" in raw_kind or "bore" in raw_kind:
        return "diameter"
    if "linear" in raw_kind or "length" in raw_kind or "width" in raw_kind or "height" in raw_kind:
        return "linear"
    label = str(dim.get("label") or dim.get("text") or "").upper()
    if label.startswith("Ã˜") or "DIA" in label or label.startswith("R"):
        return "diameter"
    return "unknown"


# ---------------------------------------------------------------------------
# Feature lookup
# ---------------------------------------------------------------------------

_DIAMETER_FEATURE_TYPES: frozenset[str] = frozenset({
    "through_hole", "blind_hole", "counterbore", "countersink",
    "boss", "fillet",
})

_LINEAR_FEATURE_TYPES: frozenset[str] = frozenset({
    "pocket", "step", "groove",
})


def _feature_diameter(feat: dict) -> float | None:
    dims = feat.get("dimensions") or {}
    for k in ("diameter_mm", "hole_diameter_mm", "tool_diameter_mm"):
        v = _to_float(dims.get(k))
        if v and v > 0:
            return v
    return None


def _feature_linear_dims(feat: dict) -> list[float]:
    dims = feat.get("dimensions") or {}
    out: list[float] = []
    for k in ("length_mm", "width_mm", "depth_mm", "height_mm",
              "size_x_mm", "size_y_mm", "size_z_mm"):
        v = _to_float(dims.get(k))
        if v and v > 0:
            out.append(v)
    return out


def _match_diameter_dim(
    target_mm: float,
    features: list[dict],
    tol: float = 0.5,
) -> tuple[int | None, float]:
    """Find the feature whose diameter is closest to target. Returns (idx, score)."""
    best_idx, best_diff = None, 1e9
    for i, f in enumerate(features):
        if (f.get("feature_type") or "").lower() not in _DIAMETER_FEATURE_TYPES:
            continue
        d = _feature_diameter(f)
        if d is None:
            continue
        diff = abs(d - target_mm)
        if diff < best_diff:
            best_diff, best_idx = diff, i
    if best_idx is None or best_diff > tol:
        return (None, 0.0)
    score = max(0.0, 1.0 - (best_diff / max(tol, 0.01)))
    return (best_idx, round(score, 3))


def _match_linear_dim(
    target_mm: float,
    features: list[dict],
    bbox: dict,
    tol: float = 1.0,
) -> tuple[int | None, str, float]:
    """Try to match a linear dim to a feature dimension or to the bbox."""
    # Feature linear dimensions first
    best_idx, best_diff = None, 1e9
    for i, f in enumerate(features):
        if (f.get("feature_type") or "").lower() not in _LINEAR_FEATURE_TYPES:
            continue
        for d in _feature_linear_dims(f):
            diff = abs(d - target_mm)
            if diff < best_diff:
                best_diff, best_idx = diff, i

    if best_idx is not None and best_diff <= tol:
        score = max(0.0, 1.0 - (best_diff / max(tol, 0.01)))
        return (best_idx, "feature", round(score, 3))

    # Bbox dimensions
    bb_dims = [
        _to_float(bbox.get("length_mm")),
        _to_float(bbox.get("width_mm")),
        _to_float(bbox.get("height_mm")),
    ]
    bb_dims = [d for d in bb_dims if d and d > 0]
    if bb_dims:
        bb_diff = min(abs(d - target_mm) for d in bb_dims)
        if bb_diff <= max(tol, target_mm * 0.02):
            score = max(0.0, 1.0 - bb_diff / max(target_mm * 0.02, tol, 0.01))
            return (None, "bbox", round(score, 3))

    return (None, "unmatched", 0.0)


# ---------------------------------------------------------------------------
# Public: tag one component
# ---------------------------------------------------------------------------

def tag_component_dimensions(
    component: dict,
    vlm_extraction: dict,
) -> list[dict]:
    """
    Tag every VLM dimension / GD&T / thread to a feature, the bbox, or unmatched.

    Mutates each matched feature:
      - feature["tolerance_class"] is set to the tightest tolerance among its tags.
      - feature["needs_finishing"] OR-ed across tags.
      - feature["needs_inspection"] OR-ed across tags.
      - feature["tagged_dimensions"] list of source VLM rows.

    Component-level mutations:
      - component["tagged_dimensions"]      = list of all tag dicts
      - component["needs_finishing_pass"]   = bool (rolled up)
      - component["inspection_time_min"]    = approx total inspection minutes
    """
    features = component.get("features") or []
    bbox     = component.get("bbox") or {}
    unit     = (vlm_extraction.get("dimension_unit") or "mm").lower()

    # Drawing-level unit override.  The VLM often mis-tags per-row units
    # ("4X 12.0±0.8" extracted as `unit: "in"` even though the title block
    # says mm) which sends `_vlm_dim_value_mm` down the wrong code path —
    # 12 "in" → 304.8 mm has no chance of matching the 12 mm feature.  We
    # only ever trust the per-row unit when it agrees with the drawing
    # default; everything else is normalised to the drawing.
    def _normalise(raw_dict: dict) -> dict:
        if not isinstance(raw_dict, dict):
            return raw_dict
        ru = (raw_dict.get("unit") or "").lower()
        if ru and ru != unit:
            normalised = dict(raw_dict)
            normalised["unit"] = unit
            return normalised
        return raw_dict

    tags: list[dict] = []

    # 1. Dimensions
    for raw_orig in (vlm_extraction.get("dimensions") or []):
        if not isinstance(raw_orig, dict):
            continue
        raw = _normalise(raw_orig)
        target = _vlm_dim_value_mm(raw, default_unit=unit)
        if target is None:
            continue
        kind = _vlm_dim_kind(raw)

        plus  = _to_float(raw.get("tolerance_plus")  or raw.get("plus"))
        minus = _to_float(raw.get("tolerance_minus") or raw.get("minus"))
        tol_class, fin, insp = _classify_tolerance(plus, minus)

        if kind == "diameter":
            feat_idx, score = _match_diameter_dim(target, features)
            match_kind = "feature" if feat_idx is not None else "unmatched"
        elif kind == "linear":
            feat_idx, match_kind, score = _match_linear_dim(target, features, bbox)
        else:
            # try diameter first, fall back to linear
            feat_idx, score = _match_diameter_dim(target, features, tol=0.3)
            if feat_idx is not None:
                match_kind = "feature"
            else:
                feat_idx, match_kind, score = _match_linear_dim(target, features, bbox)

        face_ids: list[int] = []
        if feat_idx is not None:
            face_ids = list((features[feat_idx].get("face_ids") or []))

        tag = {
            "source":               "dimension",
            "vlm_dim":              raw,
            "value_mm":             round(target, 4),
            "kind":                 kind,
            "tolerance_class":      tol_class,
            "matched_feature_index": feat_idx,
            "matched_face_ids":     face_ids,
            "match_kind":           match_kind,
            "match_score":          score,
            "needs_finishing":      fin,
            "needs_inspection":     insp,
        }
        tags.append(tag)
        if feat_idx is not None:
            _apply_to_feature(features[feat_idx], tag)

    # 2. GD&T callouts â€” try to match the datum/feature reference, else tag bbox
    for raw_orig in (vlm_extraction.get("gdt_callouts") or []):
        if not isinstance(raw_orig, dict):
            continue
        raw = _normalise(raw_orig)
        tol_class, fin, insp = _gdt_implications(raw)
        feat_idx = None
        face_ids: list[int] = []
        # If the callout names a hole diameter, try to match it
        target_mm = _vlm_dim_value_mm(raw, default_unit=unit)
        if target_mm:
            feat_idx, _ = _match_diameter_dim(target_mm, features, tol=0.5)
            if feat_idx is not None:
                face_ids = list((features[feat_idx].get("face_ids") or []))

        tag = {
            "source":               "gdt",
            "vlm_dim":              raw,
            "value_mm":             round(target_mm, 4) if target_mm else None,
            "kind":                 (raw.get("symbol") or raw.get("type") or "gdt"),
            "tolerance_class":      tol_class,
            "matched_feature_index": feat_idx,
            "matched_face_ids":     face_ids,
            "match_kind":           "feature" if feat_idx is not None else "bbox",
            "match_score":          1.0 if feat_idx is not None else 0.5,
            "needs_finishing":      fin,
            "needs_inspection":     insp,
        }
        tags.append(tag)
        if feat_idx is not None:
            _apply_to_feature(features[feat_idx], tag)
        else:
            # Positional GD&T on a multi-datum reference often has no nominal
            # value, so it never matches a single feature. Surface it at the
            # component level so the per-component GD&T tab is not empty.
            cb_str = raw.get("symbol") or raw.get("callout") or raw.get("type")
            if cb_str:
                component_callouts = component.setdefault("gdt_callouts", [])
                if cb_str not in component_callouts:
                    component_callouts.append(cb_str)

    # 3. Threads
    for raw_orig in (vlm_extraction.get("threads") or []):
        if not isinstance(raw_orig, dict):
            continue
        raw = _normalise(raw_orig)
        spec = str(raw.get("spec") or raw.get("label") or "")
        # Parse minor diameter from M6, M10, 1/4-20, etc.
        target_mm = _thread_minor_diameter_mm(spec)
        feat_idx, score = (None, 0.0)
        face_ids: list[int] = []
        if target_mm:
            feat_idx, score = _match_diameter_dim(target_mm, features, tol=1.0)
            if feat_idx is not None:
                face_ids = list((features[feat_idx].get("face_ids") or []))

        tag = {
            "source":               "thread",
            "vlm_dim":              raw,
            "value_mm":             round(target_mm, 4) if target_mm else None,
            "kind":                 "thread",
            "tolerance_class":      "standard",
            "matched_feature_index": feat_idx,
            "matched_face_ids":     face_ids,
            "match_kind":           "feature" if feat_idx is not None else "unmatched",
            "match_score":          score,
            "needs_finishing":      True,   # tapping is always its own op
            "needs_inspection":     False,
        }
        tags.append(tag)
        if feat_idx is not None:
            feat = features[feat_idx]
            feat.setdefault("operations", []).append("tapping")
            # Mark the matched feature as threaded so the frontend's per-component
            # Threads tab can find it. We retain the OCC's original feature_type
            # for downstream geometric code (drilled_hole etc.) but stash the
            # thread spec + flag on the feature itself.
            feat["is_threaded"]   = True
            feat["thread_spec"]   = spec
            ft = (feat.get("feature_type") or "").lower()
            if "thread" not in ft and "tap" not in ft:
                feat["feature_type"] = f"threaded_{ft or 'hole'}"
            _apply_to_feature(feat, tag)
        else:
            # No diameter match — still surface the thread on the component so
            # the UI's Threads tab reflects what the drawing actually called for.
            spec_clean = spec.strip()
            if spec_clean:
                comp_threads = component.setdefault("threads", [])
                if not any((t.get("spec") or t.get("label")) == spec_clean for t in comp_threads):
                    comp_threads.append({
                        "spec":     spec_clean,
                        "count":    raw.get("count") or raw.get("quantity"),
                        "depth_mm": raw.get("depth_mm"),
                        "is_blind": raw.get("is_blind"),
                    })

    # Roll-up
    component["tagged_dimensions"]    = tags
    component["needs_finishing_pass"] = any(t.get("needs_finishing") for t in tags)
    component["inspection_time_min"]  = round(
        sum(0.5 for t in tags if t.get("needs_inspection")), 2
    )
    return tags


def _apply_to_feature(feat: dict, tag: dict) -> None:
    """Merge a tag into a feature: tighten tolerance_class, OR-flags, append source.

    Also copy the raw VLM tolerance values (``tolerance_plus`` /
    ``tolerance_minus``) and GD&T callouts onto the feature itself so the
    frontend's per-component Tolerances / GD&T tabs render the actual
    drawing values. Multiple dimensions can match the same feature; in
    that case we keep the TIGHTEST tolerance (smallest absolute value),
    and union the GD&T callout strings."""
    cls = tag.get("tolerance_class") or "standard"
    cur = feat.get("tolerance_class") or "loose"
    if _TOL_RANK[cls] < _TOL_RANK.get(cur, 99):
        feat["tolerance_class"] = cls
    feat["needs_finishing"]  = bool(feat.get("needs_finishing"))  or bool(tag.get("needs_finishing"))
    feat["needs_inspection"] = bool(feat.get("needs_inspection")) or bool(tag.get("needs_inspection"))

    raw = tag.get("vlm_dim") or {}
    if tag.get("source") == "dimension":
        plus  = _to_float(raw.get("tolerance_plus")  or raw.get("plus"))
        minus = _to_float(raw.get("tolerance_minus") or raw.get("minus"))
        if plus is not None:
            cur_plus = feat.get("tolerance_plus")
            if cur_plus is None or abs(plus) < abs(cur_plus):
                feat["tolerance_plus"] = plus
        if minus is not None:
            cur_minus = feat.get("tolerance_minus")
            if cur_minus is None or abs(minus) < abs(cur_minus):
                feat["tolerance_minus"] = minus
    elif tag.get("source") == "gdt":
        # Append raw callout strings to the feature so per-component GD&T
        # tab can list them.  Dedup by exact string.
        callout = raw.get("symbol") or raw.get("callout") or raw.get("text")
        if callout:
            existing = feat.setdefault("gdt_callouts", [])
            if callout not in existing:
                existing.append(callout)

    feat.setdefault("tagged_dimensions", []).append({
        "source":           tag.get("source"),
        "value_mm":         tag.get("value_mm"),
        "tolerance_class":  tag.get("tolerance_class"),
        "match_score":      tag.get("match_score"),
    })


_TOL_RANK = {"ground": 0, "tight": 1, "standard": 2, "rough": 3, "loose": 4}


_THREAD_METRIC_RE = re.compile(r"\bM\s*(\d+(?:\.\d+)?)", re.IGNORECASE)
_THREAD_IMPERIAL_RE = re.compile(r"(\d+)\s*[/-]\s*(\d+)\s*[-x]\s*(\d+)", re.IGNORECASE)


def _thread_minor_diameter_mm(spec: str) -> float | None:
    """Parse M6 â†’ 6.0, 1/4-20 â†’ 6.35 etc. Returns nominal diameter in mm."""
    if not spec:
        return None
    m = _THREAD_METRIC_RE.search(spec)
    if m:
        return float(m.group(1))
    m = _THREAD_IMPERIAL_RE.search(spec)
    if m:
        num, den = float(m.group(1)), float(m.group(2))
        if den > 0:
            return (num / den) * 25.4
    # Fractional inch like "1/4"
    frac = re.match(r"\s*(\d+)\s*/\s*(\d+)", spec)
    if frac:
        n, d = float(frac.group(1)), float(frac.group(2))
        if d > 0:
            return (n / d) * 25.4
    return None


# ---------------------------------------------------------------------------
# Public: tag every component in an assembly
# ---------------------------------------------------------------------------

def tag_all_components(components: list[dict], vlm_extraction: dict) -> dict:
    """Tag every component and return summary statistics."""
    total_tags = 0
    finishing_count = 0
    inspection_count = 0
    for comp in components:
        tags = tag_component_dimensions(comp, vlm_extraction)
        total_tags       += len(tags)
        finishing_count  += sum(1 for t in tags if t.get("needs_finishing"))
        inspection_count += sum(1 for t in tags if t.get("needs_inspection"))

    return {
        "total_components":       len(components),
        "total_tags":             total_tags,
        "tags_needing_finishing": finishing_count,
        "tags_needing_inspection": inspection_count,
    }
