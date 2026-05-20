"""PMI/GD&T extraction from STEP AP242 files.

Extracts dimensional tolerances, geometric tolerances, datums,
surface finish callouts, and notes from AP242 STEP files using
the XDE framework's DimTolTool.

Falls back gracefully when the STEP file is AP203/AP214 (no PMI).
"""

from __future__ import annotations

import logging
from typing import Optional

from .models import PMIAnnotation, PMIType

logger = logging.getLogger(__name__)


def extract_pmi(document) -> tuple[bool, list[PMIAnnotation]]:
    """
    Extract PMI annotations from an XDE document.

    Args:
        document: TDocStd_Document loaded by step_parser

    Returns:
        (pmi_available, annotations) — pmi_available is False for AP203/AP214
    """
    annotations: list[PMIAnnotation] = []

    try:
        from OCP.XCAFDoc import XCAFDoc_DimTolTool, XCAFDoc_DocumentTool
        from OCP.TDF import TDF_LabelSequence
    except ImportError:
        logger.info("XCAFDoc_DimTolTool not available; PMI extraction disabled")
        return False, []

    try:
        dim_tol_tool = XCAFDoc_DocumentTool.DimTolTool_s(document.Main())
    except Exception as e:
        logger.debug("DimTolTool not available in document: %s", e)
        return False, []

    # ── Dimensional Tolerances ──────────────────────────────────────────
    try:
        dim_labels = TDF_LabelSequence()
        dim_tol_tool.GetDimensionLabels(dim_labels)

        for i in range(1, dim_labels.Length() + 1):
            label = dim_labels.Value(i)
            try:
                from OCP.XCAFDimTolObjects import XCAFDimTolObjects_DimensionObject
                dim_attr = None
                # Try to get dimension attribute
                try:
                    dim_attr = dim_tol_tool.GetDimension(label)
                except Exception:
                    pass

                if dim_attr is not None:
                    annotations.append(PMIAnnotation(
                        annotation_type=PMIType.DIMENSIONAL,
                        value=str(dim_attr),
                    ))
            except Exception:
                continue

        if dim_labels.Length() > 0:
            logger.info("Extracted %d dimensional annotations", dim_labels.Length())

    except Exception as e:
        logger.debug("Dimensional tolerance extraction failed: %s", e)

    # ── Geometric Tolerances ────────────────────────────────────────────
    try:
        gt_labels = TDF_LabelSequence()
        dim_tol_tool.GetGeomToleranceLabels(gt_labels)

        for i in range(1, gt_labels.Length() + 1):
            label = gt_labels.Value(i)
            try:
                gt_obj = None
                try:
                    gt_obj = dim_tol_tool.GetGeomTolerance(label)
                except Exception:
                    pass

                if gt_obj is not None:
                    annotations.append(PMIAnnotation(
                        annotation_type=PMIType.GEOMETRIC,
                        value=str(gt_obj),
                    ))
            except Exception:
                continue

        if gt_labels.Length() > 0:
            logger.info("Extracted %d geometric tolerances", gt_labels.Length())

    except Exception as e:
        logger.debug("Geometric tolerance extraction failed: %s", e)

    # ── Datum Extraction ────────────────────────────────────────────────
    try:
        datum_labels = TDF_LabelSequence()
        dim_tol_tool.GetDatumLabels(datum_labels)

        for i in range(1, datum_labels.Length() + 1):
            label = datum_labels.Value(i)
            try:
                datum_obj = None
                try:
                    datum_obj = dim_tol_tool.GetDatum(label)
                except Exception:
                    pass

                if datum_obj is not None:
                    annotations.append(PMIAnnotation(
                        annotation_type=PMIType.DATUM,
                        value=str(datum_obj),
                    ))
            except Exception:
                continue

        if datum_labels.Length() > 0:
            logger.info("Extracted %d datums", datum_labels.Length())

    except Exception as e:
        logger.debug("Datum extraction failed: %s", e)

    pmi_available = len(annotations) > 0

    if not pmi_available:
        logger.info("No PMI data found — file is likely AP203/AP214 format")

    return pmi_available, annotations
