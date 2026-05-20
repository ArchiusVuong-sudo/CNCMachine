"""Merge rule-based and UV-Net feature recognition results.

Applies confidence-weighted fusion, groups adjacent same-label
faces into discrete features, and deduplicates overlapping detections.
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from typing import Optional

from .models import FeatureDetail, FeatureType

logger = logging.getLogger(__name__)

# Features where rule-based has deterministic accuracy → prefer rule-based
RULE_PREFERRED = {
    FeatureType.THROUGH_HOLE,
    FeatureType.BLIND_HOLE,
    FeatureType.COUNTERBORE,
    FeatureType.COUNTERSINK,
    FeatureType.TAPERED_BORE,
    FeatureType.TAPERED_OD,
    FeatureType.CHAMFER,
    FeatureType.FILLET,
}

# Features where UV-Net is stronger → prefer UV-Net
UVNET_PREFERRED = {
    FeatureType.BOSS,
    FeatureType.RIB,
    FeatureType.POCKET,
}


def merge_features(
    rule_features: list[FeatureDetail],
    uvnet_features: list[FeatureDetail],
    confidence_threshold: float = 0.7,
    group_identical: bool = True,
) -> list[FeatureDetail]:
    """
    Merge rule-based and UV-Net feature detections.

    Strategy:
    1. Build face → feature maps from both engines
    2. For each face claimed by both engines:
       - Both agree on type → use higher confidence
       - Disagree → trust the engine preferred for that feature type
       - Both low confidence → mark as uncertain with both candidates
    3. Group adjacent faces with same label into discrete features
    4. Deduplicate spatially overlapping features

    Args:
        rule_features: Features from rule-based engine
        uvnet_features: Features from UV-Net engine
        confidence_threshold: Confidence cutoff for "high" confidence

    Returns:
        Merged and deduplicated feature list
    """
    # ── Rule-based features pass through directly ──
    # Different detectors may intentionally share faces (e.g. a planar
    # face can be both a slot wall and a bend face).  Preserve all of them.
    all_features: list[FeatureDetail] = list(rule_features)

    # ── Merge UV-Net features ──
    # For each UV-Net detection, check overlap with rule-based features.
    # When they agree on type → boost confidence.
    # When they disagree → use RULE_PREFERRED / UVNET_PREFERRED to resolve.
    if uvnet_features:
        rule_by_face: dict[int, list[FeatureDetail]] = defaultdict(list)
        for feat in rule_features:
            for fi in feat.face_indices:
                rule_by_face[fi].append(feat)

        for uf in uvnet_features:
            # Find rule features that share faces with this UV-Net feature
            overlapping_rule: dict[str, FeatureDetail] = {}
            overlap_count = 0
            for fi in uf.face_indices:
                for rf in rule_by_face.get(fi, []):
                    overlapping_rule[rf.feature_id] = rf
                    overlap_count += 1

            if not overlapping_rule:
                # UV-Net found something the rule engine missed — add it
                # but only if above threshold
                if uf.confidence >= confidence_threshold:
                    all_features.append(uf)
                continue

            # Check if any overlapping rule feature has the same type
            same_type_rule = [
                rf for rf in overlapping_rule.values()
                if rf.feature_type == uf.feature_type
            ]
            if same_type_rule:
                # Agree on type → boost rule-based confidence (already in list)
                for rf in same_type_rule:
                    rf.confidence = min(1.0, rf.confidence + 0.1)
                continue

            # Disagree on type — resolve using preference sets
            if uf.feature_type in UVNET_PREFERRED:
                # UV-Net is stronger for this type — add UV-Net feature
                all_features.append(uf)
            # else: rule type is in RULE_PREFERRED or neither — keep rule-based

    # Deduplicate: merge features of same type at same location
    merged = _deduplicate_by_location(all_features)

    # Count identical features (unless expand mode)
    if group_identical:
        merged = _count_identical_features(merged)

    logger.info("Merged features: %d total", len(merged))
    return merged


def _deduplicate_by_location(features: list[FeatureDetail]) -> list[FeatureDetail]:
    """Remove duplicate features of the **same type** that overlap in face indices.

    Different feature types are allowed to share faces (e.g. a planar
    face can be part of both a bend and a slot).
    """
    if not features:
        return features

    # Sort by confidence descending — keep higher confidence version
    features.sort(key=lambda f: f.confidence, reverse=True)

    covered_faces_by_type: dict[str, set[int]] = defaultdict(set)
    deduped: list[FeatureDetail] = []

    for feat in features:
        feat_faces = set(feat.face_indices)
        type_key = feat.feature_type.value
        type_covered = covered_faces_by_type[type_key]
        overlap = feat_faces & type_covered

        if len(overlap) > len(feat_faces) * 0.5:
            # More than 50% of faces already covered by same-type feature
            continue

        deduped.append(feat)
        type_covered.update(feat_faces)

    return deduped


def _count_identical_features(features: list[FeatureDetail]) -> list[FeatureDetail]:
    """
    Group features of the same type with similar dimensions and report count.

    For features like "4× through-holes at Ø8mm", consolidates into
    a single entry with count=4.
    """
    if not features:
        return features

    type_groups: dict[str, list[FeatureDetail]] = defaultdict(list)
    for feat in features:
        # Create a key from type + rounded dimensions
        dim_key = _dimension_key(feat)
        group_key = f"{feat.feature_type.value}|{dim_key}"
        type_groups[group_key].append(feat)

    result: list[FeatureDetail] = []
    for group_key, group in type_groups.items():
        representative = group[0]
        all_faces = []
        for f in group:
            all_faces.extend(f.face_indices)
        result.append(FeatureDetail(
            feature_id=representative.feature_id,
            feature_type=representative.feature_type,
            count=len(group),
            confidence=sum(f.confidence for f in group) / len(group),
            source=representative.source,
            dimensions=representative.dimensions,
            perimeter_mm=representative.perimeter_mm,
            location=representative.location,
            face_indices=sorted(set(all_faces)),
            orientation=representative.orientation,
            key_face_id=representative.key_face_id,
        ))

    return result


def _dimension_key(feat: FeatureDetail) -> str:
    """Create a hashable key from rounded dimensions for grouping."""
    parts = []
    for k in sorted(feat.dimensions.keys()):
        v = feat.dimensions[k]
        if isinstance(v, (int, float)):
            parts.append(f"{k}={round(v, 1)}")
        else:
            parts.append(f"{k}={v}")
    return "|".join(parts)
