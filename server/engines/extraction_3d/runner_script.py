"""Subprocess runner heredoc for OCC feature analysis.

The :data:`RUNNER_SCRIPT` constant is written to a tempfile each call and
executed by a child Python (which must have ``cadquery-ocp`` installed —
see :class:`GeometrySettings.occ_python`). Imports inside the heredoc use
the new ``server.engines.extraction_3d.occ`` path; the caller sets
``PYTHONPATH`` to ``<repo-root>`` (the parent of ``server/``) so the
subprocess can resolve it without installing the project as a package.

The runner's contract:
  - argv[1] = path to a STEP file
  - stdout  = exactly one JSON object on the last non-empty line
  - stderr  = structured progress logs (loader, per-component, classify,
              feature counts) which the parent forwards to its logger.
"""
from __future__ import annotations

import textwrap


RUNNER_SCRIPT = textwrap.dedent('''\
    #!/usr/bin/env python3
    """OCC subprocess runner — STEP file → per-component feature JSON."""
    import sys, os, json, traceback, uuid, time, logging
    from collections import defaultdict

    # ------------------------------------------------------------------
    # Logging — every line goes to stderr so the parent process can read
    # the single JSON result line on stdout without interleaving.
    # ------------------------------------------------------------------
    logging.basicConfig(
        level=logging.INFO,
        format="[OCC %(asctime)s %(levelname)s %(name)s] %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )
    log = logging.getLogger("extraction_3d.occ_runner")


    def _fallback(err):
        return {
            "ok": False, "_error": err,
            "request_id": uuid.uuid4().hex[:12],
            "assembly_name": "", "file_name": "",
            "component_count": 0, "unique_component_count": 0,
            "total_volume_mm3": 0.0, "pmi_available": False,
            "pmi_annotations": [], "manufacturing_processes": [],
            "components": [],
        }


    def _as_dict(obj):
        """Serialize Pydantic v1/v2 models or plain values uniformly."""
        if obj is None:
            return {}
        if isinstance(obj, dict):
            return obj
        if hasattr(obj, "model_dump"):
            return obj.model_dump()
        if hasattr(obj, "dict"):
            return obj.dict()
        return dict(obj.__dict__) if hasattr(obj, "__dict__") else {}


    if len(sys.argv) < 2:
        print(json.dumps(_fallback("Usage: runner.py <step_file>")))
        sys.exit(1)

    step_file = sys.argv[1]
    if not os.path.isfile(step_file):
        print(json.dumps(_fallback(f"File not found: {step_file}")))
        sys.exit(1)

    t0 = time.monotonic()
    log.info("runner start: %s (%d bytes)", step_file, os.path.getsize(step_file))
    try:
        # Imports from the vendored OCC subpackage.
        from server.engines.extraction_3d.occ.step_parser        import load_step_assembly
        from server.engines.extraction_3d.occ.geometry_analyzer  import analyze_geometry, compute_volume
        from server.engines.extraction_3d.occ.feature_recognizer import recognize_features_rule_based
        from server.engines.extraction_3d.occ.feature_merger     import merge_features
        from server.engines.extraction_3d.occ.feature_filter     import filter_features_by_part_type
        from server.engines.extraction_3d.occ.part_classifier    import classify_part, maybe_promote_lathe
        from server.engines.extraction_3d.occ.pmi_extractor      import extract_pmi

        t_load = time.monotonic()
        assembly_name, comps, doc, top_shape = load_step_assembly(step_file)
        log.info(
            "STEP loaded in %.2fs — assembly=%s components=%d",
            time.monotonic() - t_load, assembly_name or "?", len(comps or []),
        )

        # Assembly-level PMI is shared across all components.
        try:
            pmi_available_doc, pmi_doc_annotations = extract_pmi(doc)
        except Exception:
            pmi_available_doc, pmi_doc_annotations = False, []

        # Deduplicate leaf components by name — identical instances share geometry.
        sig_to_group = defaultdict(list)
        for c in comps:
            sig_to_group[c.name].append(c)

        out_components = []
        for idx, (sig, group) in enumerate(sig_to_group.items()):
            rep = group[0]
            shape = rep.shape
            log.info(
                "comp[%d] %s START (instances=%d)",
                idx, rep.name, len(group),
            )
            t_comp = time.monotonic()
            try:
                # 1. Geometry analysis
                geo = analyze_geometry(shape)
                _bb = _as_dict(geo.get("bounding_box"))
                log.info(
                    "comp[%d] geometry: vol=%.1fmm³ surf=%.1fmm² bbox=%.1fx%.1fx%.1f faces=%d",
                    idx, float(geo.get("volume_mm3") or 0), float(geo.get("surface_area_mm2") or 0),
                    float(_bb.get("length") or 0), float(_bb.get("width") or 0), float(_bb.get("height") or 0),
                    int(getattr(geo.get("face_type_counts"), "total", 0) or 0),
                )

                # 1b. Pre-classification (no features yet — guides detector gating)
                pre_type, _pre_conf, _ = classify_part(
                    volume_mm3=geo["volume_mm3"],
                    surface_area_mm2=geo["surface_area_mm2"],
                    bbox=geo["bounding_box"],
                    face_counts=geo["face_type_counts"],
                    thickness_stats=geo.get("thickness_stats"),
                    features=[],
                    component_name=rep.name,
                    component_description=rep.description,
                    has_closed_cross_section=geo.get("has_closed_cross_section", False),
                    rotational_symmetry=geo.get("rotational_symmetry"),
                )
                log.info(
                    "comp[%d] pre-class: %s",
                    idx, pre_type.value if hasattr(pre_type, "value") else str(pre_type),
                )

                # 2. Rule-based feature recognition
                t_feat = time.monotonic()
                rule_feats = recognize_features_rule_based(
                    shape=shape,
                    face_infos=geo["face_infos"],
                    bbox_height=geo["bounding_box"].height,
                    thickness_stats=geo.get("thickness_stats"),
                    part_type=pre_type,
                )
                _ftc = defaultdict(int)
                for f in (rule_feats or []):
                    ft = getattr(f, "feature_type", None)
                    ftk = ft.value if hasattr(ft, "value") else str(ft or "unknown")
                    _ftc[ftk] += 1
                log.info(
                    "comp[%d] rule-based features: %d total in %.2fs — %s",
                    idx, len(rule_feats or []), time.monotonic() - t_feat,
                    ", ".join(f"{k}:{v}" for k, v in sorted(_ftc.items(), key=lambda kv: -kv[1])),
                )

                # 3. Merge (UV-Net disabled — feed empty list)
                features = merge_features(rule_feats, [], group_identical=True)

                # 4. Final classification with features in hand
                part_type, confidence, _ = classify_part(
                    volume_mm3=geo["volume_mm3"],
                    surface_area_mm2=geo["surface_area_mm2"],
                    bbox=geo["bounding_box"],
                    face_counts=geo["face_type_counts"],
                    thickness_stats=geo.get("thickness_stats"),
                    features=features,
                    component_name=rep.name,
                    component_description=rep.description,
                    has_closed_cross_section=geo.get("has_closed_cross_section", False),
                    rotational_symmetry=geo.get("rotational_symmetry"),
                )

                # 4a. Auto-promote CNC_LATHE → CNC_LATHE_MILLING when milling features exist
                part_type = maybe_promote_lathe(part_type, features, geo["bounding_box"])

                _pre_filter_count = len(features or [])

                # 5. Feature filter by resolved part type
                features = filter_features_by_part_type(
                    features=features,
                    part_type=part_type,
                    thickness_stats=geo.get("thickness_stats"),
                    bbox=geo.get("bounding_box"),
                )
                log.info(
                    "comp[%d] final-class: %s conf=%.2f | filter kept %d/%d features",
                    idx,
                    part_type.value if hasattr(part_type, "value") else str(part_type),
                    float(confidence or 0),
                    len(features or []), _pre_filter_count,
                )

                # ── Serialize ────────────────────────────────────────────────
                bbox_m = geo["bounding_box"]
                bb = _as_dict(bbox_m)
                bbox_out = {
                    "length_mm": float(bb.get("length",  0) or 0),
                    "width_mm":  float(bb.get("width",   0) or 0),
                    "height_mm": float(bb.get("height",  0) or 0),
                    "x_min":     float(bb.get("x_min",   0) or 0),
                    "x_max":     float(bb.get("x_max",   0) or 0),
                    "y_min":     float(bb.get("y_min",   0) or 0),
                    "y_max":     float(bb.get("y_max",   0) or 0),
                    "z_min":     float(bb.get("z_min",   0) or 0),
                    "z_max":     float(bb.get("z_max",   0) or 0),
                }

                thickness_out = _as_dict(geo.get("thickness_stats"))

                perim = geo.get("perimeter_data")
                total_perim = 0.0
                if perim is not None:
                    perim_d = _as_dict(perim)
                    total_perim = float(perim_d.get("total_cut_length_mm", 0) or 0)

                feat_dicts = []
                for f in features:
                    fd = _as_dict(f)
                    ft = fd.get("feature_type")
                    if hasattr(ft, "value"):
                        fd["feature_type"] = ft.value
                    # Rename face_indices → face_ids at the wire boundary so the JS
                    # A4Feature contract / Supabase a4_features.face_ids column line up.
                    fd["face_ids"] = [int(x) for x in (fd.get("face_indices") or [])]
                    fd.pop("face_indices", None)
                    loc = fd.get("location")
                    if loc is not None and not isinstance(loc, dict):
                        fd["location"] = _as_dict(loc)
                    feat_dicts.append(fd)

                pmi_out = []
                for ann in pmi_doc_annotations:
                    ad = _as_dict(ann)
                    at = ad.get("annotation_type")
                    if hasattr(at, "value"):
                        ad["annotation_type"] = at.value
                    pmi_out.append(ad)

                out_components.append({
                    "component_index":      idx,
                    "name":                 rep.name,
                    "description":          rep.description,
                    "assembly_path":        getattr(rep, "assembly_path", ""),
                    "instance_count":       len(group),
                    "part_type":            part_type.value if hasattr(part_type, "value") else str(part_type),
                    "part_type_confidence": round(float(confidence), 4),
                    "volume_mm3":           round(float(geo["volume_mm3"]), 3),
                    "surface_area_mm2":     round(float(geo["surface_area_mm2"]), 3),
                    "bbox":                 bbox_out,
                    "thickness":            thickness_out,
                    "total_perimeter_mm":   round(total_perim, 3),
                    "features":             feat_dicts,
                    "pmi_available":        bool(pmi_available_doc),
                    "pmi_annotations":      pmi_out,
                })
                log.info("comp[%d] DONE in %.2fs", idx, time.monotonic() - t_comp)
            except Exception as ec:
                log.exception("comp[%d] FAILED: %s", idx, ec)
                out_components.append({
                    "component_index":      idx,
                    "name":                 getattr(rep, "name", f"Component_{idx}"),
                    "description":          getattr(rep, "description", ""),
                    "assembly_path":        getattr(rep, "assembly_path", ""),
                    "instance_count":       len(group),
                    "part_type":            "unknown",
                    "part_type_confidence": 0.0,
                    "volume_mm3":           0.0,
                    "surface_area_mm2":     0.0,
                    "bbox":                 {},
                    "thickness":            {},
                    "total_perimeter_mm":   0.0,
                    "features":             [],
                    "pmi_available":        False,
                    "pmi_annotations":      [],
                    "_error":               f"Component analysis failed: {ec}",
                    "_traceback":           traceback.format_exc(limit=3),
                })

        # Assembly total volume
        if out_components:
            total_vol = sum(
                (c.get("volume_mm3") or 0.0) * (c.get("instance_count") or 1)
                for c in out_components
            )
        elif top_shape is not None:
            try:
                total_vol = float(compute_volume(top_shape))
            except Exception:
                total_vol = 0.0
        else:
            total_vol = 0.0

        total_components = sum(c.get("instance_count", 1) for c in out_components)

        assembly_pmi_out = []
        for ann in pmi_doc_annotations:
            ad = _as_dict(ann)
            at = ad.get("annotation_type")
            if hasattr(at, "value"):
                ad["annotation_type"] = at.value
            assembly_pmi_out.append(ad)

        result = {
            "ok":                      True,
            "request_id":              uuid.uuid4().hex[:12],
            "assembly_name":           assembly_name,
            "file_name":               os.path.basename(step_file),
            "component_count":         total_components,
            "unique_component_count":  len(out_components),
            "total_volume_mm3":        round(total_vol, 3),
            "pmi_available":           bool(pmi_available_doc),
            "pmi_annotations":         assembly_pmi_out,
            "manufacturing_processes": [],
            "components":              out_components,
            "processing_time_seconds": round(time.monotonic() - t0, 3),
        }
        print(json.dumps(result, default=str))
        sys.exit(0)

    except Exception as exc:
        err = _fallback(str(exc))
        err["traceback"] = traceback.format_exc()
        print(json.dumps(err))
        sys.exit(2)
''')
