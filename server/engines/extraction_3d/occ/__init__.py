"""Vendored OCC feature recognizer used by the extraction_3d subprocess.

Verbatim port of customer's StepAnalyzer_extracted (the gold-standard
rule-based engine for XDE assembly decomposition and B-Rep feature
recognition). Uses cadquery-ocp (OCP.*) bindings, so this package only
imports cleanly inside a Python env that has cadquery-ocp installed —
which is why the rest of the server treats it as a child-process payload
rather than a directly importable module.

Modules
-------
models              — Pydantic types (PartType, FeatureType, BoundingBox, ...)
ocp_compat          — _s static-method suffix helper for cadquery-ocp vs conda OCP
step_parser         — XDE STEPCAFControl_Reader assembly decomposition
pmi_extractor       — GD&T / PMI extraction from AP242
geometry_analyzer   — Volume, bbox, face classification, thickness, perimeters
feature_recognizer  — Rule-based B-Rep feature detectors (~5k LOC)
feature_merger      — Rule-based + UV-Net feature fusion (we feed [] for UV-Net)
feature_filter      — Part-type-driven feature validity filter
part_classifier     — 6/7-class part type scorer (geometry + keywords)

Inter-module imports are all relative (``from .models import …``) so the
subpackage can be relocated without code edits.
"""
